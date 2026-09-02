# OfferSkills

OfferSkills 是一个面向求职准备的 Agent Skill。同一个通用 Agent 按用户意图或显式指定加载提示词角色：岗位搜索、知识搜索、出题、评分、简历修改。岗位、要求、学习资料、题目和评分保存在本地 SQLite 中，不同会话可以通过稳定 ID 继续使用已有记忆。

## 功能

- 搜索并保存公开岗位和原子岗位要求。
- 按岗位要求保存带来源证据的语义知识切片。
- 根据知识切片生成题目，并按 `question_id` 回找。
- 保存用户答案、得分、满分、失分原因和薄弱点。
- 对照已保存岗位要求修改用户指定的本地简历；不把简历写入数据库。
- 通过一个 JSON stdin/stdout 脚本供通用 Agent 调用。

五个角色没有固定执行顺序。Agent 负责搜索、理解、格式化、出题、评分和改简历；Python 只负责结构校验、事务写入和 SQLite 查询。

## 环境要求

- Git
- Python 3.11 或更高版本（`python3 --version` 必须显示 3.11+）
- Codex（仅在作为 Codex Skill 使用时需要）

项目只使用 Python 标准库，不需要执行 `pip install`。

## 安装为 Codex Skill

将仓库克隆到 Codex 的个人 Skills 目录：

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/1504101951/OfferSkills.git "$HOME/.agents/skills/job-seeker"
```

运行测试确认安装完整：

```bash
cd "$HOME/.agents/skills/job-seeker"
python3 -m unittest discover -s tests -v
```

Codex 会自动检测 Skill；如果没有出现，重启 Codex。之后可以显式调用：

```text
$job-seeker 搜索后端 Python 岗位，提炼岗位要求并保存。
```

也可以分会话调用不同角色，例如先保存岗位和知识，之后再要求 `$job-seeker` 根据已有 `requirement_id` 出题、根据 `question_id` 打分，或对照已保存岗位修改本地简历。用户也可以直接点名角色。

## 更新

```bash
cd "$HOME/.agents/skills/job-seeker"
git pull --ff-only
python3 -m unittest discover -s tests -v
```

数据库不在安装目录内，更新代码不会覆盖已有记忆。

## 仅使用 JSON 工具

不需要安装到 Codex 时，可以克隆到任意目录并直接运行内部工具：

```bash
git clone https://github.com/1504101951/OfferSkills.git
cd OfferSkills
python3 scripts/memory_tool.py
```

工具每次从 stdin 读取一个 JSON object，并只向 stdout 输出一个 JSON object。默认数据库固定为：

```text
~/.offerskills/jobseeker.db
```

脚本首次收到受支持的 `action` 时会自动创建数据库目录和文件；即使该动作随后因业务字段无效而失败，空数据库也可能已经创建。

### 保存岗位

```bash
python3 scripts/memory_tool.py <<'EOF'
{
  "action": "save_jobs",
  "jobs": [
    {
      "job_id": "job-backend",
      "source": "web",
      "source_url": "https://example.com/jobs/backend",
      "title": "Backend Engineer",
      "city": "Shanghai",
      "salary": "30k-40k",
      "requirements": [
        {"name": "Python", "evidence": "熟悉 Python"},
        {"name": "SQL", "evidence": "3 年 SQL 经验"}
      ]
    }
  ]
}
EOF
```

响应中的 `result.jobs[].requirements[].requirement_id` 是后续知识搜索使用的真实要求 ID。题目和评分同理：从前一步响应或 `list_*` 复制 `chunk_id`、`question_id`、`score_id`，不要原样使用文档中的 `*-id` 占位符。

### 查询岗位

```bash
python3 scripts/memory_tool.py <<'EOF'
{"action": "get_job", "job_id": "job-backend"}
EOF
```

其余动作和字段见 [SKILL.md](SKILL.md) 的“JSON 工具”章节。当前支持：

| 数据 | 保存动作 | 按 ID 查询 | 列表召回 |
| --- | --- | --- | --- |
| 岗位 | `save_jobs` | `get_job` | `list_jobs` |
| 岗位要求 | （随 `save_jobs` 写入） |  | `list_requirements` |
| 知识切片 | `save_chunks` | `get_chunk` | `list_chunks` |
| 题目 | `save_questions` | `get_question` | `list_questions` |
| 评分 | `save_score` | `get_score` | `list_scores` |

没有 `search_knowledge`。知识写入只用 `save_chunks`；是否复用已有切片由 Agent 先 `list_chunks` 再决定。

简历修改角色只使用上表中的只读动作，由 Harness 读取用户指定的本地文件，不限制格式，也不把简历写入数据库。

## 数据模型

- `jobs`：原始岗位。
- `requirements`：全局去重的原子岗位要求。
- `job_requirements`：岗位与要求的多对多关系及原文证据。
- `knowledge_chunks`：关联 `requirement_id` 的知识切片。
- `questions`：关联岗位要求和知识切片生成的题目。
- `answer_scores`：关联 `question_id` 的用户答案与评分。

同一个要求可以关联多个岗位。例如三个岗位都要求 Python 时，`requirements` 只保存一条 Python，`job_requirements` 保存三条岗位关系。

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
```

项目使用 `unittest`，不使用 pytest。完整的 Agent 调用契约见 [SKILL.md](SKILL.md)。五个角色的职责、结构化结果和数据库边界见 [references/](references/)。

Codex 的本地 Skill 目录和调用方式以 [OpenAI 官方 Skills 文档](https://developers.openai.com/codex/skills/) 为准。
