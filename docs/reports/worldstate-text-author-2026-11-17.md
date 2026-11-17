# Text-to-BIM 与 Research Preview 候选记录 · 2026-11-17

## 基线和范围

`c8f3e85` 线上副本与候选 `d3c228f` 只差四个验收或说明文件，产品代码一致，但线上标识确为前者。原五处用户未提交修改、Core 契约、用户项目和两项验收协议保持不变。工程级真实房间结果依旧 `NOT_MEASURED`，不追溯修改历史结果。

在独立 Python 3.12 环境安装 Research Preview 依赖，使用六视图合成示例完成规则编辑、真实 Codex 修改、IFC 导出和历史恢复；两次确认均为自动化。首次隔离服务未配置已有网络环境，真实 Agent 超时；在使用现有授权环境后成功，失败记录没有抹除。输出保存在 `/home/dev/.cache/worldstate-text-author/baseline-clean-browser-v1` 与 `baseline-clean-browser-v2`，不包含客户资料。

该环境额外安装 `pytest==8.3.5` 和仅用于研究测试的 `onnxruntime==1.20.1` 后，全量 Core、BIM、合成和 Agent 测试 **276 通过**；最小产品依赖不包含这两个测试工具，缺少 ONNX Runtime 的首次完整收集失败已记录。另有 87 条 IfcOpenShell 上游弃用警告。

## 冻结任务

原 23 项 WS-Agent [真实运行 23/23](../../benchmarks/ws_agent/results/2026-11-17-author-rc.json)，规则模式 0/23。A19 的端点移动得到真实 `ANGULAR_CONSTRAINT_CONFLICT`；A23 生成受当前和历史快照哈希约束的恢复预览，自动确认创建新版本。原任务及评分标准未更改；旧记录 21/23 保留。另行冻结的[扩展五项任务 5/5](../../benchmarks/ws_agent/results/2026-11-17-extended-v1.json)，覆盖实际工具错误、过期建议、版本恢复、歧义与缺失对象。

[WS-Author 首轮 11/17](../../benchmarks/ws_author/results/2026-11-17-v1.json)。六项各生成不止一个草案，严格运行器因此判失败，即使其中有正确草案。随后明确提示墙体宿主 ID，并禁止无关的部分草案，[六项针对性开发复验 6/6](../../benchmarks/ws_author/results/2026-11-17-followup.json)；它使用了已解封题目，不能叫独立盲测。首次运行源码可按[恢复补丁](../../benchmarks/ws_author/results/restore-v1-source.patch)及记录的 SHA-256 核对。

23 项编辑任务总输入 1,526,991 token（其中缓存 1,342,336）、输出 8,236；各题耗时之和 518.29 秒，并发两题。前次对应为 1,556,883 输入、1,330,176 缓存输入、9,242 输出、496.58 秒。总输入减少约 1.9%，但调用和任务结果不同，不能据此断言优化效果或实际费用。WS-Author 首轮含 T17 后续修改与恢复共 19 次调用，输入 1,453,318、缓存 1,316,480、输出 11,975 token。实际费用和人工成本均为 `NOT_MEASURED`。

## 产品执行

隔离工作区中由真实 Agent 根据文字提出模拟房间，自动化在浏览器确认后得到四墙、楼板、门、窗与两个开口；规则模式修改墙高后，真实 Agent 预览恢复版本 1 并经自动化确认创建版本 3。[浏览器记录](../../benchmarks/ws_author/results/browser-2026-11-17.json)、[设计工具轨迹](../../benchmarks/ws_author/results/browser-design-trace.jsonl)和[恢复工具轨迹](../../benchmarks/ws_author/results/browser-restore-trace.jsonl)可复核。首次浏览器发现空项目入口被遮挡；修复后发现无照片项目缺索引导致恢复失败，修复后从新隔离项目完整复验通过。截图为 Linux Chromium 1440×900，不声称 Windows 实测。

该 IFC 的 [web-ifc 独立读取](../../benchmarks/ws_author/results/web-ifc-2026-11-17.json)为 IFC4、7/7 可见构件生成几何、2 个 void 和 2 个 fill 关系。Blender 5.2.2 / Bonsai 0.9.0.post1 将 wall-2 高度由 3.0 改为 3.1 米，回写后 13 个 IFC 产品 GUID 保持，未修改构件的顶点几何未变化，IFC schema 0 错误；详见[Bonsai 编辑](../../benchmarks/ws_author/results/bonsai-edit-2026-11-17.json)与[回写核验](../../benchmarks/ws_author/results/bonsai-identity-2026-11-17.json)。本例是模拟设计，不是测量值。

## 已知限制

- 数值来源检查只能证明数值出现在请求中，不能证明 Agent 对字段的归属正确；用户必须核查确认。自动化任务和实际费用不能代替真人工作量测量。
- Studio 单实例仍绑定一个工作区；安全的多项目会话切换与任意原始 IFC 导入尚未实现。公开示例可用独立目录导入。
- 真实照片重建、扫描到 BIM 和视觉对应仍为实验能力；无人宣称完整真实房间或工程验证已通过。DSH 项目级授权仍非本轮依赖。
- 公开示例只包含本仓库生成的模拟内容；ETH3D 等受限数据、模型权重和凭据不随示例分发。详见[候选说明](../releases/worldstate-bim-0.2-research-preview-rc2.md)。
