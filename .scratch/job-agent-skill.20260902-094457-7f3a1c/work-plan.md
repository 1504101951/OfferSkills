# 求职Agent Skill

- Spec Issue: https://github.com/1504101951/OfferSkills/issues/1
- Architecture: 可被通用 Agent 调用的 Skill；四个可独立调用的角色共享 SQLite 记忆。角色为岗位搜索、知识搜索、出题、打分。岗位要求全局去重，通过 job_requirements 表与公开岗位建立多对多关系。

| 执行 Issue | 阻塞于 | 状态 | Executor 会话 | Reviewer 会话 | 返工次数 | 验收证据摘要 |
| --- | --- | --- | --- | --- | --- | --- |
| https://github.com/1504101951/OfferSkills/issues/2 | 无 | accepted | grok session `dfdd48f1-648c-4943-9485-74e2b583b087` | claude session `e99c251c-2e61-4ec1-b3cb-8307529cdbef` | 0 | `unittest`: 7/7；Review 核验外键、唯一约束、持久化重连、多次评分均通过 |
| https://github.com/1504101951/OfferSkills/issues/3 | #2 | blocked | grok session `2b372421-ce21-4bf6-a324-c20e3483221c`；返工 `5f84183b-5537-47df-ac9d-ccd0b038f5d8`、`c22379e0-68c5-4baa-ac15-893bf7537de0` | claude session `8a5fd272-f70f-413c-a572-76108407945b` | 2 | 29/29；小数经验与同行标题提取仍未通过最终 Review |
| https://github.com/1504101951/OfferSkills/issues/4 | #2 | accepted | grok session `9b251736-aacb-447a-90ab-810724341fc6`；返工 `4fbb8a12-faad-4842-b06e-dd4b90c39494` | claude session `816af4ff-1e2d-457b-a70d-f0d6749ca4eb` | 1 | `unittest`: 20/20；批量校验原子性回归通过 |
| https://github.com/1504101951/OfferSkills/issues/5 | #2、#4 | accepted | grok session `eb5c9f99-59d9-4827-910f-0cba2d225d72`；返工 `52707613-a74b-4c8f-95df-e179ddb9fb26` | claude session `9a5ecbe2-a695-447c-abac-1e688171cd97` | 1 | `unittest`: 32/32；Agent 草稿与解析独立，跨会话回找通过 |
| https://github.com/1504101951/OfferSkills/issues/6 | #2、#5 | accepted | grok session `69c7455b-1eb7-447a-b5ca-5c9e8ebddab4`；返工 `6a15a275-8764-4214-8a43-40135e080aa3` | claude session `faae62b3-8b0b-432f-bc34-c88430536c18` | 1 | `unittest`: 42/42；有限分数边界、多次评分、跨会话查询通过 |

## 验收边界

1. Skill 能独立调用岗位搜索、知识搜索、出题、打分四个角色。
2. SQLite 包含 jobs、requirements、job_requirements、knowledge_chunks、questions、answer_scores 六张表。
3. 岗位要求按 normalized_name 全局去重；同一要求可关联多个公开岗位，并保留 evidence。
4. 知识切片和题目关联 requirement_id；题目可按 question_id 回找。
5. 评分记录包含 question_id、user_answer、score、max_score、loss_reason、weak_points。
6. 资料保存来源 URL；新会话可按稳定 ID 读取历史记忆。
7. 不实现自动投递简历或自动与 HR 沟通。
