# WorldState BIM V0.2 — Research Preview 候选

**定位：AI-native Evidence-to-BIM Studio 研究预览；不是工程级测量工具或正式生产版本。** 本文件描述候选，不是公开 Release 或 Git 标签。保留原 [WS-RealRoom 工程验收协议](../../benchmarks/ws_realroom/PROTOCOL.md)，该协议尚未完成。

## 交付与安装

- 本地 Studio：IFC 构件查看、参数编辑、导出、版本恢复及受支持的 IFC 外部编辑回写。
- 可选 Codex Agent：已有模型的受控修改建议、逐项或多项预览与确认；照片必须明确授权。规则模式仍可独立运行，不冒充 Agent。
- [自生成模拟示例](../../examples/bim_research_preview/README.md)：6 张模拟图、已知模拟相机、四墙、门窗与 IFC；初始模型不是照片重建结果。
- [WS-Synthetic](../../benchmarks/ws_synthetic/README.md) 与 [WS-Agent](../../benchmarks/ws_agent/README.md)：合成真值、冻结评测与固定任务基准。

Linux x86-64、CPython 3.12.3 下已在新虚拟环境安装 `products/worldstate_bim/requirements-research-preview.txt` 并运行示例和浏览器流程。安装和最短命令见[示例说明](../../examples/bim_research_preview/README.md)。其他操作系统尚未单独验证。合成数据再生成需单独安装 Blender 和 OpenEXR；真实视觉 Provider、Bonsai、Node/Codex 均为可选组件，不打包或自动下载权重。

## 本轮验证

- 合成矩形和 L 形房间各生成 6 视图与精确参考；冻结测试使用预先固定的相同双图输入。GlueStick 两场景分别 0 个、4 个匹配点；后者严格正确 2/4。Tiny RoMa 两场景严格正确分别为 0/999、313/1000。算法输入尺寸不同、样本很小，这些值只能描述本次合成对应，不代表真实场景精度。[机器可读结果](../../benchmarks/ws_synthetic/results/2026-11-17.json)。
- 固定 23 项模拟模型任务中，真实 Codex Agent 经严格复核 **21/23**；规则基线 **0/23**，它只能解析固定格式。A19 的角度冲突理由未被工具证明，A23 无 Agent 版本恢复工具；不得将未证实的结果计为通过。[任务、判分边界与每项结果](../../benchmarks/ws_agent/README.md)。
- 合成模型的真实 Agent 多项建议在隔离浏览器中经自动化确认并生成两个修订版本；门洞宿主关系与 13 个 IFC 产品 GUID 保持。Bonsai 对另一合成墙高进行修改并回写，IFC4 schema 检查为 0 错误；这些不是人工评审。
- ETH3D kicker 旧已知位姿草稿与整场扫描的自动诊断保留在研发报告中：两个扫描文件与相机配准相关，未审核的扫描平面可能是家具或其他表面，不能称为独立墙尺寸或实例精度。

## 已知限制

- **EXPERIMENTAL：**真实照片到完整房间的自动重建；多视图匹配可能失效、混淆家具与墙，尺度和遮挡可能不可辨识。
- **EXPERIMENTAL：**真实点云重建结果及语义。CRASLAB 示例包含未确认墙窗和假设厚度，不能作为工程实况。
- **PREVIEW：**AI 修改只在受控预览与明确确认后应用；其上下文开销较高，历史版本恢复尚未暴露为 Agent 工具。当前冲突检查不是完整三维实体碰撞检查。
- **PREVIEW：**批量修改逐步保存可回退版本；如果文件写入中断，当前模型不会推进，但可能留有需检查的新版本目录。
- **NOT_MEASURED：**工程级真实房间实例精度、尺寸误差、真人建模成本、实际模型费用以及真实 Windows 客户端体验。浏览器自动化时间不能代替人工耗时。

ETH3D 用于符合其 CC BY-NC-SA 4.0 的非商业研究，不包含在本示例中。GlueStick 官方组合的 SuperPoint 受非商业限制，其他权重和依赖也须分别核实；本候选没有将它们作为产品资产分发。[许可与实验记录](../../docs/reports/worldstate-visual-correspondence-model-reality-2026-11-17.md)。
