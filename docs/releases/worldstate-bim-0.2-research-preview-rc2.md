# WorldState BIM V0.2 Research Preview — Text-to-BIM 候选

状态：**可审查 Research Preview 候选；不是 Engineering Validated**。不包含公开 Release、正式标签或主分支合并。原 [WS-RealRoom 工程协议](../../benchmarks/ws_realroom/PROTOCOL.md)及历史结论保持不变。

| 能力 | 状态 | 边界 |
| --- | --- | --- |
| 已有 WorldState BIM 编辑与 IFC 导出 | PREVIEW | 当前冲突检测不是完整三维碰撞检查 |
| Codex 受控修改、历史恢复预览 | PREVIEW | 发送模型数据需授权；预览需明确确认，过期建议拒绝执行 |
| 文字创建矩形、L 形房间及门窗 | EXPERIMENTAL | 仅模拟设计；参数关联和假设需逐项复核；每服务实例当前只有一个工作区 |
| 真实照片到完整房间 | EXPERIMENTAL | 墙体、尺度、对应和遮挡未达到工程验收 |
| 真实房间精度、真人成本、实际模型费用 | NOT_MEASURED | 合成数据和浏览器自动化不代表现场或人工效率 |

## 安装、示例与版本

Linux x86-64、Python 3.12 下，以全新虚拟环境安装 `products/worldstate_bim/requirements-research-preview.txt`；规则模式不需要 Agent。公开合成示例的最短命令见 [示例说明](../../examples/bim_text_author/README.md)。旧的 [六视图模拟房间](../../examples/bim_research_preview/README.md)继续保留。仅本机监听；部署到 Tailnet 必须使用现有受信任反向代理及精确 Origin 配置。

全量研发回归另需测试依赖 `pytest==8.3.5` 和可选研究依赖 `onnxruntime==1.20.1`；它们不属于上述最小产品安装。首次只安装产品依赖运行全量回归时，因缺少 ONNX Runtime 在测试收集阶段失败，安装可选依赖后才重新执行完整回归。

从空白项目启动真实文字建模（需要已授权的 Codex CLI 和 Node 20+；输出目录应为专用私有目录）：

```bash
python3.12 -m venv /tmp/ws-venv
/tmp/ws-venv/bin/pip install -r products/worldstate_bim/requirements-research-preview.txt
npm --prefix products/worldstate_bim/agent ci
PYTHONPATH=. /tmp/ws-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /tmp/ws-new-design --port 8766 --enable-codex-agent \
  --agent-output /tmp/ws-private-agent-jobs
```

浏览器选择“文字新建设计”，输入明确的房间尺寸、墙厚、楼板厚与门窗宿主，检查模拟草案和假设并确认。仅提供数值的存在性校验不保证 Agent 将每个数值归属于正确字段，必须人工检查。使用 `/api/version` 或 Studio 页脚核对 Git 提交和已跟踪文件是否修改；未处于 Git 检出时提交标识可能为未知。

当前 Studio 实例绑定一个工作区，不能在界面内安全切换其他项目或直接把任意 IFC 当作 WorldState IR 导入。要打开合成示例、已有已转换项目或新的空白项目，请分别选择独立工作区启动；**不要复用或覆盖现有用户工作区**。新增多项目会话隔离仍未完成。

## 测试及已知限制

原冻结 23 项编辑任务的真实 Agent 本轮 23/23，规则模式 0/23；新增独立扩展任务 5/5。[逐项结果及历史说明](../../benchmarks/ws_agent/README.md)保留旧版 21/23。WS-Author 首轮 11/17，见[协议与复验说明](../../benchmarks/ws_author/README.md)。这些任务是模拟开发集，简单文本规则不构成全面语义审核。

Python 3.12 隔离环境补装上述测试依赖后，Core、BIM、合成和 Agent 自动化测试 276 通过；其中 87 条警告来自 IfcOpenShell 的上游弃用调用。

浏览器自动化从空白项目创建四墙、门窗和楼板，规则编辑后由真实 Agent 预览恢复；IFC 经 web-ifc 解析和几何生成，Bonsai 墙高修改后同步回 IR，13 个 IFC 产品 GUID 保持。该过程不是人工成本测量。已知 UI 仍需提供安全的多项目切换；独立真实场景精度、对抗性提示和任意建筑轮廓尚无充分评测。

旧候选 `d3c228f` 与线上部署 `c8f3e85` 的差异仅为四份验收或说明文件；二者产品代码相同，但当时部署标识确为 `c8f3e85`，不应称为已部署 `d3c228f`。

自生成示例按仓库 MIT 许可发布；[IfcOpenShell 官方项目](https://github.com/IfcOpenShell/IfcOpenShell)使用 LGPL，Bonsai/Blender 等工具和各依赖须分别遵守其分发条件。[ETH3D 官方数据](https://www.eth3d.net/)为 CC BY-NC-SA 4.0，不随本示例分发；受限视觉模型权重同样不打包。Codex 是可选外部服务，须使用已有授权，不复制或包含凭据。
