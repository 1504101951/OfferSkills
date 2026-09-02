"""出题角色：校验题目草稿并保存，按 question_id 回找。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import MemoryStore
from question import QuestionRole


class QuestionRoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore(":memory:")
        self.role = QuestionRole(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _seed_sql_chunks(self) -> dict[str, str]:
        """写入一条岗位要求和两片资料，供出题。返回岗位要求 dict。"""
        req = self.store.save_requirement(name="SQL", requirement_id="req-sql")
        self.store.save_knowledge_chunk(
            chunk_id="chunk-join",
            requirement_id=req["requirement_id"],
            source_url="https://example.com/sql-join",
            title="INNER JOIN",
            content="INNER JOIN 只返回两表匹配行。",
            evidence="INNER JOIN 只返回两表匹配行。",
        )
        self.store.save_knowledge_chunk(
            chunk_id="chunk-group",
            requirement_id=req["requirement_id"],
            source_url="https://example.com/sql-group",
            title="GROUP BY",
            content="GROUP BY 按键聚合行。",
            evidence="GROUP BY 按键聚合行。",
        )
        return req

    def _sql_drafts(self) -> list[dict[str, str]]:
        """两份合法草稿：答案与解析不同，且不是切片正文副本。"""
        return [
            {
                "chunk_id": "chunk-join",
                "prompt": "INNER JOIN 返回哪些行？",
                "standard_answer": "只返回两表键匹配的行。",
                "explanation": "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。",
            },
            {
                "chunk_id": "chunk-group",
                "prompt": "GROUP BY 做什么？",
                "standard_answer": "按键把行聚合成组。",
                "explanation": "聚合函数作用在每一组，而不是整张表。",
            },
        ]

    def test_generate_by_requirement_id_saves_answer_and_explanation(self) -> None:
        """按 requirement_id 保存草稿后，库中题目必须带要求 ID、标准答案和解析。

        边界：答案与解析不同，且不得被替换成知识切片正文；保存结果不含 difficulty。
        """
        req = self._seed_sql_chunks()
        drafts = self._sql_drafts()
        result = self.role.generate(req["requirement_id"], drafts=drafts)

        questions = result["questions"]
        self.assertEqual(result["requirement_id"], "req-sql")
        self.assertEqual(len(questions), 2)
        by_prompt = {row["prompt"]: row for row in questions}
        join = by_prompt["INNER JOIN 返回哪些行？"]
        self.assertEqual(join["requirement_id"], "req-sql")
        self.assertEqual(join["standard_answer"], "只返回两表键匹配的行。")
        self.assertEqual(
            join["explanation"],
            "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。",
        )
        self.assertNotEqual(join["standard_answer"], join["explanation"])
        self.assertNotEqual(join["standard_answer"], "INNER JOIN 只返回两表匹配行。")
        self.assertNotEqual(join["explanation"], "INNER JOIN 只返回两表匹配行。")
        self.assertNotIn("difficulty", join)
        self.assertEqual(self.store.list_questions("req-sql"), questions)

    def test_get_returns_full_question_by_question_id(self) -> None:
        """保存后必须能按 question_id 取回题面、答案、解析和要求 ID。

        边界：用生成结果里的稳定 ID 回找，而不是再扫 requirement_id 列表。
        """
        self._seed_sql_chunks()
        generated = self.role.generate("req-sql", drafts=self._sql_drafts())
        question_id = generated["questions"][0]["question_id"]

        found = self.role.get(question_id)
        self.assertEqual(found, generated["questions"][0])
        self.assertEqual(found["question_id"], question_id)
        self.assertEqual(found["requirement_id"], "req-sql")
        self.assertTrue(found["prompt"])
        self.assertTrue(found["standard_answer"])
        self.assertTrue(found["explanation"])
        self.assertNotEqual(found["standard_answer"], found["explanation"])

    def test_generate_from_existing_chunk_ids(self) -> None:
        """已有知识切片可直接带草稿出题，不必再传 requirement_id。

        边界：只给其中一片的草稿，另一片不得被写成题目。
        """
        self._seed_sql_chunks()
        result = self.role.generate(drafts=[self._sql_drafts()[1]])

        questions = result["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["standard_answer"], "按键把行聚合成组。")
        self.assertNotEqual(
            questions[0]["standard_answer"], questions[0]["explanation"]
        )
        self.assertEqual(questions[0]["requirement_id"], "req-sql")
        self.assertEqual(len(self.store.list_questions("req-sql")), 1)

    def test_repeat_generate_overwrites_same_questions(self) -> None:
        """同一批切片再次出题必须覆盖原题，不能追加重复练习项。

        边界：两次 generate 同一草稿；库中题目数仍等于草稿数。
        """
        self._seed_sql_chunks()
        drafts = self._sql_drafts()
        first = self.role.generate("req-sql", drafts=drafts)
        second = self.role.generate("req-sql", drafts=drafts)
        self.assertEqual(len(self.store.list_questions("req-sql")), 2)
        self.assertEqual(
            {row["question_id"] for row in second["questions"]},
            {row["question_id"] for row in first["questions"]},
        )

    def test_missing_or_invalid_draft_writes_nothing(self) -> None:
        """缺草稿、缺字段或答案与解析相同必须整批失败，已合法的草稿也不落库。

        边界：切片已在；无草稿；两份草稿中第二份缺 explanation 或答案等于解析。
        """
        self._seed_sql_chunks()
        valid, other = self._sql_drafts()

        with self.assertRaises(ValueError):
            self.role.generate("req-sql")
        self.assertEqual(self.store.list_questions("req-sql"), [])

        incomplete = {**other, "explanation": ""}
        with self.assertRaises(ValueError):
            self.role.generate("req-sql", drafts=[valid, incomplete])
        self.assertEqual(self.store.list_questions("req-sql"), [])

        identical = {
            **other,
            "standard_answer": "同一段文字。",
            "explanation": "同一段文字。",
        }
        with self.assertRaises(ValueError):
            self.role.generate(drafts=[valid, identical])
        self.assertEqual(self.store.list_questions("req-sql"), [])

    def test_missing_requirement_reports_id_without_saving(self) -> None:
        """岗位要求不存在时只报告缺失 ID，不写题目，也不去搜资料。

        边界：requirement_id 未入库；出题后知识切片和题目都应仍为空。
        """
        result = self.role.generate("req-missing")
        self.assertEqual(
            result,
            {"missing": "requirement_id", "requirement_id": "req-missing"},
        )
        self.assertEqual(self.store.list_knowledge_chunks("req-missing"), [])
        self.assertEqual(self.store.list_questions("req-missing"), [])

    def test_missing_chunks_for_requirement_reports_id_without_saving(self) -> None:
        """要求在、资料不在时报告缺失，不隐式触发知识搜索。

        边界：已写入 requirement_id，未写入任何 knowledge_chunks。
        """
        self.store.save_requirement(name="HTTP", requirement_id="req-http")
        result = self.role.generate("req-http")
        self.assertEqual(
            result,
            {"missing": "chunk_id", "requirement_id": "req-http"},
        )
        self.assertEqual(self.store.list_knowledge_chunks("req-http"), [])
        self.assertEqual(self.store.list_questions("req-http"), [])

    def test_missing_chunk_id_reports_without_saving_found_chunks(self) -> None:
        """按草稿出题时，缺任一 chunk_id 则整批失败，已找到的切片也不落题。

        边界：一份有效草稿与一个不存在的 chunk_id 混传。
        """
        self._seed_sql_chunks()
        valid = self._sql_drafts()[0]
        absent = {
            "chunk_id": "chunk-absent",
            "prompt": "不存在的切片能出题吗？",
            "standard_answer": "不能。",
            "explanation": "校验阶段就会失败，不会写入。",
        }
        result = self.role.generate(drafts=[valid, absent])
        self.assertEqual(
            result,
            {"missing": "chunk_id", "chunk_ids": ["chunk-absent"]},
        )
        self.assertEqual(self.store.list_questions("req-sql"), [])

    def test_get_missing_question_id_reports_without_writing(self) -> None:
        """题目不存在时只报告缺失 ID，不隐式出题或写入。

        边界：question_id 未入库；get 后库中仍无该题。
        """
        result = self.role.get("q-missing")
        self.assertEqual(result, {"missing": "question_id", "question_id": "q-missing"})
        self.assertIsNone(self.store.get_question("q-missing"))

    def test_new_session_gets_question_by_id(self) -> None:
        """关闭连接后，新会话必须能按 question_id 读回完整题目。

        边界：两个 MemoryStore 打开同一文件；第二次只调用 get。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first_store = MemoryStore(path)
            req = first_store.save_requirement(name="Python", requirement_id="req-py")
            first_store.save_knowledge_chunk(
                chunk_id="chunk-list",
                requirement_id=req["requirement_id"],
                source_url="https://example.com/listcomp",
                title="列表推导",
                content="列表推导比循环更短。",
                evidence="列表推导比循环更短。",
            )
            saved = QuestionRole(first_store).generate(
                "req-py",
                drafts=[
                    {
                        "chunk_id": "chunk-list",
                        "prompt": "列表推导比循环短在哪里？",
                        "standard_answer": "同一表达式里完成遍历和收集。",
                        "explanation": "循环需要单独的追加语句，推导式把结果写在表达式中。",
                    }
                ],
            )
            question_id = saved["questions"][0]["question_id"]
            first_store.close()

            second_store = MemoryStore(path)
            try:
                loaded = QuestionRole(second_store).get(question_id)
                self.assertEqual(loaded, saved["questions"][0])
                self.assertEqual(
                    loaded["standard_answer"], "同一表达式里完成遍历和收集。"
                )
                self.assertNotEqual(loaded["standard_answer"], loaded["explanation"])
                self.assertNotEqual(loaded["standard_answer"], "列表推导比循环更短。")
            finally:
                second_store.close()


if __name__ == "__main__":
    unittest.main()
