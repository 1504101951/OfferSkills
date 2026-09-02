# Role: Executor - Execution Issue: #6 - Harness: grok - Model: grok-4.6 - Effort: high

实现打分角色：按 question_id 读取题目与标准答案，由通用 Agent 提供结构化评分结果，角色校验并保存 user_answer、score、max_score、loss_reason、weak_points；同一道题允许多次作答，新会话可查询历史评分与薄弱点。

只修改新的评分角色目录、对应测试和 `SKILL.md`；复用 `memory.MemoryStore`，不得修改其他角色或存储模块。缺少 question_id 时报告稳定 ID 且不写入；要求 0 <= score <= max_score 且 max_score > 0；失分原因和薄弱点使用当前存储支持的文本结构。运行 `python3.11 -m unittest discover -s tests -v`。
