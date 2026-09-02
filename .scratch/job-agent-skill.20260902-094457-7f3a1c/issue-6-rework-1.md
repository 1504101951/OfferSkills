# Role: Executor - Execution Issue: #6 - Rework 1 - Harness: grok - Model: grok-4.6 - Effort: high

仅修改 `scoring/` 与 `tests/test_scoring.py`，修复分数数值边界：score 和 max_score 必须是有限数字，拒绝 NaN、正负 Infinity；将 float 转换的 TypeError、ValueError、OverflowError 统一转为角色契约的 ValueError，且不写入评分。添加最小回归测试覆盖 Infinity 与超大整数。运行 `python3.11 -m unittest discover -s tests -v`。
