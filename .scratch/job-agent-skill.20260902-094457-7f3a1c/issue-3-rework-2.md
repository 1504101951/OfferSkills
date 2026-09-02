# Role: Executor - Execution Issue: #3 - Rework 2 - Harness: grok - Model: grok-4.6 - Effort: high

完成岗位搜索角色最后一轮返工，仅修改 `job_search/`、相关 Skill 说明和测试，不修改 `memory/`。

必须同时修复：

1. 同一次 `search()` 输入中出现相同 job_id：仅首次条目形成不可变快照，后续同 ID 条目返回首次已准备/已保存结果并标记 reused，不覆盖字段、不追加要求。
2. 单行多要求拆分：按 `、`、中文/英文逗号、中文/英文分号拆分，清理空白和句末标点；例如“熟悉 Python、SQL、Redis”必须得到 Python、SQL、Redis 三条原子要求。只做确定性启发式，不引入 NLP 依赖。

添加两个最小回归测试覆盖上述行为。运行 `python3.11 -m unittest discover -s tests -v`。不得修改其他角色。
