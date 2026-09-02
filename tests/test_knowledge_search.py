"""知识搜索角色：按 requirement_id 复用、切分并落库带来源的学习资料。"""

from __future__ import annotations

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

    def test_search_saves_split_chunks_with_required_fields(self) -> None:
        """首次按 requirement_id 写入时，空行切开，每片带要求 ID、标题、正文和来源。

        边界：一篇两段公开资料；title 缺省时回落到要求名。
        """
        req = self.store.save_requirement(name="Python", requirement_id="req-py")
        result = self.role.search(
            req["requirement_id"],
            documents=[
                {
                    "content": "列表推导比循环更短。\n\n生成器按需产出值。",
                    "source_url": "https://docs.python.org/3/tutorial/datastructures.html",
                }
            ],
        )

        chunks = result["chunks"]
        self.assertFalse(result["reused"])
        self.assertEqual(result["requirement_id"], "req-py")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(
            [row["content"] for row in chunks],
            ["列表推导比循环更短。", "生成器按需产出值。"],
        )
        for row in chunks:
            self.assertEqual(row["requirement_id"], "req-py")
            self.assertEqual(row["title"], "Python")
            self.assertEqual(
                row["source_url"],
                "https://docs.python.org/3/tutorial/datastructures.html",
            )
        self.assertEqual(self.store.list_knowledge_chunks("req-py"), chunks)

    def test_repeat_search_reuses_saved_chunks(self) -> None:
        """同一 requirement_id 再次请求必须读已保存资料，不得追加新切片。

        边界：第二次传入不同 source_url 的 documents，库中仍只有第一次的来源。
        """
        req = self.store.save_requirement(name="SQL")
        first = self.role.search(
            req["requirement_id"],
            documents=[
                {
                    "title": "JOIN",
                    "content": "INNER JOIN 只返回匹配行。",
                    "source_url": "https://example.com/sql-join",
                }
            ],
        )
        second = self.role.search(
            req["requirement_id"],
            documents=[
                {
                    "title": "其他",
                    "content": "不该被写入。",
                    "source_url": "https://example.com/other",
                }
            ],
        )

        self.assertTrue(second["reused"])
        self.assertEqual(second["chunks"], first["chunks"])
        listed = self.store.list_knowledge_chunks(req["requirement_id"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["source_url"], "https://example.com/sql-join")

    def test_new_session_restores_chunks_by_requirement_id(self) -> None:
        """关闭连接后，新会话按同一 requirement_id 必须读回切片，且不再写入。

        边界：两个 MemoryStore 打开同一文件；第二次 search 不传 documents。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first_store = MemoryStore(path)
            req = first_store.save_requirement(name="HTTP", requirement_id="req-http")
            first_role = KnowledgeSearchRole(first_store)
            saved = first_role.search(
                "req-http",
                documents=[
                    {
                        "title": "GET",
                        "content": "GET 用于获取资源。",
                        "source_url": "https://example.com/http-get",
                    }
                ],
            )
            first_store.close()

            second_store = MemoryStore(path)
            try:
                restored = KnowledgeSearchRole(second_store).search("req-http")
                self.assertTrue(restored["reused"])
                self.assertEqual(restored["chunks"], saved["chunks"])
                self.assertEqual(
                    second_store.get_requirement("req-http")["name"],
                    "HTTP",
                )
            finally:
                second_store.close()

    def test_missing_requirement_reports_id_without_saving(self) -> None:
        """要求不存在时只报告缺失 ID，不写切片，也不把 documents 当岗位去搜。

        边界：requirement_id 未入库；传入带 source_url 的资料仍不得落库。
        """
        result = self.role.search(
            "req-missing",
            documents=[
                {
                    "title": "无关",
                    "content": "不该保存。",
                    "source_url": "https://example.com/x",
                }
            ],
        )
        self.assertEqual(
            result,
            {"missing": "requirement_id", "requirement_id": "req-missing"},
        )
        self.assertEqual(self.store.list_knowledge_chunks("req-missing"), [])

    def test_document_without_source_url_fails(self) -> None:
        """缺少来源 URL 必须失败，避免不可追溯的资料进入记忆。

        边界：title 与 content 齐全，source_url 为空字符串。
        """
        req = self.store.save_requirement(name="Linux")
        with self.assertRaises(ValueError):
            self.role.search(
                req["requirement_id"],
                documents=[{"title": "man", "content": "ls 列出目录。", "source_url": ""}],
            )
        self.assertEqual(self.store.list_knowledge_chunks(req["requirement_id"]), [])

    def test_batch_second_document_missing_source_url_writes_nothing(self) -> None:
        """后一份缺来源时整批不得落库，否则重试会复用半成品切片。

        边界：两份文档，第二份缺少 source_url。
        """
        req = self.store.save_requirement(name="Git")
        with self.assertRaises(ValueError):
            self.role.search(
                req["requirement_id"],
                documents=[
                    {
                        "title": "commit",
                        "content": "git commit 记录快照。",
                        "source_url": "https://example.com/git-commit",
                    },
                    {
                        "title": "rebase",
                        "content": "git rebase 重放提交。",
                    },
                ],
            )
        self.assertEqual(self.store.list_knowledge_chunks(req["requirement_id"]), [])


if __name__ == "__main__":
    unittest.main()
