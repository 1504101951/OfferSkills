"""岗位搜索角色：校验并保存结构化岗位与原子要求，按 job_id 回找。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from job_search import JobSearchRole
from memory import MemoryStore


class JobSearchRoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore(":memory:")
        self.role = JobSearchRole(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def _backend_job(self, **overrides: object) -> dict[str, object]:
        """一份合法后端岗：字段已格式化，要求由 Agent 给出，不依赖描述解析。"""
        listing: dict[str, object] = {
            "job_id": "job-backend",
            "source": "web",
            "source_url": "https://example.com/jobs/backend",
            "title": "Backend Engineer",
            "city": "Shanghai",
            "salary": "30k-40k",
            "requirements": [
                {"name": "Python", "evidence": "熟悉 Python"},
                {"name": "SQL", "evidence": "3 年 SQL 经验"},
            ],
        }
        listing.update(overrides)
        return listing

    def test_search_saves_formatted_job_and_atomic_requirements(self) -> None:
        """首次写入必须保存 Agent 给出的岗位字段，并按传入的原子要求落库。

        边界：要求已带非空 name 与原文 evidence；不得再从其它字段推断条目。
        """
        result = self.role.search([self._backend_job()])

        jobs = result["jobs"]
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertFalse(job["reused"])
        self.assertEqual(job["job_id"], "job-backend")
        self.assertEqual(job["source"], "web")
        self.assertEqual(job["source_url"], "https://example.com/jobs/backend")
        self.assertEqual(job["title"], "Backend Engineer")
        self.assertEqual(job["city"], "Shanghai")
        self.assertEqual(job["salary"], "30k-40k")
        by_name = {row["name"]: row for row in job["requirements"]}
        self.assertEqual(set(by_name), {"Python", "SQL"})
        self.assertEqual(by_name["Python"]["normalized_name"], "python")
        self.assertEqual(by_name["Python"]["evidence"], "熟悉 Python")
        self.assertEqual(by_name["SQL"]["evidence"], "3 年 SQL 经验")
        self.assertEqual(self.store.get_job("job-backend")["title"], "Backend Engineer")
        self.assertEqual(
            len(self.store.list_job_requirements(job_id="job-backend")),
            2,
        )

    def test_search_does_not_infer_requirements_from_description(self) -> None:
        """岗位描述即使含列表句式，也不得被拆成额外原子要求。

        边界：description 为「熟悉 Python、SQL、Redis」；requirements 只给 Python。
        """
        result = self.role.search(
            [
                self._backend_job(
                    description="熟悉 Python、SQL、Redis",
                    requirements=[{"name": "Python", "evidence": "熟悉 Python、SQL、Redis"}],
                )
            ]
        )

        job = result["jobs"][0]
        self.assertEqual({row["name"] for row in job["requirements"]}, {"Python"})
        self.assertEqual(
            job["requirements"][0]["evidence"],
            "熟悉 Python、SQL、Redis",
        )
        self.assertEqual(
            len(self.store.list_job_requirements(job_id="job-backend")),
            1,
        )

    def test_same_requirement_links_multiple_jobs_with_evidence(self) -> None:
        """同一原子要求跨岗位只保留一条，evidence 按岗位对保留。

        边界：展示名大小写不同（Python / python），去重后 requirement_id 相同。
        """
        result = self.role.search(
            [
                self._backend_job(
                    requirements=[{"name": "Python", "evidence": "精通 Python"}]
                ),
                {
                    "job_id": "job-data",
                    "source": "web",
                    "source_url": "https://example.com/jobs/data",
                    "title": "Data Engineer",
                    "city": "Beijing",
                    "requirements": [{"name": "python", "evidence": "python 数据处理"}],
                },
            ]
        )

        jobs = {row["job_id"]: row for row in result["jobs"]}
        backend_req = jobs["job-backend"]["requirements"][0]
        data_req = jobs["job-data"]["requirements"][0]
        self.assertEqual(backend_req["requirement_id"], data_req["requirement_id"])
        self.assertEqual(backend_req["evidence"], "精通 Python")
        self.assertEqual(data_req["evidence"], "python 数据处理")
        links = self.store.list_job_requirements(
            requirement_id=backend_req["requirement_id"]
        )
        by_job = {row["job_id"]: row["evidence"] for row in links}
        self.assertEqual(len(links), 2)
        self.assertEqual(by_job["job-backend"], "精通 Python")
        self.assertEqual(by_job["job-data"], "python 数据处理")

    def test_new_session_gets_job_and_requirements_by_job_id(self) -> None:
        """关闭连接后，新会话必须能按 job_id 读回岗位与要求。

        边界：两个 MemoryStore 打开同一文件；第二次只调用 get。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.db"
            first_store = MemoryStore(path)
            saved = JobSearchRole(first_store).search(
                [
                    self._backend_job(
                        job_id="job-1",
                        title="Python Engineer",
                        city="Hangzhou",
                        salary="25k-35k",
                        source_url="https://example.com/jobs/1",
                    )
                ]
            )
            first_store.close()

            second_store = MemoryStore(path)
            try:
                loaded = JobSearchRole(second_store).get("job-1")
                saved_job = {
                    key: value
                    for key, value in saved["jobs"][0].items()
                    if key != "reused"
                }
                self.assertEqual(loaded, saved_job)
                self.assertEqual(loaded["title"], "Python Engineer")
                self.assertEqual(loaded["salary"], "25k-35k")
                names = {row["name"] for row in loaded["requirements"]}
                self.assertEqual(names, {"Python", "SQL"})
            finally:
                second_store.close()

    def test_missing_job_id_reports_without_searching(self) -> None:
        """岗位不存在时只报告缺失 ID，不隐式搜索或写入。

        边界：job_id 未入库；get 后库中仍无该岗位。
        """
        result = self.role.get("job-missing")
        self.assertEqual(result, {"missing": "job_id", "job_id": "job-missing"})
        self.assertIsNone(self.store.get_job("job-missing"))

    def test_invalid_job_or_requirement_writes_nothing(self) -> None:
        """任一岗位或要求无效必须整批失败，已合法条目也不落库。

        边界：后一条缺 source_url；后一条要求缺 evidence；缺 requirements 列表。
        """
        valid = self._backend_job(job_id="job-ok")
        missing_url = {
            "job_id": "job-bad",
            "source": "web",
            "title": "Data Engineer",
            "requirements": [{"name": "SQL", "evidence": "熟悉 SQL"}],
        }
        with self.assertRaises(ValueError):
            self.role.search([valid, missing_url])
        self.assertIsNone(self.store.get_job("job-ok"))
        self.assertIsNone(self.store.get_job("job-bad"))

        missing_evidence = self._backend_job(
            job_id="job-empty-evidence",
            requirements=[{"name": "Python", "evidence": ""}],
        )
        with self.assertRaises(ValueError):
            self.role.search([valid, missing_evidence])
        self.assertIsNone(self.store.get_job("job-ok"))
        self.assertIsNone(self.store.get_job("job-empty-evidence"))

        missing_requirements = self._backend_job(job_id="job-no-req")
        missing_requirements.pop("requirements")
        with self.assertRaises(ValueError):
            self.role.search([valid, missing_requirements])
        self.assertIsNone(self.store.get_job("job-ok"))
        self.assertIsNone(self.store.get_job("job-no-req"))

    def test_repeat_search_same_job_id_reuses_snapshot(self) -> None:
        """同一 job_id 再次传入必须返回已保存快照，不得覆盖岗位或追加要求。

        边界：首次要求为 Python/SQL；第二次同 job_id 传入 Redis 且字段不同。
        """
        first = self.role.search([self._backend_job()])
        second = self.role.search(
            [
                self._backend_job(
                    source_url="https://example.com/jobs/other",
                    title="Other",
                    city="Beijing",
                    salary="10k",
                    requirements=[{"name": "Redis", "evidence": "熟悉 Redis"}],
                )
            ]
        )

        first_job = first["jobs"][0]
        job = second["jobs"][0]
        self.assertFalse(first_job["reused"])
        self.assertTrue(job["reused"])
        self.assertEqual(job["title"], "Backend Engineer")
        self.assertEqual(job["source_url"], "https://example.com/jobs/backend")
        self.assertEqual(job["city"], "Shanghai")
        self.assertEqual(job["salary"], "30k-40k")
        self.assertEqual({row["name"] for row in job["requirements"]}, {"Python", "SQL"})
        snapshot = {key: value for key, value in first_job.items() if key != "reused"}
        self.assertEqual(
            {key: value for key, value in job.items() if key != "reused"},
            snapshot,
        )

        stored = self.store.get_job("job-backend")
        self.assertEqual(stored["title"], "Backend Engineer")
        self.assertEqual(stored["source_url"], "https://example.com/jobs/backend")
        links = self.store.list_job_requirements(job_id="job-backend")
        self.assertEqual(len(links), 2)
        names = {
            self.store.get_requirement(row["requirement_id"])["name"] for row in links
        }
        self.assertEqual(names, {"Python", "SQL"})

    def test_same_job_id_in_one_search_reuses_first_snapshot(self) -> None:
        """同一次 search 中重复 job_id 只按首次条目落库，后续标记 reused。

        边界：两条同 ID；首次 Python/SQL，第二次 Redis 且字段不同。
        """
        result = self.role.search(
            [
                self._backend_job(),
                self._backend_job(
                    source_url="https://example.com/jobs/other",
                    title="Other",
                    city="Beijing",
                    salary="10k",
                    requirements=[{"name": "Redis", "evidence": "熟悉 Redis"}],
                ),
            ]
        )

        jobs = result["jobs"]
        self.assertEqual(len(jobs), 2)
        first, second = jobs
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        snapshot = {key: value for key, value in first.items() if key != "reused"}
        self.assertEqual(
            {key: value for key, value in second.items() if key != "reused"},
            snapshot,
        )
        self.assertEqual(first["title"], "Backend Engineer")
        self.assertEqual(first["source_url"], "https://example.com/jobs/backend")
        self.assertEqual(
            {row["name"] for row in first["requirements"]},
            {"Python", "SQL"},
        )

        stored = self.store.get_job("job-backend")
        self.assertEqual(stored["title"], "Backend Engineer")
        self.assertEqual(stored["source_url"], "https://example.com/jobs/backend")
        links = self.store.list_job_requirements(job_id="job-backend")
        self.assertEqual(len(links), 2)
        names = {
            self.store.get_requirement(row["requirement_id"])["name"] for row in links
        }
        self.assertEqual(names, {"Python", "SQL"})


if __name__ == "__main__":
    unittest.main()
