---
name: job-seeker
description: 按用户意图搜索并保存公开岗位与原子要求、检索带来源的学习资料、出题并评估答案，或对照岗位要求修改本地简历；角色无固定顺序，可跨会话按稳定 ID 复用 SQLite 记忆。
---

# 求职Agent Skill

本地单用户 Skill。同一个通用 Agent 按用户意图或显式指定加载角色提示词；搜索、总结、出题、评分和简历修改全部由模型完成。Python 只校验结构、做事务并读写 SQLite。不要临时写 Python，直接调用 `scripts/memory_tool.py`。

## 角色选择

先读用户请求，再加载对应提示词。用户点名某个角色时，以点名为准。五个角色没有固定执行顺序，也不要自己串成流水线。

| 用户意图 | 角色 | 提示词 |
| --- | --- | --- |
| 搜岗位、保存 JD、提炼岗位要求 | 岗位搜索 | [references/job-search.md](references/job-search.md) |
| 按岗位要求搜资料、保存知识切片 | 知识搜索 | [references/knowledge-search.md](references/knowledge-search.md) |
| 出题、生成练习 | 出题 | [references/question-writer.md](references/question-writer.md) |
| 批改、打分、看薄弱点 | 评分 | [references/answer-reviewer.md](references/answer-reviewer.md) |
| 按岗位要求改本地简历 | 简历修改 | [references/resume-editor.md](references/resume-editor.md) |

一次请求可只做其中一个角色。缺少前置记忆时，用 `get_*` / `list_*` 召回；仍缺失就报告稳定 ID 并停止，不要隐式切换到其他角色。

新会话默认数据库仍是 `~/.offerskills/jobseeker.db`。个人数据量小，先 `list_*` 再由模型判断，不要做向量检索。

## JSON 工具

每次启动脚本从 stdin 读**一个** JSON object，只向 stdout 写**一个** JSON object。不要传子命令、不要设环境变量覆盖库路径。

```bash
python3 scripts/memory_tool.py
```

默认数据库是 `~/.offerskills/jobseeker.db`。脚本会创建父目录；响应里的 `db_path` 是展开后的实际路径。请求里的 `db_path` 会被忽略。

### 成功

退出码 0。`result` 为该动作的返回值；按稳定 ID 查询不到时 `result` 为 missing 结构，不会写库。

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
| `save_jobs` | `jobs`：岗位列表 | 校验后写入岗位与原子要求；已有 `job_id` 复用快照，不覆盖 |
| `get_job` | `job_id` | 按稳定 ID 读岗位及其要求 |
| `list_jobs` | 无 | 列出全部岗位及其要求 |
| `list_requirements` | `job_id` 可省略 | 列出原子要求；给 `job_id` 时只返回该岗位关联要求及 evidence |
| `save_chunks` | `chunks`：切片列表 | 校验后写入知识切片；不搜索、不自动复用 |
| `get_chunk` | `chunk_id` | 按稳定 ID 读切片 |
| `list_chunks` | `requirement_id` 可省略 | 列出切片；可按岗位要求过滤 |
| `save_questions` | `drafts`：题目草稿 | 校验后写入题目；同一 `chunk_id` 覆盖原题 |
| `get_question` | `question_id` | 按稳定 ID 读题目 |
| `list_questions` | `requirement_id` 可省略 | 列出题目；可按岗位要求过滤 |
| `save_score` | `question_id`、`result` | 校验后追加一条评分，不改 Agent 给的分 |
| `get_score` | `score_id` | 按稳定 ID 读评分 |
| `list_scores` | `question_id` 可省略 | 列出评分；可按题目过滤 |

未知 `action` 或非法 JSON 立即失败，不写库。没有 `search_knowledge`，知识写入只用 `save_chunks`。

### 示例

以下示例中的 `requirement-id`、`chunk-id`、`q-chunk-id`、`score-id` 是占位符。串联调用时必须从前一步响应或 `list_*` 复制真实 ID，不要原样提交占位符。

保存岗位：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_jobs", "jobs": [{"job_id": "job-backend", "source": "web", "source_url": "https://example.com/jobs/backend", "title": "Backend Engineer", "city": "Shanghai", "salary": "30k-40k", "requirements": [{"name": "Python", "evidence": "熟悉 Python"}, {"name": "SQL", "evidence": "3 年 SQL 经验"}]}]}
EOF
```

按 `job_id` 回找，或列出岗位与要求：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_job", "job_id": "job-backend"}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "list_jobs"}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "list_requirements", "job_id": "job-backend"}
EOF
```

保存知识切片，再按 `chunk_id` 或 `requirement_id` 召回：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_chunks", "chunks": [{"requirement_id": "requirement-id", "title": "INNER JOIN", "content": "INNER JOIN 只返回两表键匹配的行。", "source_url": "https://example.com/sql-join", "evidence": "INNER JOIN produces a result set that includes only matching rows."}]}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_chunk", "chunk_id": "chunk-id"}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "list_chunks", "requirement_id": "requirement-id"}
EOF
```

保存并按 `question_id` 回找题目：

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "save_questions", "drafts": [{"chunk_id": "chunk-id", "prompt": "INNER JOIN 返回哪些行？", "standard_answer": "只返回两表键匹配的行。", "explanation": "无匹配行会被丢弃，与 LEFT JOIN 保留左表全部行不同。"}]}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_question", "question_id": "q-chunk-id"}
EOF
```

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "list_questions", "requirement_id": "requirement-id"}
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

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "list_scores", "question_id": "q-chunk-id"}
EOF
```
