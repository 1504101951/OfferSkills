---
name: job-seeker
description: 按岗位要求搜索并保存带来源的公开学习资料，支持跨会话按 requirement_id 复用知识切片。
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
