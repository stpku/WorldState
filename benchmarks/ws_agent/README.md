# WS-Agent：预先声明的模拟 BIM 任务

[tasks.json](tasks.json)固定 23 项独立任务、目标参数、保持对象及预期拒绝。每项都从同一个模拟房间的初始状态开始，两个特定案例分别移除角度约束或创建历史版本。可调用 Codex 的模型只能读其独立模拟项目，并通过现有 MCP 提出草稿；自动测试不会把草稿标为真人确认。

```bash
PYTHONPATH=. python benchmarks/ws_agent/run.py --mode rules --output /path/to/new-rule-run
# 需要已有授权的 Codex CLI、Node 20+，并在 products/worldstate_bim/agent 运行 npm ci。
PYTHONPATH=. python benchmarks/ws_agent/run.py --mode agent --workers 1 \
  --codex /path/to/codex --node /path/to/node --model gpt-6.1-terra --output /path/to/new-agent-run
```

[2026-11-17 结果](results/2026-11-17.json)包括 23 次真实 Codex 任务及相同题目的规则基线。Agent 最初自动评分 22/23；复核发现 A19 把不支持的参数错误说成已验证的垂直约束冲突，故按更严格的可追溯条件更正为 **21/23**，保留原评分与工具错误。A23 因 Agent 没有历史版本恢复工具而失败。已有 Studio 版本恢复功能已通过单独的模拟浏览器回归，但不能称为 Agent 已完成该任务。

后续候选对同一原始任务集的[真实 Agent 复跑结果为 23/23](results/2026-11-17-author-rc.json)：A19 使用只移动一个端点的实际操作，确定性工具返回角度约束冲突；A23 生成受版本和内容哈希约束的恢复预览，并在隔离评测中生成新版本。原任务和判定条件未改，历史 21/23 不追溯修改。新增[五项独立扩展任务](tasks-extended-v1.json)的[结果为 5/5](results/2026-11-17-extended-v1.json)。这不是对任意指令可靠性的证明。

规则模式在这 23 条自然语言输入上为 0/23；它采用严格的固定命令格式，而不是通用语言理解。另用其文档格式验证了一次正常规则修改。结果是这个小任务集的表现，不应外推到所有命令或真实用户。

评测核对预期参数、IFC 解析/几何、GUID 和指定未受影响对象；拒绝/澄清题含简单文本规则，因此不能等同于全面语义评审。多建议先在隔离副本上顺序验证，随后 A20 的两个真实建议通过 Studio 批量确认流程由 Playwright 自动执行；不是人工效率实验。结果保留 token、时长及工具次数，模型费用和真人成本为 `NOT_MEASURED`。`regrade.py` 只重算已保存输出，不会再次调用模型。
