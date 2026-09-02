"""知识搜索角色：校验并保存 Agent 给出的语义完整知识切片。"""

from __future__ import annotations

from typing import Any

from memory import MemoryStore


def _text(value: Any) -> str:
    """只接受去掉首尾空白后的非空字符串。数字等类型不能当切片字段。

    参数:
        value: Agent 传入的字段。
    返回:
        去空白后的字符串；类型不对时为空串，供调用方判无效。
    """
    return value.strip() if isinstance(value, str) else ""


class KnowledgeSearchRole:
    """校验通用 Agent 给出的知识切片并写入记忆。不隐式触发出题。"""

    def __init__(self, store: MemoryStore) -> None:
        """绑定共享记忆。不隐式触发岗位搜索或出题。

        参数:
            store: 已初始化的 MemoryStore。
        返回:
            None。
        """
        self._store = store

    def search(
        self,
        requirement_id: str,
        chunks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """按 requirement_id 取学习资料；已有则复用，否则整批校验后事务写入。

        不按空行或字数切分：切片必须由 Agent 给出语义完整的 title/content。

        参数:
            requirement_id: 岗位要求稳定 ID。
            chunks: Agent 已切好的切片列表。每项含非空 requirement_id、title、
                content、source_url、evidence；requirement_id 须与外层参数一致。
                已有切片时可省略。
        返回:
            缺失要求: {missing: "requirement_id", requirement_id: str}
            命中或写入: {requirement_id: str, reused: bool, chunks: list[dict]}
            chunks 每项含 chunk_id, requirement_id, title, content, source_url, evidence。
        """
        requirement = self._store.get_requirement(requirement_id)
        if requirement is None:
            return {"missing": "requirement_id", "requirement_id": requirement_id}

        existing = self._store.list_knowledge_chunks(requirement_id)
        if existing:
            return {
                "requirement_id": requirement_id,
                "reused": True,
                "chunks": existing,
            }

        if chunks is None:
            return {
                "requirement_id": requirement_id,
                "reused": False,
                "chunks": [],
            }

        if not isinstance(chunks, list) or not chunks:
            raise ValueError("知识切片无效")

        pending: list[dict[str, str]] = []
        invalid = False
        for chunk in chunks:
            if not isinstance(chunk, dict):
                invalid = True
                continue
            # 缺字段不能用外层参数补：否则 Agent 未声明归属的切片也会入库
            chunk_req = _text(chunk.get("requirement_id"))
            title = _text(chunk.get("title"))
            content = _text(chunk.get("content"))
            source_url = _text(chunk.get("source_url"))
            evidence = _text(chunk.get("evidence"))
            if not (
                chunk_req == requirement_id
                and title
                and content
                and source_url
                and evidence
            ):
                invalid = True
                continue
            pending.append(
                {
                    "requirement_id": chunk_req,
                    "title": title,
                    "content": content,
                    "source_url": source_url,
                    "evidence": evidence,
                }
            )

        if invalid:
            raise ValueError("知识切片无效")

        saved = self._store.save_knowledge_chunks(pending)
        return {
            "requirement_id": requirement_id,
            "reused": False,
            "chunks": saved,
        }
