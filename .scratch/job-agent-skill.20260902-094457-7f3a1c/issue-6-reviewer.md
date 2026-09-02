# Role: Reviewer - Execution Issue: #6 - Harness: claude - Model: deepseek-v4-pro - Effort: max

独立审查打分角色是否满足 https://github.com/1504101951/OfferSkills/issues/6。不得修改任何文件。

验收：按 question_id 读取题目并保存 user_answer、score、max_score、loss_reason、weak_points；同题多次作答不覆盖；缺失题目不写入；分数边界校验；新会话读取历史评分和薄弱点。重点检查评分角色、对应测试与 SKILL.md。运行 `python3.11 -m unittest discover -s tests -v`，只输出问题、证据、影响和建议。
