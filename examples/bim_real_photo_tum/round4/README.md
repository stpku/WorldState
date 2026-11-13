# TUM 真照片 Studio 局部墙实验

**开发验证，非完整房间、非独立验收。** 使用 TUM RGB-D `fr1/room` 的公开真实照片，在 Studio 中手工标记一段可见的墙/地面交线，采用相机地面反投影生成一块 IFC 墙。墙体身份、相机姿态和墙段范围均未独立核实；高度 0.45 m 与厚度 0.12 m 是明确假设，不是整墙实测。本例不声称自动识别、三面墙或真实房间精度。

- 输入 RGB 为 `1305031927.869143.png`，SHA-256 `16a398d2a61ed1eaec756f985b4cee59afe7086ce7661fe271d8facd10e75be9`。另一张上传的 `1305031916.701048.png` 仅用于上传流程，未关联构件。
- 标尺由同一场景的配准深度帧 `1305031927.855551.png` 计算，时间差约 13.6 ms；文件 SHA-256 `8ebd0d5a8f0083c9a7b66885fe4308f2f8bce55787246c00f366b13b416aa8c1`。该帧来自固定版本的 Hugging Face 镜像，尚未和 TUM 原始完整包逐字节核对。它**不是独立尺度真值**。
- 初始照片端点为 `(255,170)` 和 `(415,155)`。用两个像素的深度原值除以 5000，并以近似 `fx=fy=525, cx=319.5, cy=239.5` 反投影，计算出同传感器参照距离 `0.6038487127014679 m`。求解另假设地面水平、相机向下俯角 30°、横滚为零且不补偿镜头畸变；这些都没有独立标定。
- [原始 IFC](photo-original.ifc) / [IR](photo-original.json) 为首个局部候选。[修改标注 IFC](annotation-change.ifc) 将第二个图像点从 `(415,155)` 移到 `(400,155)`，其墙体方向随之改变。这个移动是检验交互敏感性的**人为扰动**，继续沿用原尺度仅为测试，不能视为对新端点的有效实测。
- [规则修改 IFC](rule-edit.ifc) / [差异](rule-diff.json) 将墙段延长 0.2 m，是确定性本地规则，并非 DSH。Blender 5.2.2 + Bonsai 0.9.0.post1 再将墙长从约 0.804 m 改为 0.900 m，保存[外部 IFC](bonsai-edited.ifc) 后由 Studio 的浏览器界面校验并[回写 IR](bonsai-synced.json)；[修改差异](bonsai-sync-diff.json)、[Bonsai 记录](bonsai-report.json)。墙 GUID 始终为 `3CdM3EaMfR7PQ6jM1suVWX`。
- 在上述版本上另用 Bonsai 将高度由 0.45 改为 0.50 m，再通过 [Studio 浏览器回写脚本](../../../benchmarks/ws_realroom/studio_sync_browser.cjs)核验并生成[高度修改 IFC](height-synced.ifc) 和[差异](height-sync-diff.json)。这同样是自动化演示，不是新测量。
- [浏览器记录](browser-report.json)和[项目操作记录](photo-project.json)来自 Playwright 自动操作，标注分类为 `simulated`；标注经过时间不能充当人工成本。原始照片与深度不提交至本仓库。数据授权沿用 [TUM RGB-D 数据集记录](../README.md)；不得将无授权的私人资料加入仓库。

五个产品 IFC 均由 IfcOpenShell 0.8.4 检查 schema 且成功生成墙几何；web-ifc 0.0.77 独立读回墙及同一 GUID。这些检查不证明物理位置、分类或尺寸正确。

浏览器操作脚本为 [studio_tum_browser.cjs](../../../benchmarks/ws_realroom/studio_tum_browser.cjs)。先按 [Benchmark 安装](../../../benchmarks/README.md)准备依赖及 Playwright，再将两张公开照片保存在仓库外；启动一个**新**工作区后运行：

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /tmp/ws-tum-photo-project-NEW --port 8773

NODE_PATH=/path/to/node_modules node benchmarks/ws_realroom/studio_tum_browser.cjs \
  http://127.0.0.1:8773 /path/to/1305031927.869143.png \
  /path/to/1305031916.701048.png /tmp/ws-tum-browser-report-NEW
```

脚本只负责创建、上传、标注、生成、扰动和规则编辑；Bonsai 操作与外部 IFC 回写需要另行运行。新工作区和报告目录均不能含有先前项目。
