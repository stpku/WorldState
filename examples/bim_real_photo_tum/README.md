# 真实照片驱动的辅助墙面草稿

**状态：部分、未验证，不是完整房间，也不是 V0.2 发布成果。** 本例使用 TUM RGB-D `fr1/room` 中的真实办公室彩色帧和配准深度、人工框选的可见墙面、小型本地相对深度模型，以及明确假设的 0.12 m 厚度，生成 IFC4 `IfcWall`。墙的标签由研究者手工指定，模型仅辅助区域筛选；不代表 DSH 自动建模。

输入是 [TUM RGB-D 数据集](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download)，作者 J. Sturm、N. Engelhard、F. Endres、W. Burgard、D. Cremers；数据按 [作者论文](https://cvg.cit.tum.de/_media/spezial/bib/sturm12iros_ws.pdf) 的 CC BY 3.0 声明使用。原始照片和模型权重不随仓库分发；[第一轮清单](../../benchmarks/bim_real_room/manifest.json)记录固定来源与哈希。

| 文件 | 作用 |
| --- | --- |
| [wall-original.ifc](wall-original.ifc) / [IR](wall-original.json) | 由真实照片和深度数据产生的可见墙面片段；不是墙体全高/全长。 |
| [wall-revised.ifc](wall-revised.ifc) / [IR](wall-revised.json) / [差异](wall-diff.json) | 将片段长度从约 0.428 m 改为 0.500 m 的人工修订示例，GUID 不变；修改不是实测值。 |
| [observed-surface.ply](observed-surface.ply) | 同一帧深度传感器生成的局部点云；不代表独立尺寸真值。 |
| [web-ifc-edited.ifc](web-ifc-edited.ifc) / [报告](web-ifc-report.json) | 独立 web-ifc 引擎把片段高度改为 0.45 m 并保存回读；该外部修改没有同步 IR，必须重新验证。 |

相机图像上方方向被假设为近似竖直；真实厚度、完整墙界、完整墙高和不可见开口未知。**尺度锚从同一深度传感器数据计算，已实际应用但不是独立尺度参考。** 因此没有独立墙尺寸误差、自动化率或人工成本验收结果。

## 本地复现

从仓库根目录执行，约 100 MB 可选视觉模型下载至 `/tmp`；Python 3.12 和依赖按第一轮 benchmark 安装。

```bash
python3 benchmarks/bim_real_room/fetch.py --data-dir /tmp/worldstate-bim-data --with-model
/tmp/worldstate-bim-venv/bin/python -m products.worldstate_bim.assisted_cli create \
  --image /tmp/worldstate-bim-data/1305031916.701048.png \
  --depth /tmp/worldstate-bim-data/1305031916.711186.png --roi 10 228 90 295 \
  --anchor-pixels 30 250 70 250 --intrinsics 525 525 319.5 239.5 \
  --anchor-m 0.25450176404148306 --anchor-independence same_sensor \
  --anchor-description 'TUM sensor calibration from the same depth frame' \
  --thickness-m 0.12 --project-id tum-fr1-room-assisted-patch --operator analyst \
  --vision-onnx /tmp/worldstate-bim-data/depth-anything-v2-small.onnx \
  --output-dir /tmp/worldstate-bim-output/v1

/tmp/worldstate-bim-venv/bin/python -m products.worldstate_bim.assisted_cli revise \
  --model /tmp/worldstate-bim-output/v1/model.json --evidence-root /tmp/worldstate-bim-data \
  --wall-id wall-patch-1 --length-m 0.50 --reason 'Demo edit, not a measurement' \
  --operator analyst --output-dir /tmp/worldstate-bim-output/v2

/tmp/worldstate-bim-venv/bin/python -m products.worldstate_bim.viewer_server \
  --model-dir /tmp/worldstate-bim-output/v1 --evidence-root /tmp/worldstate-bim-data \
  --workspace /tmp/worldstate-bim-output/browser-revisions --port 8765
```

浏览器访问 `http://127.0.0.1:8765/`，可检查照片选区、旋转示意墙体、修改长度、保存新版本并下载 IFC。界面仅监听本机；其 3D 视图按 IR 参数绘制盒体，不是通用 IFC 查看器。人工修改后状态为需要重新验证。
