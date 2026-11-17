# WS-Author：独立的模拟设计任务

[冻结协议](PROTOCOL.md)和 [17 项任务](tasks.json)在执行前提交。每题从独立空项目开始；参考只用于评分，不交给 Agent。示例、参数、模型和照片均为模拟，不能用于声称照片重建精度或现场实测。提供的参考场景是开发评测，并非未见过的盲测。

首次真实 Codex 运行 [11/17](results/2026-11-17-v1.json)。六项产生了不止一个设计草案，因此按该运行器的严格规则失败，即使其中包含符合要求的最终草案；记录没有回填成成功。针对宿主墙编号提示修正后，[六题开发复验为 6/6](results/2026-11-17-followup.json)，这是看过失败后的重复评测，**不能替代完整独立测试或合称 17/17**。T17 的三次操作由自动化确认，不是人工效率实验。

```bash
# 使用已授权 Codex CLI、Node 20+ 与单独安装的 MCP 依赖。
PYTHONPATH=. python -m benchmarks.ws_author.run --workers 1 \
  --codex /path/to/codex --node /path/to/node --model gpt-6.1-terra \
  --output /path/to/new-private-author-run
```

每个任务保留工具记录、结果、用量和 IFC；实际费用和人工成本为 `NOT_MEASURED`。要复现首轮实现，在隔离检出中应用 [恢复首轮源文件的补丁](results/restore-v1-source.patch)，并核对首轮结果中的源文件 SHA-256；该补丁只用于历史实验，不能应用于运行中的服务。模型服务有随机性，不能保证重复运行得分相同。

[浏览器记录](results/browser-2026-11-17.json)及[设计工具轨迹](results/browser-design-trace.jsonl)、[恢复工具轨迹](results/browser-restore-trace.jsonl)来自隔离的自动化项目。[web-ifc](results/web-ifc-2026-11-17.json)独立解析了 7 个可见构件的几何；[Bonsai 编辑](results/bonsai-edit-2026-11-17.json)后的[回写和 GUID 对照](results/bonsai-identity-2026-11-17.json)通过。所有确认都是自动化，且该模拟例子不证明现场精度。
