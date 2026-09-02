"""打分角色：校验并保存评分结果，不隐式出题，也不自行对照标准答案改分。"""

from __future__ import annotations

import math
from typing import Any

from memory import MemoryStore


def _text(value: Any) -> str:
    """只接受去掉首尾空白后的非空字符串。数字等类型不能当用户答案。"""
    return value.strip() if isinstance(value, str) else ""


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


def _optional_text(value: Any) -> tuple[bool, str | None]:
    """失分原因和薄弱点必须是存储支持的文本，不能是列表等结构。

    参数:
        value: Agent 传入的字段；缺省为 None。
    返回:
        (是否合法, 写入用文本)。空白串落成 None，与可空 TEXT 一致。
    """
    if value is None:
        return True, None
    if not isinstance(value, str):
        return False, None
    return True, value.strip() or None


class ScoringRole:
    """校验通用 Agent 给出的评分结果并写入记忆。缺少题目时只报告稳定 ID。"""

    def __init__(self, store: MemoryStore) -> None:
        """绑定共享记忆。不隐式触发出题或知识搜索。

        参数:
            store: 已初始化的 MemoryStore。
        返回:
            None。
        """
        self._store = store

    def get(self, question_id: str) -> dict[str, Any]:
        """按稳定 question_id 读取题目、标准答案和历史评分。

        新会话靠这一条接缝恢复作答记录与薄弱点，不必再扫其他表。

        参数:
            question_id: 题目稳定 ID。
        返回:
            题目 dict，另含 scores 列表；不存在时
            {missing: "question_id", question_id: str}。
            scores 每项含 score_id, question_id, user_answer, score, max_score,
            loss_reason, weak_points，顺序为写入顺序。
        """
        found = self._store.get_question(question_id)
        if found is None:
            return {"missing": "question_id", "question_id": question_id}
        return {**found, "scores": self._store.list_answer_scores(question_id)}

    def score(
        self,
        question_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """校验结构化评分结果后追加保存。同一题不覆盖历史作答。

        角色不对照标准答案改分；分数必须是有限数字，且 0 <= score <= max_score
        且 max_score > 0，避免把 Agent 的判断写进半合法记录。

        参数:
            question_id: 已存在的题目稳定 ID。
            result: 评分结果。至少含 user_answer、score、max_score。
                loss_reason、weak_points 为可空文本，不能是列表或其它结构。
        返回:
            缺失题目: {missing: "question_id", question_id: str}
            成功: {score_id, question_id, user_answer, score, max_score,
                loss_reason, weak_points}
        """
        if self._store.get_question(question_id) is None:
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

        return self._store.save_answer_score(
            question_id=question_id,
            user_answer=user_answer,
            score=score,
            max_score=max_score,
            loss_reason=loss_reason,
            weak_points=weak_points,
        )
