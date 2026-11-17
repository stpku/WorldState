# Text-to-BIM：模拟设计示例

这里的 [IFC](model.ifc)、[Room IR](model.json) 和 [Studio 截图](studio.png)来自一次真实 Codex Agent 调用和浏览器自动确认：从空白项目生成 5 × 4 × 3 米的模拟房间，包含四墙、一块楼板、一扇门、一扇窗及其开口。没有现场照片或实测信息，模型是**设计意图，不是现实观测**。

该示例仅使用本仓库生成的参数与几何，按仓库 MIT 许可提供；不包含 ETH3D 数据或视觉模型权重。IFC 的 SHA-256 为 `de29b5614d9a584f43d787e7d10aeed65445f72e47c60bb4d39f1c0ecc190ed9`。实际浏览器、独立 web-ifc 与 Bonsai 检查见 [WS-Author 结果](../../benchmarks/ws_author/results/)。

在已安装 [Research Preview 依赖](../../products/worldstate_bim/requirements-research-preview.txt)的 Python 环境下，从仓库根目录导入到**不存在的新目录**并启动：

```bash
PYTHONPATH=. python -m benchmarks.ws_author.prepare_demo --output /tmp/worldstate-text-demo
PYTHONPATH=. python -m products.worldstate_bim.studio_server --workspace /tmp/worldstate-text-demo --port 8766
```

访问本机 `http://127.0.0.1:8766/`。示例可以在规则模式下编辑并导出；它不会覆盖已有用户项目。重新从空白项目用自然语言创建还需要已授权的 Codex、Node 和单独安装的 MCP 依赖，按[发布候选说明](../../docs/releases/worldstate-bim-0.2-research-preview-rc2.md)启动并明确确认文字发送。
