"""save_jobs：校验并保存结构化岗位与原子要求，按 job_id 回找。"""

from __future__ import annotations

from test_memory_tool import JsonToolCase


class SaveJobsTest(JsonToolCase):
    def test_save_jobs_persists_formatted_job_and_atomic_requirements(self) -> None:
        """首次写入必须保存 Agent 给出的岗位字段，并按传入的原子要求落库。

        边界：要求已带非空 name 与原文 evidence；不得再从其它字段推断条目。
        """
        code, payload, _stderr = self._call(
            {"action": "save_jobs", "jobs": [self._backend_job()]}
        )

        self.assertEqual(code, 0)
        jobs = payload["result"]["jobs"]
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
        self.assertEqual(self._table_count("jobs"), 1)
        self.assertEqual(self._table_count("job_requirements"), 2)

    def test_save_jobs_does_not_infer_requirements_from_description(self) -> None:
        """岗位描述即使含列表句式，也不得被拆成额外原子要求。

        边界：description 为「熟悉 Python、SQL、Redis」；requirements 只给 Python。
        """
        code, payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(
                        description="熟悉 Python、SQL、Redis",
                        requirements=[
                            {"name": "Python", "evidence": "熟悉 Python、SQL、Redis"}
                        ],
                    )
                ],
            }
        )

        self.assertEqual(code, 0)
        job = payload["result"]["jobs"][0]
        self.assertEqual({row["name"] for row in job["requirements"]}, {"Python"})
        self.assertEqual(
            job["requirements"][0]["evidence"],
            "熟悉 Python、SQL、Redis",
        )
        self.assertEqual(self._table_count("job_requirements"), 1)

    def test_same_requirement_links_multiple_jobs_with_evidence(self) -> None:
        """同一原子要求跨岗位只保留一条，evidence 按岗位对保留。

        边界：展示名大小写不同（Python / python），去重后 requirement_id 相同。
        """
        code, payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "jobs": [
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
                ],
            }
        )

        self.assertEqual(code, 0)
        jobs = {row["job_id"]: row for row in payload["result"]["jobs"]}
        backend_req = jobs["job-backend"]["requirements"][0]
        data_req = jobs["job-data"]["requirements"][0]
        self.assertEqual(backend_req["requirement_id"], data_req["requirement_id"])
        self.assertEqual(backend_req["evidence"], "精通 Python")
        self.assertEqual(data_req["evidence"], "python 数据处理")
        listed = self._call(
            {"action": "list_requirements", "job_id": "job-data"}
        )
        self.assertEqual(listed[1]["result"]["requirements"][0]["evidence"], "python 数据处理")
        self.assertEqual(self._table_count("requirements"), 1)
        self.assertEqual(self._table_count("job_requirements"), 2)

    def test_new_process_gets_job_and_requirements_by_job_id(self) -> None:
        """下一进程必须能按 job_id 读回岗位与要求。

        边界：两次真实 subprocess；第二次只调用 get_job。
        """
        saved = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(
                        job_id="job-1",
                        title="Python Engineer",
                        city="Hangzhou",
                        salary="25k-35k",
                        source_url="https://example.com/jobs/1",
                    )
                ],
            }
        )
        loaded = self._call({"action": "get_job", "job_id": "job-1"})
        saved_job = {
            key: value
            for key, value in saved[1]["result"]["jobs"][0].items()
            if key != "reused"
        }
        self.assertEqual(loaded[1]["result"], saved_job)
        self.assertEqual(loaded[1]["result"]["title"], "Python Engineer")
        self.assertEqual(loaded[1]["result"]["salary"], "25k-35k")
        names = {row["name"] for row in loaded[1]["result"]["requirements"]}
        self.assertEqual(names, {"Python", "SQL"})

    def test_invalid_job_is_json_error_and_not_saved(self) -> None:
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
        code, payload, stderr = self._call(
            {"action": "save_jobs", "jobs": [valid, missing_url]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"], "invalid_input")
        self.assertEqual(payload["message"], "岗位或要求无效")
        self.assertEqual(stderr, "")
        self.assertEqual(self._table_count("jobs"), 0)

        missing_evidence = self._backend_job(
            job_id="job-empty-evidence",
            requirements=[{"name": "Python", "evidence": ""}],
        )
        code, payload, _stderr = self._call(
            {"action": "save_jobs", "jobs": [valid, missing_evidence]}
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self._table_count("jobs"), 0)

        missing_requirements = self._backend_job(job_id="job-no-req")
        missing_requirements.pop("requirements")
        code, payload, _stderr = self._call(
            {"action": "save_jobs", "jobs": [valid, missing_requirements]}
        )
        self.assertNotEqual(code, 0)
        loaded = self._call({"action": "get_job", "job_id": "job-ok"})
        self.assertEqual(
            loaded[1]["result"],
            {"missing": "job_id", "job_id": "job-ok"},
        )

    def test_repeat_save_same_job_id_reuses_snapshot(self) -> None:
        """同一 job_id 再次传入必须返回已保存快照，不得覆盖岗位或追加要求。

        边界：首次要求为 Python/SQL；第二次同 job_id 传入 Redis 且字段不同。
        """
        first = self._call({"action": "save_jobs", "jobs": [self._backend_job()]})
        second = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(
                        source_url="https://example.com/jobs/other",
                        title="Other",
                        city="Beijing",
                        salary="10k",
                        requirements=[{"name": "Redis", "evidence": "熟悉 Redis"}],
                    )
                ],
            }
        )

        first_job = first[1]["result"]["jobs"][0]
        job = second[1]["result"]["jobs"][0]
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
        self.assertEqual(self._table_count("job_requirements"), 2)

    def test_same_job_id_in_one_save_reuses_first_snapshot(self) -> None:
        """同一次 save_jobs 中重复 job_id 只按首次条目落库，后续标记 reused。

        边界：两条同 ID；首次 Python/SQL，第二次 Redis 且字段不同。
        """
        code, payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(),
                    self._backend_job(
                        source_url="https://example.com/jobs/other",
                        title="Other",
                        city="Beijing",
                        salary="10k",
                        requirements=[{"name": "Redis", "evidence": "熟悉 Redis"}],
                    ),
                ],
            }
        )

        self.assertEqual(code, 0)
        jobs = payload["result"]["jobs"]
        self.assertEqual(len(jobs), 2)
        first, second = jobs
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        snapshot = {key: value for key, value in first.items() if key != "reused"}
        self.assertEqual(
            {key: value for key, value in second.items() if key != "reused"},
            snapshot,
        )
        self.assertEqual({row["name"] for row in first["requirements"]}, {"Python", "SQL"})
        self.assertEqual(self._table_count("jobs"), 1)
        self.assertEqual(self._table_count("job_requirements"), 2)

    def test_invalid_duplicate_job_id_writes_nothing(self) -> None:
        """已存在或本批重复的 job_id 仍须校验当前输入，无效则整批不写入。

        边界：先保存 saved，再同批传入合法 new 与 saved 的非列表 requirements；
        另：同批首次合法、后续同 ID 缺 source_url。
        """
        self._call({"action": "save_jobs", "jobs": [self._backend_job(job_id="saved")]})
        code, _payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(
                        job_id="new",
                        source_url="https://example.com/jobs/new",
                    ),
                    {"job_id": "saved", "requirements": "not-a-list"},
                ],
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            self._call({"action": "get_job", "job_id": "new"})[1]["result"],
            {"missing": "job_id", "job_id": "new"},
        )
        saved = self._call({"action": "get_job", "job_id": "saved"})
        self.assertEqual(saved[1]["result"]["title"], "Backend Engineer")
        self.assertEqual(
            {row["name"] for row in saved[1]["result"]["requirements"]},
            {"Python", "SQL"},
        )

        code, _payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "jobs": [
                    self._backend_job(job_id="batch-first"),
                    {
                        "job_id": "batch-first",
                        "source": "web",
                        "title": "Other",
                        "requirements": [{"name": "Redis", "evidence": "熟悉 Redis"}],
                    },
                ],
            }
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(
            self._call({"action": "get_job", "job_id": "batch-first"})[1]["result"],
            {"missing": "job_id", "job_id": "batch-first"},
        )


if __name__ == "__main__":
    unittest.main()
