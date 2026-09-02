# 派发上下文 - Role: Executor - Execution Issue: #3 - Issue URL: https://github.com/1504101951/OfferSkills/issues/3 - Parent Spec: https://github.com/1504101951/OfferSkills/issues/1 - Harness: grok - Model: grok-4.6 - Effort: high

## 目标

实现岗位搜索角色：搜索全网公开岗位、提取原子岗位要求，并写入共享 SQLite 记忆。

## 验收标准

- 保存岗位的 job_id、source、source_url、salary、title、city 和原始描述。
- 从岗位描述提取原子岗位要求，按 normalized_name 去重并建立 job_requirements 关联，保留 evidence。
- 新会话可按 job_id 读取岗位与要求。

## 允许范围

仅修改岗位搜索角色、必要的 Skill 说明和对应测试；复用 `memory.MemoryStore`，不改存储模块。

## 非目标

不实现知识搜索、出题、打分；不实现特定招聘平台适配器或搜索聚合层。

## 已验收依赖

SQLite 存储模块位于 `memory/`，接口以现有实现为准。

## 必须验证

`python3.11 -m unittest discover -s tests -v`

## 角色约束

只修改允许范围；发现存储接口不足时停止并说明，不修改 `memory/`。

## 返回要求

重述 Execution Issue #3，列出修改文件、验证命令和结果、实现摘要与剩余风险。
