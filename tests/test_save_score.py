"""save_score：校验评分结果并保存，按 score_id 与 question_id 回找。"""

from __future__ import annotations

from test_memory_tool import JsonToolCase


class SaveScoreTest(JsonToolCase):
    def _seed_question(self) -> str:
        """写入一道带标准答案的题，供打分。返回 question_id。"""
        saved = self._call({"action": "save_jobs", "jobs": [self._backend_job()]})
        sql_id = next(
            row["requirement_id"]
            for row in saved[1]["result"]["jobs"][0]["requirements"]
            if row["name"] == "SQL"
        )
        chunks = self._call(
            {
                "action": "save_chunks",
                "chunks": [
                    {
                        "chunk_id": "chunk-join",
                        "requirement_id": sql_id,
                        "title": "INNER JOIN",
                        "content": "INNER JOIN 只返回两表匹配行。",
                        "source_url": "https://example.com/sql-join",
                        "evidence": "INNER JOIN 只返回两表匹配行。",
                    }
                ],
            }
        )
        self.assertEqual(chunks[0], 0)
        questions = self._call(
            {
                "action": "save_questions",
                "drafts": [
                    {
                        "chunk_id": "chunk-join",
                        "prompt": "INNER JOIN 的结果包含什么？",
                        "standard_answer": "两表键匹配的行。",
                        "explanation": "不匹配的行会被丢弃。",
                    }
                ],
            }
        )
        return questions[1]["result"]["questions"][0]["question_id"]

    def _join_result(self) -> dict[str, object]:
        """一份合法评分：错误作答由 Agent 给分，工具不得自行改成满分或零分。"""
        return {
            "user_answer": "返回笛卡尔积。",
            "score": 2,
            "max_score": 10,
            "loss_reason": "把 JOIN 理解成了叉乘。",
            "weak_points": "JOIN 与笛卡尔积的区别",
        }

    def test_save_score_persists_user_answer_and_weak_points(self) -> None:
        """校验通过后必须保存用户答案、分数、失分原因和薄弱点。

        边界：作答与标准答案不同；工具按 Agent 给出的 2/10 落库，不改分。
        """
        question_id = self._seed_question()
        code, payload, _stderr = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": self._join_result(),
            }
        )

        self.assertEqual(code, 0)
        saved = payload["result"]
        self.assertEqual(saved["question_id"], question_id)
        self.assertEqual(saved["user_answer"], "返回笛卡尔积。")
        self.assertEqual(saved["score"], 2)
        self.assertEqual(saved["max_score"], 10)
        self.assertEqual(saved["loss_reason"], "把 JOIN 理解成了叉乘。")
        self.assertEqual(saved["weak_points"], "JOIN 与笛卡尔积的区别")
        listed = self._call({"action": "list_scores", "question_id": question_id})
        self.assertEqual(listed[1]["result"]["scores"], [saved])

    def test_same_question_keeps_multiple_scores(self) -> None:
        """同一 question_id 再次作答必须追加，不得覆盖前一次。

        边界：先 0 分再 9 分；两次 user_answer 不同，list 长度为 2。
        """
        question_id = self._seed_question()
        first = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {
                    "user_answer": "不知道",
                    "score": 0,
                    "max_score": 10,
                    "loss_reason": "未作答",
                    "weak_points": "JOIN 语义",
                },
            }
        )
        second = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {
                    "user_answer": "只返回两表键匹配的行。",
                    "score": 9,
                    "max_score": 10,
                    "loss_reason": "未提不匹配行被丢弃",
                    "weak_points": "JOIN 丢弃规则",
                },
            }
        )

        listed = self._call({"action": "list_scores", "question_id": question_id})
        scores = listed[1]["result"]["scores"]
        self.assertEqual(len(scores), 2)
        self.assertEqual(
            {row["score_id"] for row in scores},
            {first[1]["result"]["score_id"], second[1]["result"]["score_id"]},
        )
        self.assertEqual([row["score"] for row in scores], [0, 9])

    def test_missing_question_id_reports_without_writing(self) -> None:
        """题目不存在时只报告缺失 ID，不写入评分。

        边界：question_id 未入库；传入完整评分结果仍不得落库。
        """
        code, payload, _stderr = self._call(
            {
                "action": "save_score",
                "question_id": "q-missing",
                "result": self._join_result(),
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            payload["result"],
            {"missing": "question_id", "question_id": "q-missing"},
        )
        listed = self._call({"action": "list_scores", "question_id": "q-missing"})
        self.assertEqual(listed[1]["result"]["scores"], [])

    def test_invalid_score_bounds_write_nothing(self) -> None:
        """分数越界或满分无效时必须失败，已合法字段也不落库。

        边界：题目已在；score < 0；score > max_score；max_score = 0。
        """
        question_id = self._seed_question()
        payload = {
            "user_answer": "两表键匹配的行。",
            "loss_reason": "无",
            "weak_points": "无",
        }
        for result in (
            {**payload, "score": -1, "max_score": 10},
            {**payload, "score": 11, "max_score": 10},
            {**payload, "score": 0, "max_score": 0},
        ):
            code, body, _stderr = self._call(
                {
                    "action": "save_score",
                    "question_id": question_id,
                    "result": result,
                }
            )
            self.assertNotEqual(code, 0)
            self.assertEqual(body["error"], "invalid_input")
        self.assertEqual(self._table_count("answer_scores"), 0)

    def test_non_finite_score_writes_nothing(self) -> None:
        """非有限分数或无法转成有限 float 的整数必须按契约失败。

        边界：题目已在；score 为正 Infinity；max_score 为正 Infinity；
        超大整数触发 float OverflowError。这三类都不能落库。
        """
        question_id = self._seed_question()
        payload = {
            "user_answer": "两表键匹配的行。",
            "loss_reason": "无",
            "weak_points": "无",
        }
        for result in (
            {**payload, "score": float("inf"), "max_score": 10},
            {**payload, "score": 1, "max_score": float("inf")},
            {**payload, "score": 10**400, "max_score": 10},
        ):
            code, body, _stderr = self._call(
                {
                    "action": "save_score",
                    "question_id": question_id,
                    "result": result,
                }
            )
            self.assertNotEqual(code, 0)
            self.assertEqual(body["error"], "invalid_input")
        self.assertEqual(self._table_count("answer_scores"), 0)

    def test_invalid_result_fields_write_nothing(self) -> None:
        """缺用户答案、或失分原因/薄弱点不是文本时整次失败。

        边界：题目已在；无 result；user_answer 为空；weak_points 为列表。
        """
        question_id = self._seed_question()
        valid = self._join_result()

        code, _payload, _stderr = self._call(
            {"action": "save_score", "question_id": question_id}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("answer_scores"), 0)

        code, _payload, _stderr = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {**valid, "user_answer": ""},
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("answer_scores"), 0)

        code, _payload, _stderr = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {**valid, "weak_points": ["JOIN", "笛卡尔积"]},
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("answer_scores"), 0)

    def test_full_marks_allow_empty_loss_fields(self) -> None:
        """满分且 0 <= score <= max_score 时，可空文本字段按存储约定省略。

        边界：score == max_score；不传 loss_reason 与 weak_points。
        """
        question_id = self._seed_question()
        code, payload, _stderr = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {
                    "user_answer": "两表键匹配的行。",
                    "score": 10,
                    "max_score": 10,
                },
            }
        )

        self.assertEqual(code, 0)
        saved = payload["result"]
        self.assertEqual(saved["score"], 10)
        self.assertEqual(saved["max_score"], 10)
        self.assertIsNone(saved["loss_reason"])
        self.assertIsNone(saved["weak_points"])
        listed = self._call({"action": "list_scores", "question_id": question_id})
        self.assertEqual(listed[1]["result"]["scores"], [saved])

    def test_new_process_gets_scores_and_weak_points(self) -> None:
        """下一进程必须能按 score_id 与 question_id 读回历史评分与薄弱点。

        边界：两次真实 subprocess；第二次只调用 get_score 与 list_scores。
        """
        question_id = self._seed_question()
        saved = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {
                    "user_answer": "GET 获取资源，POST 提交数据。",
                    "score": 9,
                    "max_score": 10,
                    "loss_reason": "未提幂等性",
                    "weak_points": "幂等",
                },
            }
        )
        score_id = saved[1]["result"]["score_id"]
        loaded = self._call({"action": "get_score", "score_id": score_id})
        self.assertEqual(loaded[1]["result"], saved[1]["result"])
        listed = self._call({"action": "list_scores", "question_id": question_id})
        self.assertEqual(listed[1]["result"]["scores"][0]["weak_points"], "幂等")


if __name__ == "__main__":
    unittest.main()
