---
name: job-seeker
description: 按岗位要求搜索并保存带来源的公开学习资料，基于已有知识切片生成题目并评估用户答案，支持跨会话按 requirement_id 与 question_id 复用。
---

# 求职Agent Skill

本地单用户 Skill。角色通过稳定 ID 读写共享 SQLite（`memory.MemoryStore`），不隐式触发其他角色。

## 知识搜索角色

按 `requirement_id` 收集公开学习资料，切成知识切片后写入记忆。每个切片含 `requirement_id`、标题、正文、`source_url`。已有切片时直接复用，不重新搜索。

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

尚无切片时：用公开网页搜索该岗位要求名称（`store.get_requirement(requirement_id)["name"]`）对应的教程或文档，抓取正文后再次调用：

```python
result = role.search(
    requirement_id,
    documents=[
        {
            "title": "文档标题",
            "content": "段落一。\n\n段落二。",
            "source_url": "https://example.com/lesson",
        }
    ],
)
```

空行分段，每段单独成切片，共用该文档的 `title` 与 `source_url`。缺少 `source_url` 会失败。不要接入搜索聚合层或向量数据库。

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
