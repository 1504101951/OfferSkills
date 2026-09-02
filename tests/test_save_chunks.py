"""save_chunks：接收 Agent 切片、校验必填字段并原子入库。"""

from __future__ import annotations

from test_memory_tool import JsonToolCase


class SaveChunksTest(JsonToolCase):
    def _requirement_id(self) -> str:
        """先写入一条岗位要求，供切片归属。"""
        saved = self._call({"action": "save_jobs", "jobs": [self._backend_job()]})
        return next(
            row["requirement_id"]
            for row in saved[1]["result"]["jobs"][0]["requirements"]
            if row["name"] == "Python"
        )

    def _chunk(self, requirement_id: str, **overrides: object) -> dict[str, object]:
        """一份合法切片：字段已由 Agent 切好，不依赖空行分段。"""
        chunk: dict[str, object] = {
            "requirement_id": requirement_id,
            "title": "INNER JOIN",
            "content": "INNER JOIN 只返回两表键匹配的行。",
            "source_url": "https://example.com/sql-join",
            "evidence": "INNER JOIN produces only matching rows.",
        }
        chunk.update(overrides)
        return chunk

    def test_save_chunks_persists_agent_chunks_with_source_and_evidence(self) -> None:
        """首次写入必须保存 Agent 给出的语义切片，含来源与证据，且不按空行再切。

        边界：一篇含空行的 content 仍是一条切片；title/evidence 不得回落到要求名。
        """
        req_id = self._requirement_id()
        code, payload, _stderr = self._call(
            {
                "action": "save_chunks",
                "chunks": [
                    self._chunk(
                        req_id,
                        title="列表与生成器",
                        content="列表推导比循环更短。\n\n生成器按需产出值。",
                        source_url="https://docs.python.org/3/tutorial/datastructures.html",
                        evidence="List comprehensions provide a concise way to create lists.",
                    )
                ],
            }
        )

        self.assertEqual(code, 0)
        chunks = payload["result"]["chunks"]
        self.assertEqual(len(chunks), 1)
        row = chunks[0]
        self.assertEqual(row["requirement_id"], req_id)
        self.assertEqual(row["title"], "列表与生成器")
        self.assertEqual(
            row["content"],
            "列表推导比循环更短。\n\n生成器按需产出值。",
        )
        self.assertEqual(
            row["source_url"],
            "https://docs.python.org/3/tutorial/datastructures.html",
        )
        listed = self._call({"action": "list_chunks", "requirement_id": req_id})
        self.assertEqual(listed[1]["result"]["chunks"], chunks)

    def test_repeat_save_chunks_appends_instead_of_reusing(self) -> None:
        """save_chunks 是写入不是搜索；已有切片时再次保存必须追加。

        边界：第二次传入不同 source_url；库中应有两条。复用由 Agent 先 list_chunks。
        """
        req_id = self._requirement_id()
        first = self._call(
            {"action": "save_chunks", "chunks": [self._chunk(req_id)]}
        )
        second = self._call(
            {
                "action": "save_chunks",
                "chunks": [
                    self._chunk(
                        req_id,
                        title="其他",
                        content="第二条切片。",
                        source_url="https://example.com/other",
                        evidence="第二条证据。",
                    )
                ],
            }
        )

        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        listed = self._call({"action": "list_chunks", "requirement_id": req_id})
        urls = {row["source_url"] for row in listed[1]["result"]["chunks"]}
        self.assertEqual(
            urls,
            {"https://example.com/sql-join", "https://example.com/other"},
        )
        self.assertEqual(self._table_count("knowledge_chunks"), 2)

    def test_missing_requirement_reports_id_without_saving(self) -> None:
        """要求不存在时只报告缺失 ID，不写切片。

        边界：requirement_id 未入库；传入带 source_url 的切片仍不得落库。
        """
        code, payload, _stderr = self._call(
            {
                "action": "save_chunks",
                "chunks": [self._chunk("req-missing")],
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            payload["result"],
            {"missing": "requirement_id", "requirement_ids": ["req-missing"]},
        )
        listed = self._call({"action": "list_chunks", "requirement_id": "req-missing"})
        self.assertEqual(listed[1]["result"]["chunks"], [])

    def test_invalid_chunk_writes_nothing(self) -> None:
        """任一切片缺必填非空字符串时整批不写入。

        边界：source_url 空串；后一条缺 evidence；title 非字符串；
        requirement_id 缺失、空白、非字符串。
        """
        req_id = self._requirement_id()
        valid = self._chunk(req_id)

        code, payload, _stderr = self._call(
            {
                "action": "save_chunks",
                "chunks": [self._chunk(req_id, title="man", content="ls 列出目录。", source_url="")],
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"], "invalid_input")
        self.assertEqual(self._table_count("knowledge_chunks"), 0)

        code, _payload, _stderr = self._call(
            {
                "action": "save_chunks",
                "chunks": [valid, self._chunk(req_id, title="rebase", evidence="")],
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("knowledge_chunks"), 0)

        code, _payload, _stderr = self._call(
            {"action": "save_chunks", "chunks": [self._chunk(req_id, title=1)]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("knowledge_chunks"), 0)

        missing_req = self._chunk(req_id)
        missing_req.pop("requirement_id")
        code, _payload, _stderr = self._call(
            {"action": "save_chunks", "chunks": [missing_req]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("knowledge_chunks"), 0)

        code, _payload, _stderr = self._call({"action": "save_chunks", "chunks": []})
        self.assertNotEqual(code, 0)

    def test_list_chunks_filter_does_not_leak_other_requirements(self) -> None:
        """按 requirement_id 列出时不得返回其他要求的切片。

        边界：Python 与 SQL 各一片；过滤 SQL 只返回 JOIN。
        """
        saved = self._call({"action": "save_jobs", "jobs": [self._backend_job()]})
        by_name = {
            row["name"]: row["requirement_id"]
            for row in saved[1]["result"]["jobs"][0]["requirements"]
        }
        self._call(
            {
                "action": "save_chunks",
                "chunks": [
                    self._chunk(by_name["Python"], title="list", content="列表。", source_url="https://example.com/py", evidence="list"),
                    self._chunk(by_name["SQL"]),
                ],
            }
        )
        listed = self._call(
            {"action": "list_chunks", "requirement_id": by_name["SQL"]}
        )
        chunks = listed[1]["result"]["chunks"]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["title"], "INNER JOIN")
        self.assertEqual(self._table_count("knowledge_chunks"), 2)


if __name__ == "__main__":
    unittest.main()
