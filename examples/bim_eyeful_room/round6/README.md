# Round 6：真实多视图语义融合开发结果

**结果：两段由真实多视图三维点和语义平面驱动的可编辑墙体草稿；不是完整房间，也不是三面已验收墙体。** 本例尺度来自同一批照片的另一套重建，明确标为 **assumed**，没有独立实物测量；墙厚也是假设。V0.2 仍为 **NOT RELEASE-READY**。

## 真实运行与证据

- 输入 [Eyeful Tower](https://github.com/facebookresearch/EyefulTower) `raf_emptyroom` 32 张公开 MIT 开发照片，第四轮及冻结验收数据未修改。重用已注册的 28 张相机，逐张在本地 CPU 运行 UPerNet；85.07 秒后得到[逐图掩膜](masks/manifest.json)。原图 SHA-256、原图像素与 128×128 掩膜索引的变换均记录在清单中。
- [融合结果](fusion.json)包含 446 条 COLMAP 三维轨迹及每次照片像素观测、照片哈希、语义类别、模型分数和重投影误差。362 条通过当前支持条件，46 条存在语义冲突，38 条因支持不足或重投影被排除；语义分数未经校准。相机约定为 `x_camera = R_camera_from_world @ x_world + t`，几何初始尺度未知。
- 地面候选由 14 个三维点、27 张照片支持，拟合 RMS 为 0.0358 **相对单位**。墙面主要候选由 182 点、28 张照片支持；另一方向候选由 18 点、22 张照片支持。[照片叠加图](overlays/)显示真实像素支持点及**推断**的三维平面范围，可见左侧有设备与遮挡，需人工核对。拟合残差不是独立墙体精度。
- 共输出 4 个墙面假设；其中两块近似平行片段暂定合并，仍保留来源和不确定性。其他近似平行候选可能重复，也可能是相近真实墙面，系统拒绝将冲突组合直接当作不同墙导出。可供谨慎选择的不同方向墙面目前只有两组，**第三面墙未可靠恢复**。
- 墙面与地面相交得到真实三维直线；两组方向不同的候选及地面计算出[三平面交点](fusion.json)。主要交点的条件数约 1.40，但位于一个墙段支持投影的内部、另一个范围稍外；它不是已观察墙角，系统没有擅自连接或截断墙体。
- 两个真实跨视图特征点由两张已注册照片三角化，最大重投影误差分别为 0.428 和 0.005 像素，视差分别约 19.35° 和 6.74°。它们是脚本选取的特征，并非实测标尺端点。[反事实记录](correspondence-counterfactual.json)中改变一个像素使三维结果变化约 0.0997 相对单位；错误对应被拒绝。重投影误差不能代替三维准确度。
- [假设尺度与端点](ifc/anchor-assumed.json)由同一场景的相关 Metashape 相机重建给出，未独立测量且测量不确定性为 UNKNOWN。尺度实际作用于相机平移、点、平面及墙体坐标；标尺观测、相机或测量变化会使旧绑定失效。将假设长度人为增加 20% 后，墙段长度和高度也增加 20%；固定输入的 0.12 m 墙厚仍是单独的绝对尺寸假设，不跟随缩放。标尺拟合残差是约束内结果，不是独立精度。
- [原始 IFC](ifc/original.ifc)、[IR 与逐像素来源](ifc/original.json)、[20% 尺度反事实 IFC](ifc/scale-counterfactual.ifc)。两段墙的范围由三维稀疏支持点分位范围与平面交线推断，不是完整墙长、墙高或遮挡范围。Blender 5.2.2 + Bonsai 0.9.0.post1 的脚本使用原生算子将其中一段高度从约 2.1955 m 改为 2.3 m，并[回写 IR 与 IFC](ifc/bonsai-synced/)；两个 GUID 保持不变。IfcOpenShell 0.8.4 对原始、尺度反事实、Bonsai 修改和回写结果均解析 IFC4、生成两墙几何，schema 错误为 0。该软件检查不证明实物尺寸正确。
- 删除 `19_DSC0541.jpg` 后**重新运行 COLMAP**，不是仅隐藏证据：注册照片从 28 降到 26，轨迹从 446 降到 416，被删除图片的 84 条原有观测在[新融合结果](fusion-remove-photo.json)中均不存在。[暂定身份关联](association-remove-photo.json)通过剩余图片中的共同特征把两组主要候选关联起来；该关联不是对真实墙实例的独立证明。

## Studio 实测

[最新浏览器记录](studio/final-run/browser-result.json)来自真实 CPU/浏览器工作流：上传 32 图 → 使用同场景同一相机公开标定 → 注册 28 图 → 对每张注册图运行语义模型 → 融合 461 条轨迹和三维候选 → 在两张照片中按顺序标记同一对特征点 → 以明确假设尺度生成两墙 IFC → 修改高度并导出。其[三维界面](studio/final-run/builder.png)可旋转查看相机、点云和候选平面；[IFC](studio/final-run/revised.ifc) 与 [IR](studio/final-run/revised.json)保留相机、照片像素、平面和尺度来源。标点及确认均为 Playwright 自动操作，**不能作为人工成本**。之前另一轮同配置运行产生 476 条轨迹，COLMAP 的并行求解并非完全可复现；保留[先前浏览器记录](studio/browser-result.json)，不将两次运行混为一组结果。

针对最终浏览器项目，[真实界面反事实](studio/final-run/lifecycle-result.json)把假设参照改大 20%：系统拒绝旧绑定；重新求解后，两段墙的长度均增加 20%，GUID 不变。随后更改相机参数，系统拒绝以旧相机融合或生成；重载页面后仍要求重新恢复相机。最终工作区故意保留该待重新计算状态。这些操作是脚本测试，不代表尺子被实际测量。

首次 GUI 自标定仅注册 5/32 图，焦距发散至约 320172 像素，保留[失败记录](sfm-selfcal-failure.json)。同一台相机的公开标定传感器为 9，源文件 SHA-256 `05e702e72fb9076d6fef2eb40e6dbd082ad7615dc381cb2709bace449fec74b7`；用户显式确认固定标定后，GUI 注册 28/32。用户填写的标定及来源仍是待核验声明；不可将其他相机参数自动套用。

GUI 的早期版本将 `null` 测量不确定性写成“measurement uncertainty recorded”，这是措辞错误；它还把脚本代替人确认的辅助流程标为 `automatic`，混淆了自动化测试和自动建模。历史 [original.json](studio/original.json)、[rebound.json](studio/rebound.json) 被保留。最新 [latest.json](studio/latest.json)将测量不确定性标为 `unknown`，工作流标为 `assisted`、操作来源为 `automation`。升级后旧尺度绑定会被拒绝，须重新求解，见[回归记录](studio/rebind-result.json)。

资源：4 个 AMD EPYC 7K83 CPU 核、无 GPU；最新 GUI 实测 COLMAP 约 4.20 秒，28 张语义推理约 86.49 秒，轨迹与平面融合约 3.40 秒；未测真实人工时间或模型成本。

数据采用 Eyeful Tower 的 [MIT 许可和版权声明](../LICENSE.eyeful.txt)；图像的固定来源和哈希见[清单](../../../benchmarks/ws_geometry/eyeful-emptyroom-manifest.json)。模型是带 MIT 标记的第三方 ONNX 导出，许可及上游署名见[许可记录](../../../benchmarks/ws_structure/LICENSE.upernet-export.txt)，未独立证明权重与上游检查点完全一致；原图和模型权重均未提交。本次使用 pycolmap 4.2.1、ONNX Runtime 1.20.1、NumPy 1.26.4、OpenCV 4.10.0.84 和 IfcOpenShell 0.8.4。

## 复现

在仓库根目录安装 `benchmarks/ws_geometry/requirements-round2-cpu.txt` 后，下载公开照片（不向任何服务上传用户照片），使用已保存的掩膜和 COLMAP 输出即可复现开发融合；权重不提交仓库。以下目录必须不存在：

```bash
python3.12 -m venv /tmp/ws-bim-venv
/tmp/ws-bim-venv/bin/pip install -r benchmarks/ws_geometry/requirements-round2-cpu.txt
export OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/fetch_eyeful.py \
  --sfm-only --output /tmp/ws-r6-images
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_multiview_fusion.py fuse \
  --sparse examples/bim_eyeful_room/round6/sfm --images /tmp/ws-r6-images \
  --masks examples/bim_eyeful_room/round6/masks --output /tmp/ws-r6-fusion.json
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_multiview_room_example.py \
  --fusion /tmp/ws-r6-fusion.json \
  --correlated-reference examples/bim_eyeful_room/geometry/correlated-pose-comparison.json \
  --output /tmp/ws-r6-ifc-new
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_multiview_counterfactual.py \
  --fusion /tmp/ws-r6-fusion.json --anchor /tmp/ws-r6-ifc-new/anchor-assumed.json \
  --output /tmp/ws-r6-counterfactual.json
```

从原始照片重新推理掩膜可先用 `benchmarks/ws_structure/fetch_upernet.py` 下载并核验模型，再执行 `run_multiview_fusion.py infer --sparse ... --images ... --model ... --output ...`。Studio 本次实际运行也保存了[独立的 SfM、掩膜和融合结果](studio/)。下面按哈希恢复该次运行的图像名，再从保存的真实输入重复融合；已实际验证候选 ID 与支持点数一致：

```bash
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/rehydrate_fusion_images.py \
  --fusion examples/bim_eyeful_room/round6/studio/final-run/fusion.json \
  --images /tmp/ws-r6-images --output /tmp/ws-r6-studio-images
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_multiview_fusion.py fuse \
  --sparse examples/bim_eyeful_room/round6/studio/final-run/sfm --images /tmp/ws-r6-studio-images \
  --masks examples/bim_eyeful_room/round6/studio/final-run/masks --output /tmp/ws-r6-studio-fusion.json
```

要重复完整的本地浏览器流程，在独立终端启动 Studio（路径指向已核验的本地 UPerNet 模型）；另一个终端运行以下脚本。它需要本地 Playwright、Chromium、公开照片和同场景的相机参考；脚本校验源文件哈希，并使用**相关重建假设尺度**，不是实物测量：

```bash
export OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
/tmp/ws-bim-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /tmp/ws-r6-studio-new --port 8766 --vision-model /path/to/upernet.onnx
# 另一个终端；改为本机的 Playwright 和 Chromium 路径。
curl -fL 'https://fb-baas-f32eacb9-8abb-11eb-b2b8-4857dd089e15.s3.amazonaws.com/EyefulTower/raf_emptyroom/cameras.json' -o /tmp/ws-r6-cameras.json
NODE_PATH=/path/to/node_modules CHROMIUM_PATH=/path/to/chromium \
  node benchmarks/ws_realroom/studio_true_multiview_browser.cjs \
  http://127.0.0.1:8766 /tmp/ws-r6-images benchmarks/ws_geometry/eyeful-emptyroom-manifest.json \
  /tmp/ws-r6-cameras.json examples/bim_eyeful_room/round6/studio/source-camera-calibration.bin \
  /tmp/ws-r6-browser-output
# 上述开发项目生成并编辑完成后，可运行会改变标尺和相机状态的反事实测试。
NODE_PATH=/path/to/node_modules CHROMIUM_PATH=/path/to/chromium \
  node benchmarks/ws_realroom/studio_multiview_scale_lifecycle_browser.cjs \
  http://127.0.0.1:8766 /tmp/ws-r6-lifecycle-output
```

Core 与产品回归：`OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m pytest -q tests products/worldstate_bim/tests`；本轮 209 项通过，IfcOpenShell 给出 Python `utcnow()` 弃用警告。

## 未完成与下一步

当前瓶颈是低纹理导致的稀疏点、墙面语义混淆、近似重复面、未观测边界和没有独立尺度；真实墙角与完整房间拓扑尚未验证。应获取更充分视差和纹理的授权房间照片，或在明确标记输入变化后引入稠密几何和少量人工对应，再用独立测距标尺求解。不能把同图像重建出的相机尺度当独立实测。

新的独立 Room-Test、隐藏尺寸和至少三组人工/辅助配对成本均尚未提供。冻结的 [WS-RealRoom 协议](../../../benchmarks/ws_realroom/PROTOCOL.md)没有改变，精度、precision/recall、人工成本与正式发布均未达成。DSH 项目授权仍缺失，本轮未重复匿名检查；Hunyuan/VGGT GPU 路线未运行。

本轮复核：当前稀疏方法能提供可追溯的三维候选，但不足以证明侧墙实例及边界，应优先比较更好覆盖或稠密几何；用户虽可修订局部 IFC，完整房间和降低人工成本尚未证明；独立软件回写与复现均已检查，实物精度和正式发布门槛仍无结果。
