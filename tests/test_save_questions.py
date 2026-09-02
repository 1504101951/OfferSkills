"""save_questions：校验题目草稿并保存，按 question_id 回找。"""

from __future__ import annotations

from test_memory_tool import JsonToolCase


class SaveQuestionsTest(JsonToolCase):
    def _seed_sql_chunk(self) -> dict[str, str]:
        """写入一条岗位要求和两片资料，供出题。返回 requirement_id 与 chunk_id。"""
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
                    },
                    {
                        "chunk_id": "chunk-group",
                        "requirement_id": sql_id,
                        "title": "GROUP BY",
                        "content": "GROUP BY 按键聚合行。",
                        "source_url": "https://example.com/sql-group",
                        "evidence": "GROUP BY 按键聚合行。",
                    },
                ],
            }
        )
        self.assertEqual(chunks[0], 0)
        return {"requirement_id": sql_id}

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

    def test_save_questions_persists_answer_and_explanation(self) -> None:
        """保存草稿后，库中题目必须带要求 ID、标准答案和解析。

        边界：答案与解析不同，且不得被替换成知识切片正文；保存结果不含 difficulty。
        """
        seeded = self._seed_sql_chunk()
        code, payload, _stderr = self._call(
            {"action": "save_questions", "drafts": self._sql_drafts()}
        )

        self.assertEqual(code, 0)
        questions = payload["result"]["questions"]
        self.assertEqual(len(questions), 2)
        by_prompt = {row["prompt"]: row for row in questions}
        join = by_prompt["INNER JOIN 返回哪些行？"]
        self.assertEqual(join["requirement_id"], seeded["requirement_id"])
        self.assertEqual(join["standard_answer"], "只返回两表键匹配的行。")
        self.assertEqual(
            join["explanation"],
            "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。",
        )
        self.assertNotEqual(join["standard_answer"], join["explanation"])
        self.assertNotEqual(join["standard_answer"], "INNER JOIN 只返回两表匹配行。")
        self.assertNotIn("difficulty", join)
        listed = self._call(
            {"action": "list_questions", "requirement_id": seeded["requirement_id"]}
        )
        self.assertEqual(listed[1]["result"]["questions"], questions)

    def test_get_returns_full_question_by_question_id(self) -> None:
        """保存后必须能按 question_id 取回题面、答案、解析和要求 ID。

        边界：用生成结果里的稳定 ID 回找，而不是再扫 requirement_id 列表。
        """
        self._seed_sql_chunk()
        generated = self._call(
            {"action": "save_questions", "drafts": self._sql_drafts()}
        )
        question_id = generated[1]["result"]["questions"][0]["question_id"]

        found = self._call({"action": "get_question", "question_id": question_id})
        self.assertEqual(found[1]["result"], generated[1]["result"]["questions"][0])
        self.assertTrue(found[1]["result"]["prompt"])
        self.assertNotEqual(
            found[1]["result"]["standard_answer"],
            found[1]["result"]["explanation"],
        )

    def test_save_from_existing_chunk_ids(self) -> None:
        """已有知识切片可直接带草稿出题；只给其中一片时另一片不得被写成题目。

        边界：只保存 GROUP BY 草稿。
        """
        seeded = self._seed_sql_chunk()
        result = self._call(
            {"action": "save_questions", "drafts": [self._sql_drafts()[1]]}
        )

        questions = result[1]["result"]["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["standard_answer"], "按键把行聚合成组。")
        self.assertEqual(questions[0]["requirement_id"], seeded["requirement_id"])
        listed = self._call(
            {"action": "list_questions", "requirement_id": seeded["requirement_id"]}
        )
        self.assertEqual(len(listed[1]["result"]["questions"]), 1)

    def test_repeat_save_overwrites_same_questions(self) -> None:
        """同一批切片再次出题必须覆盖原题，不能追加重复练习项。

        边界：两次 save_questions 同一草稿；库中题目数仍等于草稿数。
        """
        self._seed_sql_chunk()
        drafts = self._sql_drafts()
        first = self._call({"action": "save_questions", "drafts": drafts})
        second = self._call({"action": "save_questions", "drafts": drafts})
        self.assertEqual(self._table_count("questions"), 2)
        self.assertEqual(
            {row["question_id"] for row in second[1]["result"]["questions"]},
            {row["question_id"] for row in first[1]["result"]["questions"]},
        )

    def test_missing_or_invalid_draft_writes_nothing(self) -> None:
        """缺草稿、缺字段或答案与解析相同必须整批失败，已合法的草稿也不落库。

        边界：切片已在；无草稿；两份草稿中第二份缺 explanation 或答案等于解析。
        """
        self._seed_sql_chunk()
        valid, other = self._sql_drafts()

        code, payload, _stderr = self._call({"action": "save_questions"})
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"], "invalid_input")
        self.assertEqual(self._table_count("questions"), 0)

        incomplete = {**other, "explanation": ""}
        code, _payload, _stderr = self._call(
            {"action": "save_questions", "drafts": [valid, incomplete]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("questions"), 0)

        identical = {
            **other,
            "standard_answer": "同一段文字。",
            "explanation": "同一段文字。",
        }
        code, _payload, _stderr = self._call(
            {"action": "save_questions", "drafts": [valid, identical]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("questions"), 0)

    def test_missing_chunk_id_reports_without_saving_found_chunks(self) -> None:
        """按草稿出题时，缺任一 chunk_id 则整批失败，已找到的切片也不落题。

        边界：一份有效草稿与一个不存在的 chunk_id 混传。
        """
        self._seed_sql_chunk()
        valid = self._sql_drafts()[0]
        absent = {
            "chunk_id": "chunk-absent",
            "prompt": "不存在的切片能出题吗？",
            "standard_answer": "不能。",
            "explanation": "校验阶段就会失败，不会写入。",
        }
        code, payload, _stderr = self._call(
            {"action": "save_questions", "drafts": [valid, absent]}
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            payload["result"],
            {"missing": "chunk_id", "chunk_ids": ["chunk-absent"]},
        )
        self.assertEqual(self._table_count("questions"), 0)

    def test_new_process_gets_question_by_id(self) -> None:
        """下一进程必须能按 question_id 读回完整题目。

        边界：两次真实 subprocess；第二次只调用 get_question。
        """
        self._seed_sql_chunk()
        saved = self._call(
            {"action": "save_questions", "drafts": [self._sql_drafts()[0]]}
        )
        question_id = saved[1]["result"]["questions"][0]["question_id"]
        loaded = self._call({"action": "get_question", "question_id": question_id})
        self.assertEqual(loaded[1]["result"], saved[1]["result"]["questions"][0])
        self.assertNotEqual(
            loaded[1]["result"]["standard_answer"],
            "INNER JOIN 只返回两表匹配行。",
        )


if __name__ == "__main__":
    unittest.main()
