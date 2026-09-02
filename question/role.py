"""出题角色：校验并保存题目草稿，不隐式搜索资料，也不用模板伪造内容。"""

from __future__ import annotations

from typing import Any

from memory import MemoryStore


def _text(value: Any) -> str:
    """只接受去掉首尾空白后的非空字符串。数字等类型不能当题面。"""
    return value.strip() if isinstance(value, str) else ""


class QuestionRole:
    """校验通用 Agent 给出的题目草稿并写入记忆。缺少记忆时只报告稳定 ID。"""

    def __init__(self, store: MemoryStore) -> None:
        """绑定共享记忆。不隐式触发知识搜索或打分。

        参数:
            store: 已初始化的 MemoryStore。
        返回:
            None。
        """
        self._store = store

    def generate(
        self,
        requirement_id: str | None = None,
        *,
        drafts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """校验草稿后保存题目。不把知识正文复制为标准答案或解析。

        存储按条 commit；先校验全部 chunk_id 与草稿，避免半套练习题落库。

        参数:
            requirement_id: 岗位要求稳定 ID。可与 drafts 同时提供；单独提供时
                只检查记忆是否齐全。
            drafts: 题目草稿列表。每项至少含 chunk_id、prompt、standard_answer、
                explanation。三段文本必须非空，且 standard_answer 与 explanation
                不得完全相同。
        返回:
            缺失要求: {missing: "requirement_id", requirement_id: str}
            缺失资料: {missing: "chunk_id", requirement_id: str}
                或 {missing: "chunk_id", chunk_ids: list[str]}
            成功: {questions: list[dict]}；传入 requirement_id 时另含该字段。
            每道题含 question_id, requirement_id, prompt, standard_answer, explanation。
        """
        if requirement_id is None and drafts is None:
            raise ValueError("requirement_id 或 drafts 必须提供其一")

        if requirement_id is not None:
            if self._store.get_requirement(requirement_id) is None:
                return {"missing": "requirement_id", "requirement_id": requirement_id}
            if not self._store.list_knowledge_chunks(requirement_id):
                # 缺资料只报 ID：出题不调用知识搜索，避免角色耦合
                return {"missing": "chunk_id", "requirement_id": requirement_id}

        if not drafts:
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
            chunk = self._store.get_knowledge_chunk(chunk_id)
            if chunk is None:
                missing.append(chunk_id)
                continue
            if requirement_id is not None and chunk["requirement_id"] != requirement_id:
                invalid = True
                continue
            if draft_ok:
                # 同一切片对应同一题，重复出题覆盖题面，避免堆出重复练习项
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

        questions = [self._store.save_question(**item) for item in pending]
        result: dict[str, Any] = {"questions": questions}
        if requirement_id is not None:
            result["requirement_id"] = requirement_id
        return result

    def get(self, question_id: str) -> dict[str, Any]:
        """按稳定 question_id 回找完整题目。

        参数:
            question_id: 题目稳定 ID。
        返回:
            题目 dict；不存在时 {missing: "question_id", question_id: str}。
        """
        found = self._store.get_question(question_id)
        if found is None:
            return {"missing": "question_id", "question_id": question_id}
        return found
