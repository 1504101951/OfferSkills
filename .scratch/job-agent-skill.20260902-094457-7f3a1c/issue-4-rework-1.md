# Role: Executor - Execution Issue: #4 - Rework 1 - Harness: grok - Model: grok-4.6 - Effort: high

修复知识搜索角色的批量写入原子性问题，仅修改 `knowledge_search/` 和对应测试，不修改 `memory/`、`question/` 或其他模块。

当前问题：`KnowledgeSearchRole.search()` 在循环内逐文档校验并立即写库；多个文档中后一个缺少 `source_url` 时，前一个已提交。再次调用会因已有切片直接复用，无法补齐缺失资料。

要求：在任何写入前完成整批输入校验和切片准备；任一文档无来源或内容无效时，不写入任何新切片。添加一个最小回归测试：两个文档，第二个缺少 `source_url`，调用失败且该 requirement_id 下仍无切片。运行 `python3.11 -m unittest discover -s tests -v`。只返回修改文件、测试结果和剩余风险。
