# V0.2 Research Preview 候选验收记录

判断：**Research Preview Ready（既有 BIM 编辑与合成演示范围）**。这是可审查的候选判断，不是公开 Release、工程认证或生产就绪；照片到完整 BIM、真实扫描语义和工程精度仍为实验性或未测。原 [WS-RealRoom 工程协议](../../benchmarks/ws_realroom/PROTOCOL.md)保持未完成。

| 预览门槛 | 实际结果 |
| --- | --- |
| Core 与产品回归 | 270 passed，80 条第三方弃用警告。 |
| 可安装示例与 Studio | 干净 Python 3.12 环境安装产品依赖，导入 6 张模拟图、模拟相机和 IFC；浏览器完成墙高修改、导出和历史版本恢复。 |
| IFC 独立读写 | 合成 IFC4 schema 0 错误，墙/门/窗/楼板几何生成；Bonsai 墙高编辑和 IR 回写，13 个产品 GUID 保持。 |
| 合成冻结评测 | 矩形、非矩形各 6 视图；真实匹配模型提交结果，低纹理/遮挡导致多项失败；没有独立提交的重建房间模型。 |
| WS-Agent | 23 项真实 Codex 模型任务经复核 21 项通过；规则基线 0/23；A19 检查解释不可信，A23 的 Agent 版本恢复未支持。 |
| 安全与证据 | 批量建议重新计算并确认；旧建议拒绝；非法 Host、Origin 和缺令牌请求被拒；模拟结果标为模拟。 |
| 分发和限制 | 仓库提供自生成 MIT 模拟示例、可复现命令、[逐项能力状态与 Release Notes](../../products/worldstate_bim/RESEARCH_PREVIEW.md)。真实受限影像和模型权重不进入示例。 |

现有 Studio 已更新至此候选的产品代码；用户原有项目保持独立。真实房间尺寸、墙体实例精度、真人成本、实际模型费用和真实 Windows 客户端均为 **NOT_MEASURED**。详细实验、失败与资源记录见[研发报告](../../docs/reports/worldstate-research-preview-2026-11-17.md)。
