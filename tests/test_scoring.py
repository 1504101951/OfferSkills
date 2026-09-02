"""打分角色：校验评分结果并保存，按 question_id 回找历史评分与薄弱点。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import MemoryStore
from scoring import ScoringRole


class ScoringRoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore(":memory:")
        self.role = ScoringRole(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _seed_sql_question(self) -> dict[str, str]:
        """写入一道带标准答案的题，供打分。返回题目 dict。"""
        req = self.store.save_requirement(name="SQL", requirement_id="req-sql")
        return self.store.save_question(
            question_id="q-sql-1",
            requirement_id=req["requirement_id"],
            prompt="INNER JOIN 的结果包含什么？",
            standard_answer="两表键匹配的行。",
            explanation="不匹配的行会被丢弃。",
        )

    def _join_result(self) -> dict[str, object]:
        """一份合法评分：错误作答由 Agent 给分，角色不得自行改成满分或零分。"""
        return {
            "user_answer": "返回笛卡尔积。",
            "score": 2,
            "max_score": 10,
            "loss_reason": "把 JOIN 理解成了叉乘。",
            "weak_points": "JOIN 与笛卡尔积的区别",
        }

    def test_score_saves_user_answer_and_weak_points(self) -> None:
        """校验通过后必须保存用户答案、分数、失分原因和薄弱点。

        边界：作答与标准答案不同；角色按 Agent 给出的 2/10 落库，不改分。
        """
        question = self._seed_sql_question()
        saved = self.role.score(question["question_id"], self._join_result())

        self.assertEqual(saved["question_id"], "q-sql-1")
        self.assertEqual(saved["user_answer"], "返回笛卡尔积。")
        self.assertEqual(saved["score"], 2)
        self.assertEqual(saved["max_score"], 10)
        self.assertEqual(saved["loss_reason"], "把 JOIN 理解成了叉乘。")
        self.assertEqual(saved["weak_points"], "JOIN 与笛卡尔积的区别")
        self.assertNotEqual(saved["user_answer"], question["standard_answer"])
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [saved])

    def test_get_returns_question_and_score_history(self) -> None:
        """get 必须带回题面、标准答案和已保存评分，供对照与查薄弱点。

        边界：先 score 再 get；历史按写入顺序，且含 weak_points。
        """
        self._seed_sql_question()
        saved = self.role.score("q-sql-1", self._join_result())

        loaded = self.role.get("q-sql-1")
        self.assertEqual(loaded["question_id"], "q-sql-1")
        self.assertEqual(loaded["prompt"], "INNER JOIN 的结果包含什么？")
        self.assertEqual(loaded["standard_answer"], "两表键匹配的行。")
        self.assertEqual(loaded["scores"], [saved])
        self.assertEqual(loaded["scores"][0]["weak_points"], "JOIN 与笛卡尔积的区别")

    def test_same_question_keeps_multiple_scores(self) -> None:
        """同一 question_id 再次作答必须追加，不得覆盖前一次。

        边界：先 0 分再 9 分；两次 user_answer 不同，list 长度为 2。
        """
        self._seed_sql_question()
        first = self.role.score(
            "q-sql-1",
            {
                "user_answer": "不知道",
                "score": 0,
                "max_score": 10,
                "loss_reason": "未作答",
                "weak_points": "JOIN 语义",
            },
        )
        second = self.role.score(
            "q-sql-1",
            {
                "user_answer": "只返回两表键匹配的行。",
                "score": 9,
                "max_score": 10,
                "loss_reason": "未提不匹配行被丢弃",
                "weak_points": "JOIN 丢弃规则",
            },
        )

        scores = self.store.list_answer_scores("q-sql-1")
        self.assertEqual(len(scores), 2)
        self.assertEqual(
            {row["score_id"] for row in scores},
            {first["score_id"], second["score_id"]},
        )
        self.assertEqual([row["score"] for row in scores], [0, 9])
        self.assertEqual(self.role.get("q-sql-1")["scores"], scores)

    def test_missing_question_id_reports_without_writing(self) -> None:
        """题目不存在时只报告缺失 ID，不写入评分，也不隐式出题。

        边界：question_id 未入库；传入完整评分结果仍不得落库。
        """
        result = self.role.score("q-missing", self._join_result())
        self.assertEqual(
            result,
            {"missing": "question_id", "question_id": "q-missing"},
        )
        self.assertIsNone(self.store.get_question("q-missing"))
        self.assertEqual(self.store.list_answer_scores("q-missing"), [])

    def test_get_missing_question_id_reports_without_writing(self) -> None:
        """get 遇到不存在的题目只报告缺失 ID，不写出评分。

        边界：question_id 未入库；get 后库中仍无该题和评分。
        """
        result = self.role.get("q-missing")
        self.assertEqual(result, {"missing": "question_id", "question_id": "q-missing"})
        self.assertIsNone(self.store.get_question("q-missing"))
        self.assertEqual(self.store.list_answer_scores("q-missing"), [])

    def test_invalid_score_bounds_write_nothing(self) -> None:
        """分数越界或满分无效时必须失败，已合法字段也不落库。

        边界：题目已在；score < 0；score > max_score；max_score = 0。
        """
        self._seed_sql_question()
        payload = {
            "user_answer": "两表键匹配的行。",
            "loss_reason": "无",
            "weak_points": "无",
        }

        with self.assertRaises(ValueError):
            self.role.score("q-sql-1", {**payload, "score": -1, "max_score": 10})
        with self.assertRaises(ValueError):
            self.role.score("q-sql-1", {**payload, "score": 11, "max_score": 10})
        with self.assertRaises(ValueError):
            self.role.score("q-sql-1", {**payload, "score": 0, "max_score": 0})
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [])

    def test_non_finite_score_writes_nothing(self) -> None:
        """非有限分数或无法转成有限 float 的整数必须按契约 ValueError 失败。

        边界：题目已在；score 为正 Infinity；max_score 为正 Infinity；
        超大整数触发 float OverflowError。这三类都不能落库。
        """
        self._seed_sql_question()
        payload = {
            "user_answer": "两表键匹配的行。",
            "loss_reason": "无",
            "weak_points": "无",
        }

        with self.assertRaises(ValueError):
            self.role.score(
                "q-sql-1", {**payload, "score": float("inf"), "max_score": 10}
            )
        with self.assertRaises(ValueError):
            self.role.score(
                "q-sql-1", {**payload, "score": 1, "max_score": float("inf")}
            )
        with self.assertRaises(ValueError):
            self.role.score(
                "q-sql-1", {**payload, "score": 10**400, "max_score": 10}
            )
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [])

    def test_invalid_result_fields_write_nothing(self) -> None:
        """缺用户答案、或失分原因/薄弱点不是文本时整次失败。

        边界：题目已在；无 result；user_answer 为空；weak_points 为列表。
        """
        self._seed_sql_question()
        valid = self._join_result()

        with self.assertRaises(ValueError):
            self.role.score("q-sql-1")
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [])

        with self.assertRaises(ValueError):
            self.role.score("q-sql-1", {**valid, "user_answer": ""})
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [])

        with self.assertRaises(ValueError):
            self.role.score("q-sql-1", {**valid, "weak_points": ["JOIN", "笛卡尔积"]})
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [])

    def test_full_marks_allow_empty_loss_fields(self) -> None:
        """满分且 0 <= score <= max_score 时，可空文本字段按存储约定省略。

        边界：score == max_score；不传 loss_reason 与 weak_points。
        """
        self._seed_sql_question()
        saved = self.role.score(
            "q-sql-1",
            {
                "user_answer": "两表键匹配的行。",
                "score": 10,
                "max_score": 10,
            },
        )

        self.assertEqual(saved["score"], 10)
        self.assertEqual(saved["max_score"], 10)
        self.assertIsNone(saved["loss_reason"])
        self.assertIsNone(saved["weak_points"])
        self.assertEqual(self.store.list_answer_scores("q-sql-1"), [saved])

    def test_new_session_gets_scores_and_weak_points(self) -> None:
        """关闭连接后，新会话必须能按 question_id 读回历史评分与薄弱点。

        边界：两个 MemoryStore 打开同一文件；第二次只调用 get。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first_store = MemoryStore(path)
            req = first_store.save_requirement(name="HTTP", requirement_id="req-http")
            first_store.save_question(
                question_id="q-http-1",
                requirement_id=req["requirement_id"],
                prompt="GET 与 POST 的区别？",
                standard_answer="GET 用于获取，POST 用于提交。",
                explanation="GET 通常幂等，POST 用于产生副作用的提交。",
            )
            saved = ScoringRole(first_store).score(
                "q-http-1",
                {
                    "user_answer": "GET 获取资源，POST 提交数据。",
                    "score": 9,
                    "max_score": 10,
                    "loss_reason": "未提幂等性",
                    "weak_points": "幂等",
                },
            )
            first_store.close()

            second_store = MemoryStore(path)
            try:
                loaded = ScoringRole(second_store).get("q-http-1")
                self.assertEqual(loaded["standard_answer"], "GET 用于获取，POST 用于提交。")
                self.assertEqual(len(loaded["scores"]), 1)
                self.assertEqual(loaded["scores"][0], saved)
                self.assertEqual(loaded["scores"][0]["weak_points"], "幂等")
                self.assertEqual(loaded["scores"][0]["loss_reason"], "未提幂等性")
            finally:
                second_store.close()


if __name__ == "__main__":
    unittest.main()
