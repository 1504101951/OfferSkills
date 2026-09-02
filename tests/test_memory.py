"""MemoryStore 接缝测试：只验证公开读写后的库状态与返回值。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from memory import MemoryStore

EXPECTED_TABLES = {
    "jobs",
    "requirements",
    "job_requirements",
    "knowledge_chunks",
    "questions",
    "answer_scores",
}


class MemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_initialize_creates_six_tables(self) -> None:
        """初始化必须建齐 6 张业务表，缺表则后续角色无法按契约读写。

        边界：对空文件初始化；只认业务表名，不含 sqlite 内部表。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            store = MemoryStore(path)
            store.close()
            conn = sqlite3.connect(path)
            try:
                names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
            finally:
                conn.close()
        self.assertEqual(names, EXPECTED_TABLES)

    def test_same_normalized_name_keeps_one_requirement(self) -> None:
        """同一 normalized_name 只保留一条要求，否则跨岗位无法复用资料和题目。

        边界：展示名大小写不同（Python / python），去重键相同，返回同一 requirement_id。
        """
        first = self.store.save_requirement(name="Python")
        second = self.store.save_requirement(name="python")
        self.assertEqual(first["requirement_id"], second["requirement_id"])
        self.assertEqual(first["normalized_name"], "python")
        self.assertEqual(second["name"], "Python")

    def test_requirement_links_multiple_jobs_with_evidence(self) -> None:
        """一个要求可挂多个岗位，evidence 按岗位对保留，不能互相覆盖。

        边界：两个岗位、同一 requirement_id、两条不同 evidence。
        """
        backend = self.store.save_job(
            source="web",
            source_url="https://example.com/jobs/backend",
            title="Backend Engineer",
            city="Shanghai",
            salary="30k-40k",
        )
        data = self.store.save_job(
            source="web",
            source_url="https://example.com/jobs/data",
            title="Data Engineer",
            city="Beijing",
        )
        req = self.store.save_requirement(name="Python")
        self.store.link_job_requirement(
            backend["job_id"], req["requirement_id"], evidence="精通 Python"
        )
        self.store.link_job_requirement(
            data["job_id"], req["requirement_id"], evidence="Python 3 年经验"
        )

        links = self.store.list_job_requirements(requirement_id=req["requirement_id"])
        by_job = {row["job_id"]: row["evidence"] for row in links}
        self.assertEqual(len(links), 2)
        self.assertEqual(by_job[backend["job_id"]], "精通 Python")
        self.assertEqual(by_job[data["job_id"]], "Python 3 年经验")

    def test_knowledge_question_score_roundtrip_by_stable_id(self) -> None:
        """资料、题目、评分按调用方稳定 ID 写入后必须原样读回。

        边界：ID 由调用方指定；知识切片必须带 source_url；评分字段按契约齐全。
        """
        req = self.store.save_requirement(name="SQL", requirement_id="req-sql")
        chunk = self.store.save_knowledge_chunk(
            chunk_id="chunk-sql-1",
            requirement_id=req["requirement_id"],
            source_url="https://example.com/sql-join",
            title="JOIN",
            content="INNER JOIN 只返回两表匹配行。",
            evidence="INNER JOIN 只返回两表匹配行。",
        )
        question = self.store.save_question(
            question_id="q-sql-1",
            requirement_id=req["requirement_id"],
            prompt="INNER JOIN 的结果包含什么？",
            standard_answer="两表键匹配的行。",
            explanation="不匹配的行会被丢弃。",
        )
        score = self.store.save_answer_score(
            score_id="score-1",
            question_id=question["question_id"],
            user_answer="返回笛卡尔积。",
            score=2,
            max_score=10,
            loss_reason="把 JOIN 理解成了叉乘。",
            weak_points="JOIN 与笛卡尔积的区别",
        )

        self.assertEqual(self.store.get_knowledge_chunk("chunk-sql-1"), chunk)
        self.assertEqual(self.store.get_question("q-sql-1"), question)
        self.assertEqual(self.store.get_answer_score("score-1"), score)
        self.assertEqual(
            self.store.list_knowledge_chunks("req-sql")[0]["source_url"],
            "https://example.com/sql-join",
        )
        self.assertEqual(
            self.store.list_knowledge_chunks("req-sql")[0]["evidence"],
            "INNER JOIN 只返回两表匹配行。",
        )
        self.assertEqual(self.store.list_questions("req-sql")[0]["question_id"], "q-sql-1")

    def test_same_question_keeps_multiple_scores(self) -> None:
        """同一 question_id 允许多次评分，后一次不得覆盖前一次。

        边界：两笔评分同一题、不同 score_id 与答案，list 长度为 2。
        """
        req = self.store.save_requirement(name="HTTP")
        question = self.store.save_question(
            requirement_id=req["requirement_id"],
            prompt="GET 与 POST 的区别？",
            standard_answer="GET 用于获取，POST 用于提交。",
        )
        first = self.store.save_answer_score(
            question_id=question["question_id"],
            user_answer="不知道",
            score=0,
            max_score=10,
            loss_reason="未作答",
            weak_points="HTTP 方法语义",
        )
        second = self.store.save_answer_score(
            question_id=question["question_id"],
            user_answer="GET 获取资源，POST 提交数据。",
            score=9,
            max_score=10,
            loss_reason="未提幂等性",
            weak_points="幂等",
        )

        scores = self.store.list_answer_scores(question["question_id"])
        self.assertEqual(len(scores), 2)
        self.assertEqual({row["score_id"] for row in scores}, {first["score_id"], second["score_id"]})
        self.assertEqual({row["score"] for row in scores}, {0, 9})

    def test_new_connection_reads_persisted_ids(self) -> None:
        """新连接打开同一文件后，必须能按稳定 ID 读回上一会话写入的记录。

        边界：关闭第一个连接再打开第二个；不是同一 MemoryStore 实例。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first = MemoryStore(path)
            job = first.save_job(
                job_id="job-1",
                source="web",
                source_url="https://example.com/jobs/1",
                title="Python Engineer",
            )
            req = first.save_requirement(name="Python", requirement_id="req-1")
            first.link_job_requirement(job["job_id"], req["requirement_id"], evidence="熟悉 Python")
            first.close()

            second = MemoryStore(path)
            try:
                loaded = second.get_job("job-1")
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded["title"], "Python Engineer")
                self.assertEqual(second.get_requirement("req-1")["normalized_name"], "python")
            finally:
                second.close()

    def test_reinitialize_after_delete_recreates_schema(self) -> None:
        """删除库文件后再次初始化必须能重新建表并写入。

        边界：先写入再删文件，新实例从空文件重建。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first = MemoryStore(path)
            first.save_job(
                source="web",
                source_url="https://example.com/jobs/old",
                title="Old",
            )
            first.close()
            path.unlink()

            second = MemoryStore(path)
            try:
                job = second.save_job(
                    source="web",
                    source_url="https://example.com/jobs/new",
                    title="New",
                )
                self.assertEqual(second.get_job(job["job_id"])["title"], "New")
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
