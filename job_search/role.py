"""岗位搜索角色：校验并保存结构化岗位与原子要求，不解析岗位描述。"""

from __future__ import annotations

from typing import Any

from memory import MemoryStore


def _text(value: Any) -> str:
    """只接受去掉首尾空白后的非空字符串。数字等类型不能当岗位字段。

    参数:
        value: Agent 传入的字段。
    返回:
        去空白后的字符串；类型不对时为空串，供调用方判无效。
    """
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: Any) -> tuple[bool, str | None]:
    """可空字段空白落成 None，与 jobs 表可空 TEXT 一致。

    参数:
        value: Agent 传入的字段；缺省为 None。
    返回:
        (是否合法, 写入用文本)。非字符串视为无效，避免把数字当薪资文本。
    """
    if value is None:
        return True, None
    if not isinstance(value, str):
        return False, None
    return True, value.strip() or None


class JobSearchRole:
    """校验通用 Agent 给出的岗位与原子要求并写入记忆。不隐式触发知识搜索。"""

    def __init__(self, store: MemoryStore) -> None:
        """绑定共享记忆。

        参数:
            store: 已初始化的 MemoryStore。
        返回:
            None。
        """
        self._store = store

    def search(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        """整批校验后写入公开岗位，并保存随附的原子要求。

        不解析 description：要求必须由 Agent 给出 name 与 evidence。
        存储按条 commit；先备齐整批，避免后一条失败后前一条已落库。

        已保存岗位是不可变快照：save_job 会覆盖字段，但旧 job_requirements
        不会删除，重复 job_id 再写入会使岗位与要求漂移。同一次输入里
        尚未 commit 的首次条目也按已确定快照处理，避免第二条抢先覆盖。

        参数:
            jobs: 公开岗位列表。每项含 source、source_url、title，以及
                requirements 列表；可选 job_id、city、salary、description。
                每条要求至少含非空 name 与原文 evidence。
                库中已有或本批已出现的 job_id 直接复用，不校验其余字段。
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
            if job_id:
                # 库中快照和本批首次条目都不可变；后出现的同 ID 不能再走 save_job
                if job_id in seen_ids or self._store.get_job(job_id):
                    pending.append({"reused": True, "job_id": job_id})
                    seen_ids.add(job_id)
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
            if job_id:
                seen_ids.add(job_id)
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
                    existing = self._store.get_job(job_id)
                    snapshots[job_id] = self._with_requirements(existing)
                saved.append({**snapshots[job_id], "reused": True})
                continue
            items = item.pop("items")
            item.pop("reused")
            job = self._store.save_job(**item)
            for name, evidence in items:
                requirement = self._store.save_requirement(name)
                self._store.link_job_requirement(
                    job["job_id"], requirement["requirement_id"], evidence
                )
            snapshot = self._with_requirements(job)
            snapshots[job["job_id"]] = snapshot
            saved.append({**snapshot, "reused": False})
        return {"jobs": saved}

    def get(self, job_id: str) -> dict[str, Any]:
        """按稳定 job_id 读取岗位及其原子要求。

        参数:
            job_id: 岗位稳定 ID。
        返回:
            岗位 dict（含 requirements）；不存在时
            {missing: "job_id", job_id: str}。
        """
        job = self._store.get_job(job_id)
        if job is None:
            return {"missing": "job_id", "job_id": job_id}
        return self._with_requirements(job)

    def _with_requirements(self, job: dict[str, Any]) -> dict[str, Any]:
        """给岗位补上关联要求。get 与 search 共用，避免读路径漏掉 evidence。

        参数:
            job: MemoryStore.get_job / save_job 返回的岗位 dict。
        返回:
            岗位字段加上 requirements 列表。
        """
        links = self._store.list_job_requirements(job_id=job["job_id"])
        requirements = []
        for link in links:
            requirement = self._store.get_requirement(link["requirement_id"])
            requirements.append(
                {
                    "requirement_id": requirement["requirement_id"],
                    "name": requirement["name"],
                    "normalized_name": requirement["normalized_name"],
                    "evidence": link["evidence"],
                }
            )
        return {**job, "requirements": requirements}
