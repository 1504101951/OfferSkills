#!/usr/bin/env python3
"""Skill 内部 JSON 工具：一次进程只处理一个请求。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# 从任意工作目录调用脚本时仍能 import 仓库内四个角色
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from job_search import JobSearchRole
from knowledge_search import KnowledgeSearchRole
from memory import MemoryStore
from question import QuestionRole
from scoring import ScoringRole

# 所有新会话共用这一处；不接受请求字段或环境变量覆盖，避免记忆分叉
DEFAULT_DB_PATH = "~/.offerskills/jobseeker.db"

ACTIONS = frozenset(
    {
        "save_jobs",
        "get_job",
        "search_knowledge",
        "get_chunk",
        "save_questions",
        "get_question",
        "save_score",
        "get_score",
    }
)


class RequestError(ValueError):
    """请求字段类型或动作名不合法，尚未进入角色校验。"""


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

    不在这里做非空或业务校验：缺字段是协议错误，内容合法性交给角色。

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


def dispatch(action: str, request: dict[str, Any], store: MemoryStore) -> dict[str, Any]:
    """把动作转发到角色或最小查询接口，不复制业务校验。

    参数:
        action: 已识别的动作名。
        request: 完整请求 object。
        store: 已打开的共享记忆。
    返回:
        角色或查询返回的 dict，作为响应 result。
    """
    if action == "save_jobs":
        return JobSearchRole(store).search(request.get("jobs"))
    if action == "get_job":
        return JobSearchRole(store).get(field_str(request, "job_id"))
    if action == "search_knowledge":
        chunks = request["chunks"] if "chunks" in request else None
        return KnowledgeSearchRole(store).search(
            field_str(request, "requirement_id"), chunks
        )
    if action == "get_chunk":
        chunk_id = field_str(request, "chunk_id")
        found = store.get_knowledge_chunk(chunk_id)
        if found is None:
            return {"missing": "chunk_id", "chunk_id": chunk_id}
        return found
    if action == "save_questions":
        requirement_id = request.get("requirement_id")
        if requirement_id is not None and not isinstance(requirement_id, str):
            raise RequestError("缺少 requirement_id")
        drafts = request["drafts"] if "drafts" in request else None
        return QuestionRole(store).generate(requirement_id, drafts=drafts)
    if action == "get_question":
        return QuestionRole(store).get(field_str(request, "question_id"))
    if action == "save_score":
        return ScoringRole(store).score(
            field_str(request, "question_id"), request.get("result")
        )
    if action == "get_score":
        score_id = field_str(request, "score_id")
        found = store.get_answer_score(score_id)
        if found is None:
            return {"missing": "score_id", "score_id": score_id}
        return found
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
