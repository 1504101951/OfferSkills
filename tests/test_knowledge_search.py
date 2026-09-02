"""知识搜索角色：接收 Agent 切片、校验必填字段并原子入库。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from knowledge_search import KnowledgeSearchRole
from memory import MemoryStore


class KnowledgeSearchRoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore(":memory:")
        self.role = KnowledgeSearchRole(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _chunk(self, **overrides: object) -> dict[str, object]:
        """一份合法切片：字段已由 Agent 切好，不依赖空行分段。"""
        chunk: dict[str, object] = {
            "title": "INNER JOIN",
            "content": "INNER JOIN 只返回两表键匹配的行。",
            "source_url": "https://example.com/sql-join",
            "evidence": "INNER JOIN produces only matching rows.",
        }
        chunk.update(overrides)
        return chunk

    def test_search_saves_agent_chunks_with_source_and_evidence(self) -> None:
        """首次写入必须保存 Agent 给出的语义切片，含来源与证据，且不按空行再切。

        边界：一篇含空行的 content 仍是一条切片；title/evidence 不得回落到要求名。
        """
        req = self.store.save_requirement(name="Python", requirement_id="req-py")
        result = self.role.search(
            req["requirement_id"],
            chunks=[
                self._chunk(
                    title="列表与生成器",
                    content="列表推导比循环更短。\n\n生成器按需产出值。",
                    source_url="https://docs.python.org/3/tutorial/datastructures.html",
                    evidence="List comprehensions provide a concise way to create lists.",
                )
            ],
        )

        chunks = result["chunks"]
        self.assertFalse(result["reused"])
        self.assertEqual(result["requirement_id"], "req-py")
        self.assertEqual(len(chunks), 1)
        row = chunks[0]
        self.assertEqual(row["requirement_id"], "req-py")
        self.assertEqual(row["title"], "列表与生成器")
        self.assertEqual(
            row["content"],
            "列表推导比循环更短。\n\n生成器按需产出值。",
        )
        self.assertEqual(
            row["source_url"],
            "https://docs.python.org/3/tutorial/datastructures.html",
        )
        self.assertEqual(
            row["evidence"],
            "List comprehensions provide a concise way to create lists.",
        )
        self.assertEqual(self.store.list_knowledge_chunks("req-py"), chunks)

    def test_repeat_search_reuses_saved_chunks(self) -> None:
        """同一 requirement_id 再次请求必须读已保存资料，不得追加新切片。

        边界：第二次传入不同 source_url 的 chunks，库中仍只有第一次的来源。
        """
        req = self.store.save_requirement(name="SQL")
        first = self.role.search(
            req["requirement_id"],
            chunks=[self._chunk()],
        )
        second = self.role.search(
            req["requirement_id"],
            chunks=[
                self._chunk(
                    title="其他",
                    content="不该被写入。",
                    source_url="https://example.com/other",
                    evidence="不该出现。",
                )
            ],
        )

        self.assertTrue(second["reused"])
        self.assertEqual(second["chunks"], first["chunks"])
        listed = self.store.list_knowledge_chunks(req["requirement_id"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["source_url"], "https://example.com/sql-join")
        self.assertEqual(listed[0]["evidence"], "INNER JOIN produces only matching rows.")

    def test_new_session_restores_chunks_by_requirement_id(self) -> None:
        """关闭连接后，新会话按同一 requirement_id 必须读回完整切片，且不再写入。

        边界：两个 MemoryStore 打开同一文件；第二次 search 不传 chunks。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first_store = MemoryStore(path)
            first_store.save_requirement(name="HTTP", requirement_id="req-http")
            first_role = KnowledgeSearchRole(first_store)
            saved = first_role.search(
                "req-http",
                chunks=[
                    self._chunk(
                        title="GET",
                        content="GET 用于获取资源。",
                        source_url="https://example.com/http-get",
                        evidence="GET requests a representation of the specified resource.",
                    )
                ],
            )
            first_store.close()

            second_store = MemoryStore(path)
            try:
                restored = KnowledgeSearchRole(second_store).search("req-http")
                self.assertTrue(restored["reused"])
                self.assertEqual(restored["chunks"], saved["chunks"])
                self.assertEqual(
                    restored["chunks"][0]["evidence"],
                    "GET requests a representation of the specified resource.",
                )
                self.assertEqual(
                    second_store.get_requirement("req-http")["name"],
                    "HTTP",
                )
            finally:
                second_store.close()

    def test_missing_requirement_reports_id_without_saving(self) -> None:
        """要求不存在时只报告缺失 ID，不写切片，也不把 chunks 当岗位去搜。

        边界：requirement_id 未入库；传入带 source_url 的切片仍不得落库。
        """
        result = self.role.search("req-missing", chunks=[self._chunk()])
        self.assertEqual(
            result,
            {"missing": "requirement_id", "requirement_id": "req-missing"},
        )
        self.assertEqual(self.store.list_knowledge_chunks("req-missing"), [])

    def test_invalid_chunk_writes_nothing(self) -> None:
        """任一切片缺必填非空字符串时整批不写入，避免半成品被下次 search 复用。

        边界：source_url 空串；后一条缺 evidence；title 非字符串；requirement_id 不一致。
        """
        req = self.store.save_requirement(name="Linux")
        req_id = req["requirement_id"]
        valid = self._chunk()

        with self.assertRaises(ValueError):
            self.role.search(
                req_id,
                chunks=[self._chunk(title="man", content="ls 列出目录。", source_url="")],
            )
        self.assertEqual(self.store.list_knowledge_chunks(req_id), [])

        with self.assertRaises(ValueError):
            self.role.search(
                req_id,
                chunks=[valid, self._chunk(title="rebase", evidence="")],
            )
        self.assertEqual(self.store.list_knowledge_chunks(req_id), [])

        with self.assertRaises(ValueError):
            self.role.search(req_id, chunks=[self._chunk(title=1)])
        self.assertEqual(self.store.list_knowledge_chunks(req_id), [])

        with self.assertRaises(ValueError):
            self.role.search(
                req_id,
                chunks=[self._chunk(requirement_id="req-other")],
            )
        self.assertEqual(self.store.list_knowledge_chunks(req_id), [])

        with self.assertRaises(ValueError):
            self.role.search(req_id, chunks=[])
        self.assertEqual(self.store.list_knowledge_chunks(req_id), [])

    def test_constraint_error_in_batch_writes_nothing(self) -> None:
        """事务中途外键失败必须整批回滚，否则半批会被下次 search 复用。

        边界：第二片 requirement_id 在 requirements 表中不存在。
        """
        req = self.store.save_requirement(name="Git")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_knowledge_chunks(
                [
                    {
                        "requirement_id": req["requirement_id"],
                        "title": "commit",
                        "content": "git commit 记录快照。",
                        "source_url": "https://example.com/git-commit",
                        "evidence": "git commit creates a snapshot.",
                    },
                    {
                        "requirement_id": "req-missing",
                        "title": "rebase",
                        "content": "git rebase 重放提交。",
                        "source_url": "https://example.com/git-rebase",
                        "evidence": "git rebase reapplies commits.",
                    },
                ]
            )
        self.assertEqual(self.store.list_knowledge_chunks(req["requirement_id"]), [])


if __name__ == "__main__":
    unittest.main()
