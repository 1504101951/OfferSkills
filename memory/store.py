"""共享 SQLite 记忆：岗位、要求、资料、题目和评分的最小读写。"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    city TEXT,
    salary TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS requirements (
    requirement_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS job_requirements (
    job_id TEXT NOT NULL,
    requirement_id TEXT NOT NULL,
    evidence TEXT NOT NULL,
    PRIMARY KEY (job_id, requirement_id),
    FOREIGN KEY (job_id) REFERENCES jobs(job_id),
    FOREIGN KEY (requirement_id) REFERENCES requirements(requirement_id)
);

-- title/evidence 必填：出题角色把切片当完整资料，缺标题或出处原文无法追溯
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    requirement_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT NOT NULL,
    FOREIGN KEY (requirement_id) REFERENCES requirements(requirement_id)
);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    requirement_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    standard_answer TEXT NOT NULL,
    explanation TEXT,
    FOREIGN KEY (requirement_id) REFERENCES requirements(requirement_id)
);

CREATE TABLE IF NOT EXISTS answer_scores (
    score_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    user_answer TEXT NOT NULL,
    score REAL NOT NULL,
    max_score REAL NOT NULL,
    loss_reason TEXT,
    weak_points TEXT,
    FOREIGN KEY (question_id) REFERENCES questions(question_id)
);
"""


def _new_id() -> str:
    """生成稳定 ID。参数无。返回 32 位 hex。"""
    return uuid.uuid4().hex


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """把 sqlite3.Row 转成普通 dict，供公开接口返回。

    参数:
        row: 查询结果行；无行时为 None。
    返回:
        dict 或 None。
    """
    if row is None:
        return None
    return dict(row)


class MemoryStore:
    """SQLite 记忆存储。同一 normalized_name 只保留一条岗位要求。"""

    def __init__(self, db_path: str | Path) -> None:
        """打开或创建数据库并初始化 6 张表。

        参数:
            db_path: SQLite 文件路径，或 ":memory:"。
        返回:
            None。副作用是建立连接并执行 schema。
        """
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        """创建 6 张业务表。可重复调用，已存在的表不会被破坏。

        参数:
            无。
        返回:
            None。
        """
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """关闭连接，避免文件库被占用导致后续会话打不开。

        参数:
            无。
        返回:
            None。
        """
        self._conn.close()

    def save_job(
        self,
        *,
        source: str,
        source_url: str,
        title: str,
        job_id: str | None = None,
        city: str | None = None,
        salary: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """按 job_id 写入或覆盖公开岗位。

        参数:
            source: 来源平台或渠道。
            source_url: 岗位页面 URL。
            title: 岗位标题。
            job_id: 稳定 ID；缺省则生成。
            city: 城市，可空。
            salary: 薪资文本，可空。
            description: 岗位描述，可空。
        返回:
            dict: {job_id, source, source_url, title, city, salary, description}
        """
        job_id = job_id or _new_id()
        self._conn.execute(
            """
            INSERT INTO jobs (job_id, source, source_url, title, city, salary, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                source=excluded.source,
                source_url=excluded.source_url,
                title=excluded.title,
                city=excluded.city,
                salary=excluded.salary,
                description=excluded.description
            """,
            (job_id, source, source_url, title, city, salary, description),
        )
        self._conn.commit()
        saved = self.get_job(job_id)
        assert saved is not None
        return saved

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """按稳定 job_id 读取岗位。

        参数:
            job_id: 岗位稳定 ID。
        返回:
            岗位 dict，不存在时为 None。
        """
        row = self._conn.execute(
            "SELECT job_id, source, source_url, title, city, salary, description "
            "FROM jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _row_dict(row)

    def save_requirement(
        self,
        name: str,
        *,
        requirement_id: str | None = None,
        normalized_name: str | None = None,
    ) -> dict[str, Any]:
        """按 normalized_name 全局去重写入岗位要求。

        已存在时返回原记录，不覆盖 name，也不改 requirement_id。

        参数:
            name: 展示名，如 "Python"。
            requirement_id: 稳定 ID；发生去重冲突时忽略。
            normalized_name: 去重键；缺省为 name 的大小写折叠并压缩空白。
        返回:
            dict: {requirement_id, name, normalized_name}
        """
        # 去重键忽略大小写和多余空白，避免 "Python" 与 "python" 变成两条原子要求
        key = normalized_name or " ".join(name.casefold().split())
        self._conn.execute(
            """
            INSERT INTO requirements (requirement_id, name, normalized_name)
            VALUES (?, ?, ?)
            ON CONFLICT(normalized_name) DO NOTHING
            """,
            (requirement_id or _new_id(), name, key),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT requirement_id, name, normalized_name FROM requirements "
            "WHERE normalized_name = ?",
            (key,),
        ).fetchone()
        found = _row_dict(row)
        assert found is not None
        return found

    def get_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        """按稳定 requirement_id 读取岗位要求。

        参数:
            requirement_id: 要求稳定 ID。
        返回:
            要求 dict，不存在时为 None。
        """
        row = self._conn.execute(
            "SELECT requirement_id, name, normalized_name FROM requirements "
            "WHERE requirement_id = ?",
            (requirement_id,),
        ).fetchone()
        return _row_dict(row)

    def link_job_requirement(
        self, job_id: str, requirement_id: str, evidence: str
    ) -> dict[str, Any]:
        """把岗位与要求做成多对多关联，并按岗位对保存 evidence。

        同一 (job_id, requirement_id) 再次写入时更新 evidence，避免重复行。

        参数:
            job_id: 已存在的岗位 ID。
            requirement_id: 已存在的要求 ID。
            evidence: 该岗位描述中支持这条要求的原文。
        返回:
            dict: {job_id, requirement_id, evidence}
        """
        self._conn.execute(
            """
            INSERT INTO job_requirements (job_id, requirement_id, evidence)
            VALUES (?, ?, ?)
            ON CONFLICT(job_id, requirement_id) DO UPDATE SET evidence=excluded.evidence
            """,
            (job_id, requirement_id, evidence),
        )
        self._conn.commit()
        return {
            "job_id": job_id,
            "requirement_id": requirement_id,
            "evidence": evidence,
        }

    def list_job_requirements(
        self,
        *,
        job_id: str | None = None,
        requirement_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """按岗位或要求列出关联及 evidence。

        参数:
            job_id: 按岗位过滤；可与 requirement_id 同时给。
            requirement_id: 按要求过滤。
        返回:
            list[dict]: 每项为 {job_id, requirement_id, evidence}。
        """
        if job_id is None and requirement_id is None:
            raise ValueError("job_id 或 requirement_id 必须提供其一")
        clauses = []
        params: list[str] = []
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        if requirement_id is not None:
            clauses.append("requirement_id = ?")
            params.append(requirement_id)
        sql = (
            "SELECT job_id, requirement_id, evidence FROM job_requirements WHERE "
            + " AND ".join(clauses)
        )
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def save_knowledge_chunk(
        self,
        *,
        requirement_id: str,
        source_url: str,
        title: str,
        content: str,
        evidence: str,
        chunk_id: str | None = None,
    ) -> dict[str, Any]:
        """按 chunk_id 写入一条学习资料切片。走整批事务入口，避免单条路径漏 evidence。

        参数:
            requirement_id: 所属岗位要求 ID。
            source_url: 资料来源 URL。
            title: 切片标题。
            content: 切片正文。
            evidence: 来源中支持该切片的原文。
            chunk_id: 稳定 ID；缺省则生成。
        返回:
            dict: {chunk_id, requirement_id, source_url, title, content, evidence}
        """
        item: dict[str, Any] = {
            "requirement_id": requirement_id,
            "source_url": source_url,
            "title": title,
            "content": content,
            "evidence": evidence,
        }
        if chunk_id is not None:
            item["chunk_id"] = chunk_id
        return self.save_knowledge_chunks([item])[0]

    def save_knowledge_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """在一个事务内写入整批切片。中途约束失败必须回滚，避免半批被复用。

        参数:
            chunks: 每项含 requirement_id、source_url、title、content、evidence；
                chunk_id 可选。
        返回:
            写入后的切片 dict 列表，顺序与输入一致。
        """
        saved_ids: list[str] = []
        with self._conn:
            for chunk in chunks:
                chunk_id = chunk.get("chunk_id") or _new_id()
                self._conn.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        chunk_id, requirement_id, source_url, title, content, evidence
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        requirement_id=excluded.requirement_id,
                        source_url=excluded.source_url,
                        title=excluded.title,
                        content=excluded.content,
                        evidence=excluded.evidence
                    """,
                    (
                        chunk_id,
                        chunk["requirement_id"],
                        chunk["source_url"],
                        chunk["title"],
                        chunk["content"],
                        chunk["evidence"],
                    ),
                )
                saved_ids.append(chunk_id)
        saved = []
        for cid in saved_ids:
            row = self.get_knowledge_chunk(cid)
            assert row is not None
            saved.append(row)
        return saved

    def get_knowledge_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """按稳定 chunk_id 读取知识切片。

        参数:
            chunk_id: 切片稳定 ID。
        返回:
            切片 dict，不存在时为 None。
        """
        row = self._conn.execute(
            "SELECT chunk_id, requirement_id, source_url, title, content, evidence "
            "FROM knowledge_chunks WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        return _row_dict(row)

    def list_knowledge_chunks(self, requirement_id: str) -> list[dict[str, Any]]:
        """按 requirement_id 列出知识切片。

        参数:
            requirement_id: 岗位要求 ID。
        返回:
            list[dict]，顺序为写入顺序。
        """
        rows = self._conn.execute(
            "SELECT chunk_id, requirement_id, source_url, title, content, evidence "
            "FROM knowledge_chunks WHERE requirement_id = ? ORDER BY rowid",
            (requirement_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_question(
        self,
        *,
        requirement_id: str,
        prompt: str,
        standard_answer: str,
        question_id: str | None = None,
        explanation: str | None = None,
    ) -> dict[str, Any]:
        """按 question_id 写入题目、标准答案和解析。

        参数:
            requirement_id: 所属岗位要求 ID。
            prompt: 题面。
            standard_answer: 标准答案。
            question_id: 稳定 ID；缺省则生成。
            explanation: 解析，可空。
        返回:
            dict: {question_id, requirement_id, prompt, standard_answer, explanation}
        """
        question_id = question_id or _new_id()
        self._conn.execute(
            """
            INSERT INTO questions (
                question_id, requirement_id, prompt, standard_answer, explanation
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                requirement_id=excluded.requirement_id,
                prompt=excluded.prompt,
                standard_answer=excluded.standard_answer,
                explanation=excluded.explanation
            """,
            (question_id, requirement_id, prompt, standard_answer, explanation),
        )
        self._conn.commit()
        saved = self.get_question(question_id)
        assert saved is not None
        return saved

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        """按稳定 question_id 回找题目。

        参数:
            question_id: 题目稳定 ID。
        返回:
            题目 dict，不存在时为 None。
        """
        row = self._conn.execute(
            "SELECT question_id, requirement_id, prompt, standard_answer, explanation "
            "FROM questions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        return _row_dict(row)

    def list_questions(self, requirement_id: str) -> list[dict[str, Any]]:
        """按 requirement_id 列出题目。

        参数:
            requirement_id: 岗位要求 ID。
        返回:
            list[dict]，顺序为写入顺序。
        """
        rows = self._conn.execute(
            "SELECT question_id, requirement_id, prompt, standard_answer, explanation "
            "FROM questions WHERE requirement_id = ? ORDER BY rowid",
            (requirement_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_answer_score(
        self,
        *,
        question_id: str,
        user_answer: str,
        score: float,
        max_score: float,
        score_id: str | None = None,
        loss_reason: str | None = None,
        weak_points: str | None = None,
    ) -> dict[str, Any]:
        """追加一条评分。同一 question_id 可写多次，不覆盖历史作答。

        参数:
            question_id: 已存在的题目 ID。
            user_answer: 用户答案。
            score: 得分。
            max_score: 满分。
            score_id: 稳定 ID；缺省则生成。
            loss_reason: 失分原因，可空。
            weak_points: 薄弱点文本，可空。
        返回:
            dict: {score_id, question_id, user_answer, score, max_score, loss_reason, weak_points}
        """
        score_id = score_id or _new_id()
        # 只用 INSERT：评分是作答历史，不能 REPLACE 掉同一题的旧记录
        self._conn.execute(
            """
            INSERT INTO answer_scores (
                score_id, question_id, user_answer, score, max_score, loss_reason, weak_points
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (score_id, question_id, user_answer, score, max_score, loss_reason, weak_points),
        )
        self._conn.commit()
        saved = self.get_answer_score(score_id)
        assert saved is not None
        return saved

    def get_answer_score(self, score_id: str) -> dict[str, Any] | None:
        """按稳定 score_id 读取评分。

        参数:
            score_id: 评分稳定 ID。
        返回:
            评分 dict，不存在时为 None。
        """
        row = self._conn.execute(
            "SELECT score_id, question_id, user_answer, score, max_score, loss_reason, weak_points "
            "FROM answer_scores WHERE score_id = ?",
            (score_id,),
        ).fetchone()
        return _row_dict(row)

    def list_answer_scores(self, question_id: str) -> list[dict[str, Any]]:
        """按 question_id 列出全部评分记录。

        参数:
            question_id: 题目 ID。
        返回:
            list[dict]，顺序为写入顺序。
        """
        rows = self._conn.execute(
            "SELECT score_id, question_id, user_answer, score, max_score, loss_reason, weak_points "
            "FROM answer_scores WHERE question_id = ? ORDER BY rowid",
            (question_id,),
        ).fetchall()
        return [dict(row) for row in rows]
