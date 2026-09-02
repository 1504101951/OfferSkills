"""知识搜索角色：按 requirement_id 复用或写入带来源的学习资料切片。"""

from __future__ import annotations

from typing import Any

from memory import MemoryStore


def _split_content(content: str) -> list[str]:
    """按空行切成片段。整篇入库会让后续出题范围过大。

    参数:
        content: 公开资料正文。
    返回:
        去空白后的非空段落列表；无空行时为单元素列表。
    """
    return [part.strip() for part in content.split("\n\n") if part.strip()]


class KnowledgeSearchRole:
    """围绕已有岗位要求收集公开学习资料，优先返回已保存切片。"""

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
        documents: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """按 requirement_id 取学习资料；已有则复用，否则整批校验切分后再写入。

        参数:
            requirement_id: 岗位要求稳定 ID。
            documents: 公开资料列表，每项为 {title, content, source_url}。
                已有切片时可省略。source_url 必填；切分后须有非空正文。
        返回:
            缺失要求: {missing: "requirement_id", requirement_id: str}
            命中或写入: {requirement_id: str, reused: bool, chunks: list[dict]}
            chunks 每项含 chunk_id, requirement_id, title, content, source_url。
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

        # 存储按条 commit；先备齐整批，避免后一份失败后前一份被复用
        pending: list[dict[str, str]] = []
        for document in documents or []:
            source_url = (document.get("source_url") or "").strip()
            if not source_url:
                raise ValueError("公开资料必须包含 source_url")
            title = (document.get("title") or "").strip() or requirement["name"]
            pieces = _split_content(document.get("content") or "")
            if not pieces:
                raise ValueError("公开资料内容无效")
            for piece in pieces:
                pending.append(
                    {
                        "source_url": source_url,
                        "title": title,
                        "content": piece,
                    }
                )

        chunks = [
            self._store.save_knowledge_chunk(requirement_id=requirement_id, **item)
            for item in pending
        ]
        return {
            "requirement_id": requirement_id,
            "reused": False,
            "chunks": chunks,
        }
