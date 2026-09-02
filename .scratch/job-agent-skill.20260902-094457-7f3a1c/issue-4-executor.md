# 派发上下文 - Role: Executor - Execution Issue: #4 - Issue URL: https://github.com/1504101951/OfferSkills/issues/4 - Parent Spec: https://github.com/1504101951/OfferSkills/issues/1 - Harness: grok - Model: grok-4.6 - Effort: high

## 目标

实现知识搜索角色：按 requirement_id 搜索公开学习资料、切分知识片段、保存来源 URL，并优先复用已有资料。

## 验收标准

- 可按 requirement_id 搜索并保存知识切片。
- 每个切片包含 requirement_id、标题、正文和 source_url。
- 重复请求可读取已保存资料；新会话可按 requirement_id 恢复。
- 缺少岗位要求时报告缺失 ID 且不写入。

## 允许范围

仅修改知识搜索角色、必要的 Skill 说明和对应测试；复用 `memory.MemoryStore`，不改存储模块。

## 非目标

不实现岗位搜索、出题、打分；不引入独立向量数据库或搜索聚合层。

## 已验收依赖

SQLite 存储模块位于 `memory/`，接口以现有实现为准。

## 必须验证

`python3.11 -m unittest discover -s tests -v`

## 角色约束

只修改允许范围；发现存储接口不足时停止并说明，不修改 `memory/`。

## 返回要求

重述 Execution Issue #4，列出修改文件、验证命令和结果、实现摘要与剩余风险。
