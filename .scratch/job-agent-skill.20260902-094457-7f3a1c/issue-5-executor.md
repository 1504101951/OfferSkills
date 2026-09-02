# Role: Executor - Execution Issue: #5 - Harness: grok - Model: grok-4.6 - Effort: high

实现并核验出题角色：按 requirement_id 或已有 knowledge_chunk 生成题目、标准答案和解析，保存后支持 question_id 查询。工作区已有未提交的 `question/` 与测试草稿，可复用、修正，不得修改 `memory/`、`job_search/`、`knowledge_search/`。

验收：缺少 requirement_id 或 chunk_id 时报告稳定 ID 且不写入；不隐式触发知识搜索；新会话可按 question_id 回找完整题目。将出题角色调用说明补入 `SKILL.md`。运行 `python3.11 -m unittest discover -s tests -v`。只修改 `question/`、`tests/test_question.py`、`SKILL.md`。
