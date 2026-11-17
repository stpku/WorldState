# WorldState Research Preview：自生成模拟房间

此示例包含合成房间的 6 张 RGB 图、模拟相机和四墙、楼板、门窗、开口的原生 IFC4。照片和 IFC 来自同一程序化场景；它们**不是照片重建结果、真实建筑或测量精度证明**。`reference/` 的深度、实例、语义、可见性及真值仅供开发，不是冻结测试集。

所有图像、几何、IFC 和标签均由本仓库生成器、简单自定义材质及确定性几何生成，没有使用外部照片、受限模型权重或第三方纹理。示例可按仓库根目录的 [MIT 许可](../../LICENSE)分发。Blender 软件自身使用 GPL，独立生成的图像依生成者的权利授权；[Blender 官方说明](https://docs.blender.org/manual/en/latest/getting_started/about/license.html)。IfcOpenShell 和 Bonsai 的程序许可分别见其[官方说明](https://docs.ifcopenshell.org/introduction)；工具本身未打包在示例中。

从仓库根目录运行（需要 Python 3.12 与已安装的产品依赖；所有目录须是新路径）：

```bash
python3.12 -m venv /path/to/ws-preview-venv
/path/to/ws-preview-venv/bin/pip install -r products/worldstate_bim/requirements-research-preview.txt
PYTHONPATH=. /path/to/ws-preview-venv/bin/python benchmarks/ws_synthetic/prepare_demo.py \
  --example examples/bim_research_preview --output /path/to/new-private-workspace --operator user
PYTHONPATH=. /path/to/ws-preview-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /path/to/new-private-workspace --port 8766
```

在服务器本机打开 `http://127.0.0.1:8766/`。左侧可选墙、门、窗；右侧修改参数并保存新版本；导出 IFC 后可在支持 IFC4 的独立软件中检查。已有图片与参考模型并列展示，并非对完整房间自动配准或照片驱动重建。未提供视觉模型时，本地规则模式仍可用；真实 Codex Agent 需要单独安装 Node 依赖并配置已授权的 CLI，按界面要求确认数据传输。

合成数据生成、冻结和评测见 [WS-Synthetic 说明](../../benchmarks/ws_synthetic/README.md)。实际人工用时和真实房间精度没有由此示例测量。
