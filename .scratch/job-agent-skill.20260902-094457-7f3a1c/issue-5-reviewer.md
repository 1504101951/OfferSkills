# Role: Reviewer - Execution Issue: #5 - Harness: claude - Model: deepseek-v4-pro - Effort: max

独立审查工作区中的出题角色是否满足 https://github.com/1504101951/OfferSkills/issues/5。不得修改任何文件。

验收：按 requirement_id 或已有知识切片生成并保存题目、标准答案、解析；按 question_id 回找；缺少要求或资料时报告缺失 ID 且不写入；不隐式触发知识搜索；新会话恢复。重点检查 `question/`、`tests/test_question.py` 和 `SKILL.md`。运行 `python3.11 -m unittest discover -s tests -v`，只输出问题、证据、影响和建议。
