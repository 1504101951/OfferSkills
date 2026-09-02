---
name: job-seeker
description: 保存公开岗位与原子岗位要求，按岗位要求搜索并保存带来源的公开学习资料，基于已有知识切片生成题目并评估用户答案，支持跨会话按稳定 ID 复用。
---

# 求职Agent Skill

本地单用户 Skill。角色通过稳定 ID 读写共享 SQLite（`memory.MemoryStore`），不隐式触发其他角色。Agent 不要临时写 Python，直接调用 `scripts/memory_tool.py`。

## JSON 工具

每次启动脚本从 stdin 读**一个** JSON object，只向 stdout 写**一个** JSON object。不要传子命令、不要设环境变量覆盖库路径。

```bash
python3 scripts/memory_tool.py
```

默认数据库是 `~/.offerskills/jobseeker.db`。脚本会创建父目录；响应里的 `db_path` 是展开后的实际路径。请求里的 `db_path` 会被忽略。

### 成功

退出码 0。`result` 为对应角色或查询的返回值；查询不到稳定 ID 时 `result` 为角色风格的 missing 结构，不会写库。

```json
{"ok": true, "action": "get_job", "db_path": "/home/user/.offerskills/jobseeker.db", "result": {"missing": "job_id", "job_id": "job-x"}}
```

### 失败

退出码非 0。`error` 可机器判断：`invalid_json`、`unknown_action`、`invalid_request`、`invalid_input`、`internal`。stdout 仍是 JSON，不会混入日志或 traceback。

```json
{"ok": false, "error": "unknown_action", "message": "未知动作: 'nope'", "db_path": "/home/user/.offerskills/jobseeker.db"}
```

### 动作

| action | 字段 | 行为 |
| --- | --- | --- |
| `save_jobs` | `jobs`：岗位列表 | `JobSearchRole.search` |
| `get_job` | `job_id` | `JobSearchRole.get` |
| `search_knowledge` | `requirement_id`；`chunks` 可省略 | `KnowledgeSearchRole.search`；省略 `chunks` 时复用已有切片 |
| `get_chunk` | `chunk_id` | 按稳定 ID 读切片；不存在时 `{"missing": "chunk_id", "chunk_id": ...}` |
| `save_questions` | `drafts`；`requirement_id` 可省略 | `QuestionRole.generate` |
| `get_question` | `question_id` | `QuestionRole.get` |
| `save_score` | `question_id`、`result` | `ScoringRole.score` |
| `get_score` | `score_id` | 按稳定 ID 读评分；不存在时 `{"missing": "score_id", "score_id": ...}` |

未知 `action` 或非法 JSON 立即失败，不写库。

### 示例

以下示例中的 `requirement-id`、`chunk-id`、`q-chunk-id`、`score-id` 是占位符。串联调用时必须从前一步响应复制真实 ID，不要原样提交占位符。

保存岗位：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_jobs", "jobs": [{"job_id": "job-backend", "source": "web", "source_url": "https://example.com/jobs/backend", "title": "Backend Engineer", "city": "Shanghai", "salary": "30k-40k", "requirements": [{"name": "Python", "evidence": "熟悉 Python"}, {"name": "SQL", "evidence": "3 年 SQL 经验"}]}]}
EOF
```

按 `job_id` 回找：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_job", "job_id": "job-backend"}
EOF
```

按 `requirement_id` 保存或复用知识，再按 `chunk_id` 读切片：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "search_knowledge", "requirement_id": "requirement-id", "chunks": [{"requirement_id": "requirement-id", "title": "INNER JOIN", "content": "INNER JOIN 只返回两表键匹配的行。", "source_url": "https://example.com/sql-join", "evidence": "INNER JOIN produces a result set that includes only matching rows."}]}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "search_knowledge", "requirement_id": "requirement-id"}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_chunk", "chunk_id": "chunk-id"}
EOF
```

保存并按 `question_id` 回找题目：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_questions", "requirement_id": "requirement-id", "drafts": [{"chunk_id": "chunk-id", "prompt": "INNER JOIN 返回哪些行？", "standard_answer": "只返回两表键匹配的行。", "explanation": "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。"}]}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_question", "question_id": "q-chunk-id"}
EOF
```

保存并按 `score_id` 回找评分：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_score", "question_id": "q-chunk-id", "result": {"user_answer": "返回笛卡尔积。", "score": 2, "max_score": 10, "loss_reason": "把 JOIN 理解成了叉乘。", "weak_points": "JOIN 与笛卡尔积的区别"}}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_score", "score_id": "score-id"}
EOF
```

## 岗位搜索角色

通用 Agent 全网搜索并理解公开岗位后输出结构化岗位与原子要求；岗位搜索角色只校验并保存，不解析岗位描述，也不用正则或分隔符推断要求。

每条岗位至少含 `source`、`source_url`、`title`，以及 `requirements` 列表。`job_id`、`city`、`salary` 可空。每条原子要求至少含非空 `name` 与原文 `evidence`。先校验整批岗位与要求，再写入；任一无效则整批不写入。同一 `normalized_name` 只保留一条 `requirements` 记录，各岗位分别保存 `job_requirements` 与 evidence。

### 调用

```python
from memory import MemoryStore
from job_search import JobSearchRole

store = MemoryStore("jobseeker.db")
role = JobSearchRole(store)
result = role.search(
    [
        {
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
    ]
)
```

成功时使用 `result["jobs"]`。已保存或本批重复的 `job_id` 再次传入时，该项 `reused` 为 true，使用已保存/首次快照，不覆盖字段、不追加要求。当前输入仍须完整合法；任一无效则整批不写入。

保存后按稳定 ID 回找岗位及其要求：

```python
job = role.get(job_id)
```

岗位不存在时返回 `{"missing": "job_id", "job_id": ...}`，停止，不要去搜知识或出题。

## 知识搜索角色

通用 Agent 阅读公开资料并输出语义完整的结构化知识切片；知识搜索角色只校验并保存，不搜索网页、不总结、不按空行或字数切分。

每条切片至少含非空 `requirement_id`、`title`、`content`、`source_url`、`evidence`；`requirement_id` 须与 `search` 外层参数一致。先校验整批切片，再在一个事务中写入；任一无效则整批不写入。已有切片时直接复用，不重新搜索。

### 调用

```python
from memory import MemoryStore
from knowledge_search import KnowledgeSearchRole

store = MemoryStore("jobseeker.db")
role = KnowledgeSearchRole(store)
result = role.search(requirement_id)
```

`requirement_id` 不在记忆中时，返回 `{"missing": "requirement_id", "requirement_id": ...}`，停止，不要去搜岗位或出题。

已有切片时，`result["reused"]` 为 true，直接使用 `result["chunks"]`。

尚无切片时，用岗位要求名称（`store.get_requirement(requirement_id)["name"]`）检索公开教程或文档，理解后切成语义完整的切片，再次调用：

```python
result = role.search(
    requirement_id,
    chunks=[
        {
            "requirement_id": requirement_id,
            "title": "INNER JOIN",
            "content": "INNER JOIN 只返回两表键匹配的行。",
            "source_url": "https://example.com/sql-join",
            "evidence": "INNER JOIN produces a result set that includes only matching rows.",
        }
    ],
)
```

成功时使用 `result["chunks"]`。`content` 保持 Agent 给出的语义边界；缺少 `requirement_id`、`source_url` 或 `evidence` 会失败。不要接入搜索聚合层或向量数据库。

## 出题角色

通用 Agent 读取 `requirement_id` 对应知识切片后生成结构化题目草稿；出题角色只校验并保存，不把切片正文复制为标准答案或解析，也不隐式搜索学习资料。

每份草稿至少含关联 `chunk_id`、`prompt`、`standard_answer`、`explanation`。三段文本必须非空，且标准答案与解析不得完全相同。先校验全部 `chunk_id` 与全部草稿，再写入；任一无效则整批不写入。

### 调用

```python
from memory import MemoryStore
from question import QuestionRole

store = MemoryStore("jobseeker.db")
role = QuestionRole(store)
```

`requirement_id` 不在记忆中时，返回 `{"missing": "requirement_id", "requirement_id": ...}`，停止，不要去搜岗位：

```python
result = role.generate(requirement_id)
```

岗位要求在、知识切片不在时，返回 `{"missing": "chunk_id", "requirement_id": ...}`，停止，不要去搜资料或调用知识搜索角色。

要求与切片都在时，Agent 先读切片再生成草稿，然后交给出题角色：

```python
chunks = store.list_knowledge_chunks(requirement_id)
result = role.generate(
    requirement_id,
    drafts=[
        {
            "chunk_id": chunks[0]["chunk_id"],
            "prompt": "INNER JOIN 返回哪些行？",
            "standard_answer": "只返回两表键匹配的行。",
            "explanation": "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。",
        }
    ],
)
```

成功时使用 `result["questions"]`。同一知识切片对应同一道题，重复调用会覆盖题面，不会追加重复练习项。

已有切片也可只传草稿，不必再传 `requirement_id`：

```python
result = role.generate(
    drafts=[
        {
            "chunk_id": "chunk-id",
            "prompt": "GROUP BY 做什么？",
            "standard_answer": "按键把行聚合成组。",
            "explanation": "聚合函数作用在每一组，而不是整张表。",
        }
    ]
)
```

任一草稿的 `chunk_id` 不存在时，返回 `{"missing": "chunk_id", "chunk_ids": [...]}`，不写入任何题目。草稿缺字段、文本为空、或标准答案与解析完全相同，同样整批不写入。

保存后按稳定 ID 回找完整题目（题面、标准答案、解析、`requirement_id`）：

```python
question = role.get(question_id)
```

题目不存在时返回 `{"missing": "question_id", "question_id": ...}`。

## 打分角色

通用 Agent 按 `question_id` 读取题目与标准答案后生成结构化评分结果；打分角色只校验并保存，不对照标准答案改分，也不隐式出题。

评分结果至少含 `user_answer`、`score`、`max_score`。须满足 `0 <= score <= max_score` 且 `max_score > 0`。`loss_reason` 与 `weak_points` 为可空文本，不要传列表。同一题可多次作答，每次追加一条记录。

### 调用

```python
from memory import MemoryStore
from scoring import ScoringRole

store = MemoryStore("jobseeker.db")
role = ScoringRole(store)
```

`question_id` 不在记忆中时，返回 `{"missing": "question_id", "question_id": ...}`，停止，不要去出题：

```python
result = role.score("q-missing", {"user_answer": "不知道", "score": 0, "max_score": 10})
```

题目在时，Agent 先读题再评分：

```python
question = role.get(question_id)
result = role.score(
    question_id,
    {
        "user_answer": "返回笛卡尔积。",
        "score": 2,
        "max_score": 10,
        "loss_reason": "把 JOIN 理解成了叉乘。",
        "weak_points": "JOIN 与笛卡尔积的区别",
    },
)
```

成功时使用返回记录的 `score_id`、`user_answer`、`score`、`max_score`、`loss_reason`、`weak_points`。新会话再 `get` 同一 `question_id`，`question["scores"]` 即作答历史，每项含薄弱点。
