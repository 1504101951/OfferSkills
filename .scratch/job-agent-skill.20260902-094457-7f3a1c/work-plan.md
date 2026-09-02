# 求职Agent Skill

- Spec Issue: 待发布
- Architecture: 可被通用 Agent 调用的 Skill；四个可独立调用的角色共享 SQLite 记忆。角色为岗位搜索、知识搜索、出题、打分。岗位要求全局去重，通过 job_requirements 表与公开岗位建立多对多关系。

| 执行 Issue | 阻塞于 | 状态 | Executor 会话 | Reviewer 会话 | 返工次数 | 验收证据摘要 |
| --- | --- | --- | --- | --- | --- | --- |

## 验收边界

1. Skill 能独立调用岗位搜索、知识搜索、出题、打分四个角色。
2. SQLite 包含 jobs、requirements、job_requirements、knowledge_chunks、questions、answer_scores 六张表。
3. 岗位要求按 normalized_name 全局去重；同一要求可关联多个公开岗位，并保留 evidence。
4. 知识切片和题目关联 requirement_id；题目可按 question_id 回找。
5. 评分记录包含 question_id、user_answer、score、max_score、loss_reason、weak_points。
6. 资料保存来源 URL；新会话可按稳定 ID 读取历史记忆。
7. 不实现自动投递简历或自动与 HR 沟通。
