# Role: Reviewer - Execution Issue: #3 - Harness: claude - Model: deepseek-v4-pro - Effort: max

独立审查工作区中的岗位搜索角色是否满足 https://github.com/1504101951/OfferSkills/issues/3。不得修改代码、测试、配置或文档。

验收：保存公开岗位及来源；提取原子岗位要求并去重；建立岗位-要求多对多关联并保留 evidence；新会话可按 job_id 恢复。重点检查岗位搜索角色、相关 Skill 说明和测试。运行 `python3.11 -m unittest discover -s tests -v`。只输出问题、证据、影响和建议。
