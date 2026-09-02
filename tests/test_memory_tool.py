"""JSON 工具脚本：真实 subprocess 往返与跨进程记忆恢复。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "memory_tool.py"


class JsonToolCase(unittest.TestCase):
    """在隔离 HOME 下启动 JSON 工具，避免写入开发者真实 ~/.offerskills。

    本身不含 test_*，只给各动作用例提供 subprocess 与临时库。
    """

    def setUp(self) -> None:
        """为每个用例准备独立 HOME。

        参数:
            无。
        返回:
            None。副作用是创建临时目录并设置 self.home / self.db_path / self.env。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.db_path = self.home / ".offerskills" / "jobseeker.db"
        self.env = {**os.environ, "HOME": str(self.home)}

    def tearDown(self) -> None:
        """删掉本用例的临时 HOME，避免残留库文件干扰后续用例。

        参数:
            无。
        返回:
            None。
        """
        self.tmp.cleanup()

    def _run(self, payload: dict[str, Any] | str) -> subprocess.CompletedProcess[str]:
        """在隔离 HOME 下启动脚本进程。cwd 不是仓库根，用于证明脚本自己能 import。

        参数:
            payload: 请求 object，或直接作为 stdin 的原始字符串。
        返回:
            subprocess.CompletedProcess，含 returncode、stdout、stderr。
        """
        raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=raw,
            capture_output=True,
            text=True,
            env=self.env,
            cwd=self.home,
        )

    def _call(self, payload: dict[str, Any] | str) -> tuple[int, dict[str, Any], str]:
        """跑一次工具并解析 stdout 为单个 JSON object。

        参数:
            payload: 请求 object，或非法 JSON 字符串。
        返回:
            (退出码, 响应 dict, stderr 原文)。
        """
        completed = self._run(payload)
        self.assertNotIn("Traceback", completed.stdout)
        self.assertNotIn("Traceback", completed.stderr)
        parsed = json.loads(completed.stdout)
        self.assertIsInstance(parsed, dict)
        return completed.returncode, parsed, completed.stderr

    def _backend_job(self, **overrides: object) -> dict[str, object]:
        """一份合法后端岗：字段已格式化，要求由 Agent 给出。"""
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

    def _table_count(self, table: str) -> int:
        """直接读 SQLite 行数，确认工具写入或回滚后的真实库状态。"""
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()


class MemoryToolProtocolTest(JsonToolCase):
    def test_protocol_errors_are_json_and_nonzero(self) -> None:
        """非法 JSON、非 object、未知动作必须 JSON 失败且非零退出，不得写库。

        边界：stdout 可 json.loads；无 traceback；默认库文件尚未创建。
        """
        cases = [
            ("not json", "invalid_json"),
            ("[]", "invalid_request"),
            ('{"action": "nope"}', "unknown_action"),
        ]
        for raw, error in cases:
            with self.subTest(raw=raw):
                code, payload, stderr = self._call(raw)
                self.assertNotEqual(code, 0)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"], error)
                self.assertEqual(payload["db_path"], str(self.db_path))
                self.assertEqual(stderr, "")
                self.assertFalse(self.db_path.exists())

    def test_search_knowledge_is_unknown_action(self) -> None:
        """旧动作名必须失败，避免 Agent 继续走搜索复用分支。

        边界：search_knowledge 不在公开动作中；不写库。
        """
        code, payload, stderr = self._call(
            {"action": "search_knowledge", "requirement_id": "req-x"}
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "unknown_action")
        self.assertEqual(stderr, "")
        self.assertFalse(self.db_path.exists())

    def test_deeply_nested_json_is_invalid_json(self) -> None:
        """过深嵌套必须按 invalid_json 失败，不能把 RecursionError traceback 漏到 stderr。

        边界：约 1200 层数组；stdout 可 json.loads 为单个 object；stderr 空；非零退出。
        """
        nested = "[" * 1200 + "]" * 1200
        code, payload, stderr = self._call(nested)
        self.assertNotEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid_json")
        self.assertEqual(payload["db_path"], str(self.db_path))
        self.assertEqual(stderr, "")
        self.assertFalse(self.db_path.exists())

    def test_missing_stable_ids_do_not_write(self) -> None:
        """查询不存在的稳定 ID 必须返回 missing 结构，退出码 0，业务表无行。

        边界：job_id / chunk_id / question_id / score_id 均未写入过。
        """
        cases = [
            ({"action": "get_job", "job_id": "job-missing"}, "job_id"),
            ({"action": "get_chunk", "chunk_id": "chunk-missing"}, "chunk_id"),
            ({"action": "get_question", "question_id": "q-missing"}, "question_id"),
            ({"action": "get_score", "score_id": "score-missing"}, "score_id"),
        ]
        for request, missing in cases:
            with self.subTest(action=request["action"]):
                code, payload, _stderr = self._call(request)
                self.assertEqual(code, 0)
                self.assertTrue(payload["ok"])
                self.assertEqual(
                    payload["result"],
                    {"missing": missing, missing: request[missing]},
                )

        counts = {
            table: self._table_count(table)
            for table in (
                "jobs",
                "knowledge_chunks",
                "questions",
                "answer_scores",
            )
        }
        self.assertEqual(set(counts.values()), {0})

    def test_request_db_path_does_not_override_default(self) -> None:
        """请求夹带 db_path 不得改默认库，否则新会话会读到空文件。

        边界：另给一个绝对路径；写入仍落在 ~/.offerskills/jobseeker.db。
        """
        other = self.home / "other.db"
        code, payload, _stderr = self._call(
            {
                "action": "save_jobs",
                "db_path": str(other),
                "jobs": [self._backend_job()],
            }
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["db_path"], str(self.db_path))
        self.assertTrue(self.db_path.is_file())
        self.assertFalse(other.exists())

        loaded = self._call({"action": "get_job", "job_id": "job-backend"})
        self.assertEqual(loaded[1]["result"]["title"], "Backend Engineer")


class MemoryToolRoundtripTest(JsonToolCase):
    def test_roundtrip_persists_across_processes(self) -> None:
        """四类保存必须经真实进程写入默认库，下一进程按稳定 ID 与 list_* 读回同一数据。

        边界：每个动作单独起进程；cwd 为临时 HOME；库文件是展开后的
        ~/.offerskills/jobseeker.db；知识写入是 save_chunks 而不是旧搜索动作。
        """
        save_jobs = self._call({"action": "save_jobs", "jobs": [self._backend_job()]})
        self.assertEqual(save_jobs[0], 0)
        self.assertTrue(save_jobs[1]["ok"])
        self.assertEqual(save_jobs[1]["db_path"], str(self.db_path))
        self.assertTrue(self.db_path.is_file())
        job = save_jobs[1]["result"]["jobs"][0]
        requirement_id = job["requirements"][0]["requirement_id"]

        loaded_job = self._call({"action": "get_job", "job_id": "job-backend"})
        self.assertEqual(loaded_job[0], 0)
        self.assertEqual(loaded_job[1]["result"]["title"], "Backend Engineer")
        self.assertEqual(
            loaded_job[1]["result"]["requirements"][0]["requirement_id"],
            requirement_id,
        )

        listed_jobs = self._call({"action": "list_jobs"})
        self.assertEqual(listed_jobs[0], 0)
        self.assertEqual(len(listed_jobs[1]["result"]["jobs"]), 1)
        self.assertEqual(listed_jobs[1]["result"]["jobs"][0]["job_id"], "job-backend")

        listed_requirements = self._call(
            {"action": "list_requirements", "job_id": "job-backend"}
        )
        self.assertEqual(listed_requirements[0], 0)
        listed_names = {
            row["name"] for row in listed_requirements[1]["result"]["requirements"]
        }
        self.assertEqual(listed_names, {"Python", "SQL"})
        all_requirements = self._call({"action": "list_requirements"})
        self.assertEqual(
            {row["name"] for row in all_requirements[1]["result"]["requirements"]},
            {"Python", "SQL"},
        )

        sql_id = next(
            row["requirement_id"]
            for row in job["requirements"]
            if row["name"] == "SQL"
        )
        saved_knowledge = self._call(
            {
                "action": "save_chunks",
                "chunks": [
                    {
                        "requirement_id": sql_id,
                        "title": "INNER JOIN",
                        "content": "INNER JOIN 只返回两表键匹配的行。",
                        "source_url": "https://example.com/sql-join",
                        "evidence": "INNER JOIN produces only matching rows.",
                    }
                ],
            }
        )
        self.assertEqual(saved_knowledge[0], 0)
        chunk = saved_knowledge[1]["result"]["chunks"][0]
        chunk_id = chunk["chunk_id"]

        listed_chunks = self._call(
            {"action": "list_chunks", "requirement_id": sql_id}
        )
        self.assertEqual(listed_chunks[0], 0)
        self.assertEqual(listed_chunks[1]["result"]["chunks"][0]["chunk_id"], chunk_id)

        loaded_chunk = self._call({"action": "get_chunk", "chunk_id": chunk_id})
        self.assertEqual(loaded_chunk[0], 0)
        self.assertEqual(loaded_chunk[1]["result"]["title"], "INNER JOIN")
        self.assertEqual(
            loaded_chunk[1]["result"]["evidence"],
            "INNER JOIN produces only matching rows.",
        )

        saved_questions = self._call(
            {
                "action": "save_questions",
                "drafts": [
                    {
                        "chunk_id": chunk_id,
                        "prompt": "INNER JOIN 返回哪些行？",
                        "standard_answer": "只返回两表键匹配的行。",
                        "explanation": "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。",
                    }
                ],
            }
        )
        self.assertEqual(saved_questions[0], 0)
        question_id = saved_questions[1]["result"]["questions"][0]["question_id"]

        loaded_question = self._call(
            {"action": "get_question", "question_id": question_id}
        )
        self.assertEqual(loaded_question[0], 0)
        self.assertEqual(
            loaded_question[1]["result"]["prompt"],
            "INNER JOIN 返回哪些行？",
        )
        listed_questions = self._call(
            {"action": "list_questions", "requirement_id": sql_id}
        )
        self.assertEqual(
            listed_questions[1]["result"]["questions"][0]["question_id"],
            question_id,
        )

        saved_score = self._call(
            {
                "action": "save_score",
                "question_id": question_id,
                "result": {
                    "user_answer": "返回笛卡尔积。",
                    "score": 2,
                    "max_score": 10,
                    "loss_reason": "把 JOIN 理解成了叉乘。",
                    "weak_points": "JOIN 与笛卡尔积的区别",
                },
            }
        )
        self.assertEqual(saved_score[0], 0)
        score_id = saved_score[1]["result"]["score_id"]
        self.assertEqual(saved_score[1]["result"]["score"], 2)

        loaded_score = self._call({"action": "get_score", "score_id": score_id})
        self.assertEqual(loaded_score[0], 0)
        self.assertEqual(loaded_score[1]["result"]["user_answer"], "返回笛卡尔积。")
        self.assertEqual(loaded_score[1]["result"]["weak_points"], "JOIN 与笛卡尔积的区别")
        listed_scores = self._call(
            {"action": "list_scores", "question_id": question_id}
        )
        self.assertEqual(listed_scores[1]["result"]["scores"][0]["score_id"], score_id)
        self.assertEqual(listed_scores[2], "")


if __name__ == "__main__":
    unittest.main()
