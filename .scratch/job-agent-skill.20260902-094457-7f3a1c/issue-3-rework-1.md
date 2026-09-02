# Role: Executor - Execution Issue: #3 - Rework 1 - Harness: grok - Model: grok-4.6 - Effort: high

修复岗位搜索角色的重复 job_id 数据漂移，仅修改 `job_search/`、相关 Skill 说明和对应测试，不修改 `memory/`。

当前问题：同一 job_id 再次传入不同描述时，岗位字段被覆盖，但旧 job_requirements 不会删除，导致描述与要求不一致。

要求：将已保存岗位视为不可变快照；调用输入包含已存在 job_id 时，直接返回数据库中的岗位与要求，并标记 reused，不覆盖岗位字段、不新增或删除要求关联。新增最小回归测试：首次 Python/SQL，第二次同 job_id 使用 Redis 描述，结果和数据库仍只有首次岗位字段及 Python/SQL 要求。运行 `python3.11 -m unittest discover -s tests -v`。
