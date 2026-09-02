#!/usr/bin/env python3
"""Skill 内部 JSON 工具：一次进程只处理一个请求。"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# 从任意工作目录调用脚本时仍能 import 仓库内 MemoryStore
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory import MemoryStore

# 所有新会话共用这一处；不接受请求字段或环境变量覆盖，避免记忆分叉
DEFAULT_DB_PATH = "~/.offerskills/jobseeker.db"

ACTIONS = frozenset(
    {
        "save_jobs",
        "get_job",
        "list_jobs",
        "list_requirements",
        "save_chunks",
        "get_chunk",
        "list_chunks",
        "save_questions",
        "get_question",
        "list_questions",
        "save_score",
        "get_score",
        "list_scores",
    }
)


class RequestError(ValueError):
    """请求字段类型或动作名不合法，尚未进入业务校验。"""


def db_path() -> Path:
    """展开默认库路径。

    参数:
        无。
    返回:
        展开 ~ 后的 Path。
    """
    return Path(DEFAULT_DB_PATH).expanduser()


def write_json(payload: dict[str, Any]) -> None:
    """只向 stdout 写一个 JSON object，避免日志混入。

    参数:
        payload: 成功或失败响应。
    返回:
        None。
    """
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def field_str(request: dict[str, Any], key: str) -> str:
    """读取动作所需的稳定 ID 字符串。

    不在这里做非空或业务校验：缺字段是协议错误，内容合法性交给写入校验。

    参数:
        request: 请求 object。
        key: 字段名。
    返回:
        调用方给出的原样字符串。
    """
    value = request.get(key)
    if not isinstance(value, str):
        raise RequestError(f"缺少 {key}")
    return value


def optional_str(request: dict[str, Any], key: str) -> str | None:
    """读取可选过滤字段。缺省表示列出全部，由 Agent 自行判断。

    参数:
        request: 请求 object。
        key: 字段名。
    返回:
        字符串或 None。
    """
    if key not in request:
        return None
    value = request[key]
    if not isinstance(value, str):
        raise RequestError(f"缺少 {key}")
    return value


def _text(value: Any) -> str:
    """只接受去掉首尾空白后的非空字符串。数字等类型不能当业务字段。

    参数:
        value: Agent 传入的字段。
    返回:
        去空白后的字符串；类型不对时为空串，供调用方判无效。
    """
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: Any) -> tuple[bool, str | None]:
    """可空字段空白落成 None，与表中可空 TEXT 一致。

    参数:
        value: Agent 传入的字段；缺省为 None。
    返回:
        (是否合法, 写入用文本)。非字符串视为无效，避免把数字当文本。
    """
    if value is None:
        return True, None
    if not isinstance(value, str):
        return False, None
    return True, value.strip() or None


def _number(value: Any) -> float | None:
    """只接受有限数字。bool 是 int 子类，但不能当分数。

    float 对超大 int 会 OverflowError；NaN/Inf 能通过类型检查，但比较不稳定，
    必须在写入前拦掉，避免半合法评分落库。

    参数:
        value: Agent 传入的 score 或 max_score。
    返回:
        有限 float；类型不对、非有限、或转换失败时为 None。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _job_with_requirements(store: MemoryStore, job: dict[str, Any]) -> dict[str, Any]:
    """给岗位补上关联要求。get 与 list 共用，避免读路径漏掉 evidence。

    参数:
        store: 已打开的共享记忆。
        job: MemoryStore.get_job / save_job / list_jobs 返回的岗位 dict。
    返回:
        岗位字段加上 requirements 列表。
    """
    links = store.list_job_requirements(job_id=job["job_id"])
    requirements = []
    for link in links:
        requirement = store.get_requirement(link["requirement_id"])
        requirements.append(
            {
                "requirement_id": requirement["requirement_id"],
                "name": requirement["name"],
                "normalized_name": requirement["normalized_name"],
                "evidence": link["evidence"],
            }
        )
    return {**job, "requirements": requirements}


def save_jobs(store: MemoryStore, jobs: Any) -> dict[str, Any]:
    """整批校验后写入公开岗位，并保存随附的原子要求。

    不解析 description：要求必须由 Agent 给出 name 与 evidence。
    存储按条 commit；先备齐整批，避免后一条失败后前一条已落库。

    已保存岗位是不可变快照：save_job 会覆盖字段，但旧 job_requirements
    不会删除，重复 job_id 再写入会使岗位与要求漂移。同一次输入里
    尚未 commit 的首次条目也按已确定快照处理，避免第二条抢先覆盖。

    参数:
        store: 已打开的共享记忆。
        jobs: 公开岗位列表。每项含 source、source_url、title，以及
            requirements 列表；可选 job_id、city、salary、description。
            每条要求至少含非空 name 与原文 evidence。
            库中已有或本批已出现的 job_id 仍须完整校验当前输入；
            通过后才复用快照，不覆盖字段、不追加要求。
    返回:
        {jobs: list[dict]}。每项含 job_id、source、source_url、title、city、
        salary、description、reused，以及 requirements。
        reused 为 true 表示该项来自首次已准备或已保存快照。
        requirements 每项含 requirement_id、name、normalized_name、evidence。
    """
    if not isinstance(jobs, list):
        raise ValueError("岗位或要求无效")

    pending: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    invalid = False
    for listing in jobs:
        if not isinstance(listing, dict):
            invalid = True
            continue
        job_id_ok, job_id = _optional_text(listing.get("job_id"))
        if not job_id_ok:
            invalid = True
            continue

        source = _text(listing.get("source"))
        source_url = _text(listing.get("source_url"))
        title = _text(listing.get("title"))
        city_ok, city = _optional_text(listing.get("city"))
        salary_ok, salary = _optional_text(listing.get("salary"))
        desc_ok, description = _optional_text(listing.get("description"))
        raw_requirements = listing.get("requirements")
        items: list[tuple[str, str]] = []
        reqs_ok = isinstance(raw_requirements, list)
        if reqs_ok:
            for item in raw_requirements:
                if not isinstance(item, dict):
                    reqs_ok = False
                    continue
                name = _text(item.get("name"))
                evidence = _text(item.get("evidence"))
                # 缺 name 或 evidence 等于 Agent 没给出原子要求，不能靠描述补
                if not name or not evidence:
                    reqs_ok = False
                    continue
                items.append((name, evidence))

        if not (
            source
            and source_url
            and title
            and city_ok
            and salary_ok
            and desc_ok
            and reqs_ok
        ):
            invalid = True
            continue
        # 先校验再谈复用：无效重复项若提前 continue，同批新岗位会被放行
        reused = bool(job_id and (job_id in seen_ids or store.get_job(job_id)))
        if job_id:
            seen_ids.add(job_id)
        if reused:
            pending.append({"reused": True, "job_id": job_id})
            continue
        pending.append(
            {
                "reused": False,
                "job_id": job_id,
                "source": source,
                "source_url": source_url,
                "title": title,
                "city": city,
                "salary": salary,
                "description": description,
                "items": items,
            }
        )

    if invalid:
        raise ValueError("岗位或要求无效")

    saved = []
    snapshots: dict[str, dict[str, Any]] = {}
    for item in pending:
        if item["reused"]:
            job_id = item["job_id"]
            if job_id not in snapshots:
                existing = store.get_job(job_id)
                snapshots[job_id] = _job_with_requirements(store, existing)
            saved.append({**snapshots[job_id], "reused": True})
            continue
        items = item.pop("items")
        item.pop("reused")
        job = store.save_job(**item)
        for name, evidence in items:
            requirement = store.save_requirement(name)
            store.link_job_requirement(
                job["job_id"], requirement["requirement_id"], evidence
            )
        snapshot = _job_with_requirements(store, job)
        snapshots[job["job_id"]] = snapshot
        saved.append({**snapshot, "reused": False})
    return {"jobs": saved}


def get_job(store: MemoryStore, job_id: str) -> dict[str, Any]:
    """按稳定 job_id 读取岗位及其原子要求。

    参数:
        store: 已打开的共享记忆。
        job_id: 岗位稳定 ID。
    返回:
        岗位 dict（含 requirements）；不存在时
        {missing: "job_id", job_id: str}。
    """
    job = store.get_job(job_id)
    if job is None:
        return {"missing": "job_id", "job_id": job_id}
    return _job_with_requirements(store, job)


def list_jobs(store: MemoryStore) -> dict[str, Any]:
    """列出全部岗位及其原子要求。

    参数:
        store: 已打开的共享记忆。
    返回:
        {jobs: list[dict]}，顺序为写入顺序。
    """
    return {
        "jobs": [_job_with_requirements(store, job) for job in store.list_jobs()]
    }


def list_requirements(store: MemoryStore, job_id: str | None) -> dict[str, Any]:
    """列出原子岗位要求。给 job_id 时只返回该岗位已关联的要求。

    参数:
        store: 已打开的共享记忆。
        job_id: 可选岗位 ID。
    返回:
        {requirements: list[dict]}。按岗位过滤时每项另含 evidence。
        岗位不存在时列表为空，不写成 missing：list 不是按 ID 回找。
    """
    if job_id is None:
        return {"requirements": store.list_requirements()}
    links = store.list_job_requirements(job_id=job_id)
    requirements = []
    for link in links:
        requirement = store.get_requirement(link["requirement_id"])
        requirements.append(
            {
                "requirement_id": requirement["requirement_id"],
                "name": requirement["name"],
                "normalized_name": requirement["normalized_name"],
                "evidence": link["evidence"],
            }
        )
    return {"requirements": requirements}


def save_chunks(store: MemoryStore, chunks: Any) -> dict[str, Any]:
    """整批校验后写入知识切片。不搜索、不总结、不按已有切片自动复用。

    复用由 Agent 先 list_chunks 决定。工具只拦结构与外键，避免半批落库。

    参数:
        store: 已打开的共享记忆。
        chunks: 切片列表。每项含非空 requirement_id、title、content、
            source_url、evidence；chunk_id 可选。
    返回:
        缺失要求: {missing: "requirement_id", requirement_ids: list[str]}
        命中写入: {chunks: list[dict]}
    """
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("知识切片无效")

    pending: list[dict[str, str]] = []
    missing: list[str] = []
    seen_missing: set[str] = set()
    invalid = False
    for chunk in chunks:
        if not isinstance(chunk, dict):
            invalid = True
            continue
        requirement_id = _text(chunk.get("requirement_id"))
        title = _text(chunk.get("title"))
        content = _text(chunk.get("content"))
        source_url = _text(chunk.get("source_url"))
        evidence = _text(chunk.get("evidence"))
        chunk_id_ok, chunk_id = _optional_text(chunk.get("chunk_id"))
        if not (
            requirement_id
            and title
            and content
            and source_url
            and evidence
            and chunk_id_ok
        ):
            invalid = True
            continue
        if store.get_requirement(requirement_id) is None:
            if requirement_id not in seen_missing:
                seen_missing.add(requirement_id)
                missing.append(requirement_id)
            continue
        item = {
            "requirement_id": requirement_id,
            "title": title,
            "content": content,
            "source_url": source_url,
            "evidence": evidence,
        }
        if chunk_id is not None:
            item["chunk_id"] = chunk_id
        pending.append(item)

    if missing:
        return {"missing": "requirement_id", "requirement_ids": missing}
    if invalid:
        raise ValueError("知识切片无效")
    return {"chunks": store.save_knowledge_chunks(pending)}


def get_chunk(store: MemoryStore, chunk_id: str) -> dict[str, Any]:
    """按稳定 chunk_id 读取知识切片。

    参数:
        store: 已打开的共享记忆。
        chunk_id: 切片稳定 ID。
    返回:
        切片 dict；不存在时 {missing: "chunk_id", chunk_id: str}。
    """
    found = store.get_knowledge_chunk(chunk_id)
    if found is None:
        return {"missing": "chunk_id", "chunk_id": chunk_id}
    return found


def list_chunks(store: MemoryStore, requirement_id: str | None) -> dict[str, Any]:
    """列出知识切片。

    参数:
        store: 已打开的共享记忆。
        requirement_id: 可选岗位要求 ID。
    返回:
        {chunks: list[dict]}。
    """
    return {"chunks": store.list_knowledge_chunks(requirement_id)}


def save_questions(store: MemoryStore, drafts: Any) -> dict[str, Any]:
    """校验草稿后保存题目。不把知识正文复制为标准答案或解析。

    存储按条 commit；先校验全部 chunk_id 与草稿，避免半套练习题落库。
    同一切片对应同一题，重复出题覆盖题面，避免堆出重复练习项。

    参数:
        store: 已打开的共享记忆。
        drafts: 题目草稿列表。每项至少含 chunk_id、prompt、standard_answer、
            explanation。三段文本必须非空，且 standard_answer 与 explanation
            不得完全相同。
    返回:
        缺失资料: {missing: "chunk_id", chunk_ids: list[str]}
        成功: {questions: list[dict]}
        每道题含 question_id, requirement_id, prompt, standard_answer, explanation。
    """
    if not isinstance(drafts, list) or not drafts:
        raise ValueError("题目草稿无效")

    missing: list[str] = []
    pending: list[dict[str, str]] = []
    invalid = False
    for draft in drafts:
        if not isinstance(draft, dict):
            invalid = True
            continue
        chunk_id = _text(draft.get("chunk_id"))
        prompt = _text(draft.get("prompt"))
        answer = _text(draft.get("standard_answer"))
        explanation = _text(draft.get("explanation"))
        # 答案与解析相同等于没解析，不能等写入后再发现
        draft_ok = bool(
            chunk_id and prompt and answer and explanation and answer != explanation
        )
        if not draft_ok:
            invalid = True
        if not chunk_id:
            continue
        chunk = store.get_knowledge_chunk(chunk_id)
        if chunk is None:
            missing.append(chunk_id)
            continue
        if draft_ok:
            pending.append(
                {
                    "question_id": f"q-{chunk_id}",
                    "requirement_id": chunk["requirement_id"],
                    "prompt": prompt,
                    "standard_answer": answer,
                    "explanation": explanation,
                }
            )

    if missing:
        return {"missing": "chunk_id", "chunk_ids": missing}
    if invalid:
        raise ValueError("题目草稿无效")

    questions = [store.save_question(**item) for item in pending]
    return {"questions": questions}


def get_question(store: MemoryStore, question_id: str) -> dict[str, Any]:
    """按稳定 question_id 回找完整题目。

    参数:
        store: 已打开的共享记忆。
        question_id: 题目稳定 ID。
    返回:
        题目 dict；不存在时 {missing: "question_id", question_id: str}。
    """
    found = store.get_question(question_id)
    if found is None:
        return {"missing": "question_id", "question_id": question_id}
    return found


def list_questions(store: MemoryStore, requirement_id: str | None) -> dict[str, Any]:
    """列出题目。

    参数:
        store: 已打开的共享记忆。
        requirement_id: 可选岗位要求 ID。
    返回:
        {questions: list[dict]}。
    """
    return {"questions": store.list_questions(requirement_id)}


def save_score(store: MemoryStore, question_id: str, result: Any) -> dict[str, Any]:
    """校验结构化评分结果后追加保存。同一题不覆盖历史作答。

    工具不对照标准答案改分；分数必须是有限数字，且 0 <= score <= max_score
    且 max_score > 0，避免把 Agent 的判断写进半合法记录。

    参数:
        store: 已打开的共享记忆。
        question_id: 已存在的题目稳定 ID。
        result: 评分结果。至少含 user_answer、score、max_score。
            loss_reason、weak_points 为可空文本，不能是列表或其它结构。
    返回:
        缺失题目: {missing: "question_id", question_id: str}
        成功: {score_id, question_id, user_answer, score, max_score,
            loss_reason, weak_points}
    """
    if store.get_question(question_id) is None:
        return {"missing": "question_id", "question_id": question_id}

    if not isinstance(result, dict):
        raise ValueError("评分结果无效")

    user_answer = _text(result.get("user_answer"))
    score = _number(result.get("score"))
    max_score = _number(result.get("max_score"))
    loss_ok, loss_reason = _optional_text(result.get("loss_reason"))
    weak_ok, weak_points = _optional_text(result.get("weak_points"))
    # 先看齐字段再写入：存储按条 commit，非有限或越界分数不能留下作答半成品
    if not (
        user_answer
        and score is not None
        and max_score is not None
        and max_score > 0
        and 0 <= score <= max_score
        and loss_ok
        and weak_ok
    ):
        raise ValueError("评分结果无效")

    return store.save_answer_score(
        question_id=question_id,
        user_answer=user_answer,
        score=score,
        max_score=max_score,
        loss_reason=loss_reason,
        weak_points=weak_points,
    )


def get_score(store: MemoryStore, score_id: str) -> dict[str, Any]:
    """按稳定 score_id 读取评分。

    参数:
        store: 已打开的共享记忆。
        score_id: 评分稳定 ID。
    返回:
        评分 dict；不存在时 {missing: "score_id", score_id: str}。
    """
    found = store.get_answer_score(score_id)
    if found is None:
        return {"missing": "score_id", "score_id": score_id}
    return found


def list_scores(store: MemoryStore, question_id: str | None) -> dict[str, Any]:
    """列出评分记录。

    参数:
        store: 已打开的共享记忆。
        question_id: 可选题目 ID。
    返回:
        {scores: list[dict]}。
    """
    return {"scores": store.list_answer_scores(question_id)}


def dispatch(action: str, request: dict[str, Any], store: MemoryStore) -> dict[str, Any]:
    """把动作转发到校验与 SQLite 读写，不搜索、不出题、不评分、不改简历。

    参数:
        action: 已识别的动作名。
        request: 完整请求 object。
        store: 已打开的共享记忆。
    返回:
        查询或写入返回的 dict，作为响应 result。
    """
    if action == "save_jobs":
        return save_jobs(store, request.get("jobs"))
    if action == "get_job":
        return get_job(store, field_str(request, "job_id"))
    if action == "list_jobs":
        return list_jobs(store)
    if action == "list_requirements":
        return list_requirements(store, optional_str(request, "job_id"))
    if action == "save_chunks":
        return save_chunks(store, request.get("chunks"))
    if action == "get_chunk":
        return get_chunk(store, field_str(request, "chunk_id"))
    if action == "list_chunks":
        return list_chunks(store, optional_str(request, "requirement_id"))
    if action == "save_questions":
        return save_questions(store, request.get("drafts"))
    if action == "get_question":
        return get_question(store, field_str(request, "question_id"))
    if action == "list_questions":
        return list_questions(store, optional_str(request, "requirement_id"))
    if action == "save_score":
        return save_score(
            store, field_str(request, "question_id"), request.get("result")
        )
    if action == "get_score":
        return get_score(store, field_str(request, "score_id"))
    if action == "list_scores":
        return list_scores(store, optional_str(request, "question_id"))
    raise RequestError(f"未知动作: {action}")


def main() -> int:
    """读 stdin JSON，写 stdout JSON，失败非零退出。

    参数:
        无。从 stdin 读一个 JSON object。
    返回:
        0 表示协议成功（查询 missing 也是 0）；1 表示非法 JSON、未知动作或校验失败。
    """
    path = db_path()
    path_text = str(path)
    try:
        request = json.loads(sys.stdin.read())
    # 过深嵌套会 RecursionError 而不是 JSONDecodeError；不捕就会把 traceback 漏到 stderr
    except (json.JSONDecodeError, RecursionError) as exc:
        write_json(
            {
                "ok": False,
                "error": "invalid_json",
                "message": str(exc),
                "db_path": path_text,
            }
        )
        return 1

    if not isinstance(request, dict):
        write_json(
            {
                "ok": False,
                "error": "invalid_request",
                "message": "请求必须是 JSON object",
                "db_path": path_text,
            }
        )
        return 1

    action = request.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        write_json(
            {
                "ok": False,
                "error": "unknown_action",
                "message": f"未知动作: {action!r}",
                "db_path": path_text,
            }
        )
        return 1

    store = None
    try:
        # sqlite 不会创建缺失的父目录，首次会话必须先建好
        path.parent.mkdir(parents=True, exist_ok=True)
        store = MemoryStore(path)
        result = dispatch(action, request, store)
        write_json(
            {
                "ok": True,
                "action": action,
                "db_path": path_text,
                "result": result,
            }
        )
        return 0
    except RequestError as exc:
        write_json(
            {
                "ok": False,
                "error": "invalid_request",
                "message": str(exc),
                "db_path": path_text,
            }
        )
        return 1
    except ValueError as exc:
        write_json(
            {
                "ok": False,
                "error": "invalid_input",
                "message": str(exc),
                "db_path": path_text,
            }
        )
        return 1
    except Exception as exc:
        write_json(
            {
                "ok": False,
                "error": "internal",
                "message": str(exc),
                "db_path": path_text,
            }
        )
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
