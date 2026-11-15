# WorldState BIM 第十轮：通用多视图构件建模

**结果：通用建模入口和部分真实数据闭环已运行；三面真实墙及独立验收未完成，V0.2 仍为 NOT RELEASE-READY。** 通用求解器不依赖照片文件名、颜色或固定裁剪；现有 Studio 可以新建墙面候选、跨图标注、查看建议、求解、修订和导出。真实浏览器及 Bonsai 演练使用的还是第九轮 kicker 同一门上局部证据，不能称为新墙、新房间或真人试验。

原有五处用户未提交文件、Core 公共契约和 `WS-RealRoom` 冻结协议均未修改。ETH3D kicker、office 都已用于开发；按项目现有许可记录仅在 CC BY-NC-SA 4.0 允许的非商业研究范围使用，照片、扫描、模型衍生物和演示截图留在本机缓存，不作为商业资产发布。

## 可使用的能力

- `products/worldstate_bim/general_modeler.py` 接收绑定原图 SHA-256、完整相机参数快照哈希、对象与特征 ID、来源、确认状态、原始像素、可见性、像素不确定度和时间的点、线及平面语义观察。跨图同名点构成对应；不可见、拒绝及未接受建议不参与求解。相同像素不允许冒充多个无关联特征，重叠共面候选需要先审核。
- 普通多边形模式对多个构件的三维顶点和显式平行、垂直、共面、相交/重合约束联合优化；三点以上的非矩形表面可保留为候选，不会自动闭合房间。对象约束必须记录来源、两侧照片证据、时间及声明的不确定度。语义平面目前只记录、不参与该模式优化；对象关系尚无 Studio 编辑入口。
- 边到线模式复用既有局部几何：两点构成已观测边，第三个物理点声明方向，两张以上照片提供对边线。对边两个端点和矩形形状是**推断/假设**，并非真实标注的角点；该模式目前一次只支持一个构件，暂不支持跨对象联合约束。它保留每个观测的像素不确定度，但旧求解路径仍使用统一 3 px 稳健尺度，没有按各自不确定度加权。
- 求解检查相机模型、像素及版本绑定、同名点对应、视差、退化、平面条件和既有的 3 px 重投影一致性门槛。提供可复现的像素、相机位置/旋转及焦距扰动；这些扰动幅度是声明的假设，采样失败有计数，接受样本的百分位有选择偏差，**不是经过标定的几何误差或可信区间**。
- IFC 编译沿用 Room IR 与现有编译器：只有显式接受、通过矩形及竖直近似检查的四顶点候选才编译为墙片段；墙厚、朝上方向和尺度的假设会记录。可复用既有跨图物理标尺求解，Studio 会检查标尺端点与当前观察一致；改变观察后旧解和导出入口失效。非矩形、未知边界或冲突不会被静默挤出为完整墙。
- Studio `/modeler` 使用本地上传的照片和已注册相机清单，支持并排视角、原始像素局部放大点选、线段、可见/遮挡标记、三维候选、图像投影和版本化 IFC。COLMAP 轨迹只提供待接受/拒绝的确定性匹配建议，重复轨迹被标记；配置现有 UPerNet 后也可查看视觉区域与线段并明确接受/拒绝。AI、脚本及真人来源分别记录，视觉建议不是已验证墙实例。该入口不提供自动语义去遮挡或完整自动房间恢复。

本轮新引入的候选筛选参数是工程启发式：平面拟合 RMS 不超过该候选直径的 2%，明确接受的 IFC 矩形近似顶点调整不超过候选宽/高较大值的 2%。只有三个点时共面残差天然为零，不能用来证明真实表面。上述参数不能当作独立几何精度或 WS-RealRoom 发布容差；原有 3 px 一致性检查和正式验收门槛未放宽。

## 本轮真实运行

| 运行 | 可检查结果 | 不能据此声称 |
| --- | --- | --- |
| kicker / 第九轮已有局部输入，经通用边到线模式 | 三张真实照片、8 个自动角点观察与 3 条自动线观察；重投影点/线混合 RMS **1.174 px**，生成 1 个 IfcWall 局部草稿。相机使用官方扫描配准位姿；标尺与 0.10 m 厚度为假设。 | 新物理墙、完整墙、独立公制精度或真人标注。门扇与墙共面未确认。 |
| kicker / 同一通用多边形求解器 | 三组自动语义特征平面提议：一组因重投影超 3 px 拒绝，两组在同坐标系联合求解，点 RMS 1.344 px；两组均被矩形/竖直 IFC 门槛拒绝。 | 两面或三面有效墙。图像复核显示其中一组穿过柜体及物品，另一组边界跨越遮挡，特征凸包不是实际墙边。 |
| office / 不改求解器 | 四组自动特征凸包可在同坐标系联合求解，点 RMS 1.269 px；四组均被 IFC 门槛拒绝。 | 已完成跨房间可用 IFC；照片中候选混合家具、白板或未确认边界。 |
| 浏览器 / kicker | 在真实照片上上传、导入相机、新建构件、用放大图进行脚本点线标注、求解、重新标注及导出版本 1/2；同一构件 GUID 保持。另运行真实 UPerNet 视觉线建议，接受记录为 `ai_suggested`、`accepted_by: automation`。 | 真人标注、真实人工耗时或新房间验收。 |

通用模型的真实候选来源于 COLMAP 与 UPerNet 墙语义轨迹，模型名、图像和相机哈希记录在缓存；UPerNet 把柜体等错判为墙的情况仍存在。选择的四个特征连接得到的是**特征凸包**，线段可能跨过遮挡，不是观察到的真实墙体范围。没有为获得三墙结果降低已有支持或重投影阈值。

对同一门上片段，在 2 px 像素扰动、0.002 源单位相机平移、0.05° 旋转和 0.001 焦距比例扰动的**假设**下，24 次采样中像素模式拒绝 15 次、相机模式拒绝 24 次、联合模式拒绝 23 次。该点集包含约 1.99° 视差的方向点；高拒绝率提示既有 3 px 检查与这些扰动不相容，不能由很低的重投影残差推断几何可靠。其余通过样本的统计受筛选影响，不应当成精度。

真实 IFC 经过 IfcOpenShell 的 IFC4 schema 与几何检查，并由 Blender 5.2.2 / Bonsai 0.9.0.post1 实际将假设尺度下墙片段高度由约 0.333879 改为 0.383879，再通过 `sync-ifc` 回写；原始、Bonsai 编辑和回写 IFC 的 GUID 均为 `3AO3U58HXS4vDq3n8RqxyU`。用户界面的两次导出也保留同一 GUID；所有尺寸仍须重新验证。

## 扫描参考及人员阻断

`propose_scan_reference_planes.py` 仅读取原始两站扫描及其配准，不接收候选 IFC、候选位置或边界。全场按每 100 点抽样、0.05 源单位体素去重，得到 64,245 体素；全局 RANSAC 产生 9 个平面提议，其中 4 个在假设源坐标 z 轴向上时近似竖直。每个提议的点云 PLY、哈希和两站对同一拟合面的支持统计已写入外部缓存，供独立审核；它们可能是家具，也可能合并/分裂墙面。两站统计使用共同拟合面，并不是独立精度。

尝试使用现有 Open3D 0.19 环境时，导入先因缺少 `plotly` 失败；在隔离虚拟环境补充 `plotly` 和 `dash` 后又因缺少 `sklearn` 失败。因此本次全场分割实际使用可复现的 NumPy RANSAC，**没有 Open3D 实测结果**。

尚无独立评测人员审核平面类别、墙实例、可信范围及独立尺寸，也没有与候选进行有审核依据的对象匹配或参考 IFC。扫描点云候选不等于已审核参考；墙实例 precision/recall、独立尺寸误差、留出图精度均为 **NOT_MEASURED**。正式 Room-Test 仍需未参与开发的新授权场景。

可由真实人员执行的 A/B 任务及空白记录见 [`MODELER_PAIRED_TASK.md`](../../benchmarks/ws_realroom/MODELER_PAIRED_TASK.md)。没有真人参与及至少三组有效配对运行，人工成本和效率保持 **NOT_MEASURED**；自动化浏览器操作不计人工成本。

## 复现和使用

需要第八、九轮已验证缓存、Python 3.12 和 `benchmarks/ws_geometry/requirements-round2-cpu.txt`；以下输出路径必须不存在。运行在仓库根目录，外部数据与结果不得提交到 Git。

```bash
WS_K="$HOME/.cache/worldstate-round8/eth3d/kicker"
WS_O="$HOME/.cache/worldstate-round8/eth3d/office"
WS_OUT="$HOME/.cache/worldstate-round10/reproduction-NEW"
WS_PY=/tmp/worldstate-bim-reset-venv/bin/python
export PYTHONPATH=. OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4

# 同一通用接口重跑第九轮输入：已知位姿、自动像素、假设尺度。
$WS_PY benchmarks/ws_geometry/run_generalized_legacy_patch.py \
  --legacy-input "$HOME/.cache/worldstate-round9/kicker/observations-v2/training.json" \
  --images "$WS_K/isolated-dev/input/photos" --up 0 0 1 \
  --assume-metres-per-source-unit 1 --assume-thickness-m 0.1 --output "$WS_OUT/legacy-patch"

# 导出通用相机及待确认轨迹清单，再由 Studio 上传哈希匹配的原始照片。
$WS_PY benchmarks/ws_geometry/export_modeler_cameras.py \
  --reconstruction "$WS_K/runs/known-pose-sfm-corrected" --images "$WS_K/isolated-dev/input/photos" \
  --camera-mode known-pose --include-tracks --output "$WS_OUT/kicker-cameras.json"
$WS_PY -m products.worldstate_bim.studio_server --workspace "$WS_OUT/studio" \
  --vision-model "$HOME/.cache/worldstate-round5/upernet-convnext-tiny-ade.onnx" --port 8766
```

浏览器本机访问 `http://127.0.0.1:8766/modeler`，创建项目并上传照片后导入清单。普通多边形需为每个顶点在至少两个视角标注同一物理点；边到线模式使用 `p1/p2`、方向点 `p5` 以及至少两视图的 `p3–p4` 对边线。无独立尺度时只能明确选择假设尺度。图像局部放大点选使用原始照片的 200×200 裁剪，不改变原照片或观测坐标。

以下开发评测先从已有相机和掩膜生成语义轨迹，再调用**同一**通用候选脚本；`--up` 只是搜索假设。扫描提议脚本不接收这些候选。

```bash
$WS_PY benchmarks/ws_geometry/run_multiview_fusion.py fuse \
  --sparse "$WS_K/runs/known-pose-sfm-corrected" --images "$WS_K/isolated-dev/input/photos" \
  --masks "$WS_K/runs/known-pose-masks" --output "$WS_OUT/kicker-fusion.json"
$WS_PY benchmarks/ws_geometry/run_modeler_surface_probe.py \
  --fusion "$WS_OUT/kicker-fusion.json" --images "$WS_K/isolated-dev/input/photos" \
  --up 0 0 1 --output "$WS_OUT/kicker-probe"
$WS_PY benchmarks/ws_geometry/run_multiview_fusion.py fuse \
  --sparse "$WS_O/runs/known-pose-sfm" --images "$WS_O/isolated-dev/input/photos" \
  --masks "$WS_O/runs/known-pose-masks" --output "$WS_OUT/office-fusion.json"
$WS_PY benchmarks/ws_geometry/run_modeler_surface_probe.py \
  --fusion "$WS_OUT/office-fusion.json" --images "$WS_O/isolated-dev/input/photos" \
  --up 0 0 1 --output "$WS_OUT/office-probe"
$WS_PY benchmarks/ws_geometry/propose_scan_reference_planes.py \
  --scan-dir "$WS_K/evaluation-private/kicker/scan_clean" --output "$WS_OUT/scan-proposals.json" \
  --artifacts "$WS_OUT/scan-review" --stride 100 --voxel-source 0.05 --distance-source 0.03
$WS_PY -m pytest tests products/worldstate_bim/tests
```

扫描 PLY 应由未查看候选模型的评测人员结合两站数据独立审核，记录墙/家具/未知、实例与可信边界、测量方法和不确定度，冻结参考后再执行匹配；当前尚无此审核结果。Bonsai 回写使用既有 `benchmarks/ws_bim/bonsai_parameter_edit.py` 和 `products.worldstate_bim.room_cli sync-ifc`。

本机 Bonsai 验证可在新目录中按以下方式重做；`0.383878717` 仅为脚本修改后的假设尺寸。路径需指向本机已安装的 Blender/Bonsai。

```bash
WS_EDIT="$WS_OUT/bonsai-NEW"
mkdir -p "$WS_EDIT"
BLENDER_USER_CONFIG="$HOME/.cache/worldstate-round2/blender-config" \
BLENDER_USER_EXTENSIONS="$HOME/.cache/worldstate-round2/blender-extensions" \
  /home/dev/work/aigc-3d/tmp/blender-5.2.2-linux-x64/blender -b --python-exit-code 1 \
  --python benchmarks/ws_bim/bonsai_parameter_edit.py -- "$WS_OUT/legacy-patch/model.ifc" \
  height '3AO3U58HXS4vDq3n8RqxyU' 0.383878717 "$WS_EDIT/edited.ifc" "$WS_EDIT/report.json"
$WS_PY -m products.worldstate_bim.room_cli sync-ifc \
  --model "$WS_OUT/legacy-patch/model.json" --baseline-ifc "$WS_OUT/legacy-patch/model.ifc" \
  --edited-ifc "$WS_EDIT/edited.ifc" --element-id wall-patch --attribute height \
  --operator analyst --reason 'Automated editor regression, not a measurement' --output-dir "$WS_EDIT/synced"
```

自动化浏览器脚本在 `benchmarks/ws_realroom/general_modeler_edge_browser.cjs`、
`general_modeler_browser.cjs` 和 `general_modeler_vision_check.cjs`；需要本机
Playwright/Chromium 和单独的测试工作区，且该测试项目必须将 `operator_kind`
设为 `automation`。不得将测试操作作为真人确认或人工效率数据。

## 当前发布判断

本轮代码提交 `27037d6`、`4f10194`、`c1bd5dd` 分别对应通用求解、Studio 和开发评测；Core 与产品全量回归 **239 passed，59 条第三方弃用警告**。

本轮没有三个经验证的不同墙面，也没有 office 真实有效 IFC、独立扫描参考尺寸、真人配对成本或正式 Room-Test。DSH 仍为外部授权阻断，未重复匿名访问。下一步应由真实人员使用通用界面确认 kicker 上三个确实属于不同墙面的跨图观察，并由独立人员先审核扫描参考；如果照片不支持这些对应，应保留未知而非以家具或封闭先验补墙。正式 V0.2 门槛没有降低。
