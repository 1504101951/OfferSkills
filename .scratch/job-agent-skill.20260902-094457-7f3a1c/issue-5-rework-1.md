# Role: Executor - Execution Issue: #5 - Rework 1 - Harness: grok - Model: grok-4.6 - Effort: high

修复出题角色把知识正文复制为标准答案和解析的问题。仅修改 `question/`、`tests/test_question.py`、`SKILL.md`。

架构要求：通用 Agent 读取 requirement_id 对应知识切片后生成结构化题目草稿；QuestionRole 负责校验并保存，不自行用模板伪造内容。`generate` 接收草稿列表，每项至少包含关联 chunk_id、prompt、standard_answer、explanation；三段文本必须非空，standard_answer 与 explanation 不得完全相同。先校验所有 chunk_id 和全部草稿，再写入，任一无效则整批不写入。保存后仍可按 question_id 跨会话回找。SKILL.md 给出 Agent 生成草稿后调用的明确示例。

更新测试覆盖：答案与解析不同；缺失/无效草稿整批不写入；原有缺失 ID、新会话和不隐式知识搜索行为继续通过。运行 `python3.11 -m unittest discover -s tests -v`。
