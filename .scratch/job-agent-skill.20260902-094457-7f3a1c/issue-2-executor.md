# 派发上下文 - Role: Executor - Execution Issue: #2 - Issue URL: https://github.com/1504101951/OfferSkills/issues/2 - Issue Updated At: 2026-09-02 - Parent Spec: https://github.com/1504101951/OfferSkills/issues/1 - Harness: grok - Model: grok-4.6 - Effort: high

## 目标

实现求职Agent Skill 的共享 SQLite 记忆模块，覆盖 6 张表及最小读写接口。

## 验收标准

- 数据库可初始化并创建 jobs、requirements、job_requirements、knowledge_chunks、questions、answer_scores。
- 同一 normalized_name 的岗位要求只保存一条。
- 一个要求可关联多个岗位并保留 evidence。
- 资料、题目、评分可按稳定 ID 写入和读取；同一道题可有多次评分记录。
- 提供输入→输出和状态变化测试。

## 允许范围

仅修改存储模块、数据库初始化和对应测试；可创建实现所需的最小目录结构。

## 非目标

不实现岗位搜索、知识搜索、出题、打分角色；不引入独立向量数据库；不实现 CLI 或 Web 服务。

## 架构约束

使用 SQLite 作为唯一持久化存储。岗位要求全局去重，通过 job_requirements 表与岗位建立多对多关系。知识切片、题目关联 requirement_id；评分包含 question_id、user_answer、score、max_score、loss_reason、weak_points。

## 已验收依赖

无。

## 当前证据

首次执行，暂无。

## 必须验证

- 使用项目实际测试命令；若无既有测试框架，提供最小可运行的 Python 自检。

## 角色约束

只修改允许范围。必须越界时停止修改，说明原因和所需决策。

## 返回要求

重述 Execution Issue #2；列出实际修改文件、验证命令和结果、实现摘要与剩余风险。
