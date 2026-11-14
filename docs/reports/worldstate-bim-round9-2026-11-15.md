# WorldState BIM 第九轮：基于图像证据的局部墙面

**结果：部分成功，V0.2 NOT RELEASE-READY。** ETH3D kicker 的真实照片产生了一个可编辑 IFC4 门上墙面片段，并在 Bonsai 中编辑、回写；它不是完整墙、完整房间或经过独立公制验收的结果。已知位姿与 Photo-only 两种模式都运行了同一个局部约束求解。没有人为标注、独立墙实例与尺寸真值或真实人工效率实验。

第八轮的 kicker 和 office 已用于开发及扫描诊断，不能作为盲测场景。本轮遵守 ETH3D CC BY-NC-SA 4.0，仅用于非商业研究；原始数据、图像衍生物、IFC 和扫描报告保存在仓库外的本机缓存，不作为商业产品资产。第八轮扫描结果已在本轮部分实验之前查看；本轮冻结用于保证本次候选、代码和输入未在评测步骤中变化，**不代表事先独立或盲测**。

## 实际建模

分析者使用真实开发照片选择黄色门的跨图区域以及墙顶交线搜索区域，OpenCV 再提取颜色轮廓角点和线梯度；这些是 **AI 辅助选择加自动图像处理，不是真人标注**。使用 `DSC_6497.JPG`、`DSC_6508.JPG`、`DSC_6515.JPG`：门上两角各有三张照片，右下角因遮挡仅使用后两张。门扇与墙面共面、门边近似竖直、局部片段矩形是未确认的建模假设。

求解器分别三角化三个真实像素对应，以顶边、门边和墙顶线定义局部坐标及可见片段，不要求全局地面。SciPy `soft_l1` 联合优化角点与顶边重投影，并可使用 PixCuboid 的一个面作为初始候选；它不会把其余闭合面自动当成实际墙体。来自 UPerNet 的每视图 25 个相关采样只合成**一个弱语义约束**，不是 25 个独立测量；语义概率未校准。角点和图像线仍遵循既有 3 px 一致性检查，三角化仍使用既有最小 1° 视差门槛。数据或相机改变后会拒绝使用旧求解。

实测本片段内同时满足两视图轨迹、位于图像候选区域且语义为墙的稀疏轨迹数为 **0**；没有降低支持门槛。当前优化没有使用点到面、深度、公制标尺和完整房间拓扑损失，这些项仍未完成。语义项只能作为弱候选支持，不能证明墙实例正确。上部两个角的最大视差约 21.92° / 24.20°，右下角约 **1.99°**，空间不确定性未量化；局部优化雅可比条件数约 128.7 也不是误差置信区间。

| 模式及模型 | 真实输入与限制 | 拟合视角 RMS | 开发留出视角 RMS |
| --- | --- | ---: | ---: |
| Known-pose，PixCuboid 初始候选 | 使用 ETH3D 官方扫描配准位姿、场景内参 | 78.04 px | 113.14 px |
| Known-pose，像素与语义约束后 | 同上；三个拟合视图，`DSC_6509.JPG` 不参与局部参数优化 | 1.174 px | 2.279 px，最大 4.399 px |
| Photo-only，直接三角化后优化 | 使用照片和本场景官方内参，COLMAP 26/29 注册，**未输入官方位姿与扫描** | 1.168 px | 2.271 px，最大 4.374 px |

这些数值是角点距离与顶线距离组成的重投影一致性，**不是墙面或尺寸精度**。留出视角此前由分析者查看，并参与相机恢复，不能当作盲测或独立验收。Known-pose 和 Photo-only 的相机输入、坐标及尺度不同，不作精度排名。第八轮 PixCuboid 八图先验与本次三个局部观测图也不同；表中前后比较是同一 PixCuboid 初值的修订结果，不是控制变量完整的算法排行榜。

Known-pose 输出片段宽约 0.953、高约 0.334 **源坐标单位**；Photo-only 输出约 1.739 × 0.610 源坐标单位，二者的数值没有可比较的物理尺度。为测试 IFC 编辑，分别显式假设 `1 源单位 = 1 m`、厚度 `0.10 m`，在 IR 与 IFC 证据属性中标记尺度未知、厚度假设和不完整边界；不能将文件中以米表示的值用作实测。门扇与墙面的法向偏移、真实墙厚、完整墙高、遮挡和房间拓扑均未知。优化后的 IFC 只有一个 IfcWall 局部片段，没有生成门、完整墙或隐藏空间。

## 冻结后诊断及可编辑性

冻结候选后，在与官方相机配准的扫描坐标中对两个激光扫描按每 50 点抽样。对 2,100 个片段表面采样点，初始/优化候选到 scan1 最近点距离中位数分别为 0.378 / 0.0207 源单位，到 scan2 分别为 0.279 / 0.0155 源单位。采样和最近点可能选中非墙物体；官方相机本身与扫描配准，因此不是独立公制准确度。

另以**模型限定的区域**从 scan1 自动提议局部平面，筛得 347 个抽样点，scan2 在同一近峰筛选区域有 2,000 点；未由独立人员审核其是否为墙。没有可确认的独立墙面实例、边界、参考 IFC 或独立尺寸，所以实例 precision / recall、墙长 / 墙高误差、布局 IoU 和正式真实房间验收均为 **NOT_MEASURED**。Photo-only 坐标没有被强行对齐到扫描；其扫描对照标记未评测。

Known-pose 原 IFC、Bonsai 编辑版、回写后 IFC 及 Studio 角点修订版均通过 IfcOpenShell IFC4 schema 解析与几何生成，各有一个墙片段，GUID 均为 `3fVWXsYKPTpRbpsSR$wN7f`。Blender 5.2.2 / Bonsai 0.9.0.post1 实际将假设尺度下高度由约 0.333911 改至 0.383911，随后通过 `sync-ifc` 回写 IR；修改不是测量，回写状态为需要重新验证。

本地 Studio 已能加载该 IR/IFC、上传匹配哈希的原始照片、显示当前版本的图像投影、修改墙高，并通过照片中的上角点重新求解，保存新的版本和修改来源。真实 Chromium 自动化运行上传了两张照片、完成高度修改和一个角点修正，版本 2 → 3 → 4，操作者及日志标记 `automation`。角点修正会重新计算并替换当前局部墙面尺寸；视图坐标受显示分辨率影响，错误对应会被拒绝。它目前只支持已有局部候选的门上两角修正，还不能从 Studio 中完成通用的新房间首次建模或编辑所有墙线。Playwright 操作时间不计为真人成本。

## 可复现命令

需要已完成第八轮数据及依赖准备（`benchmarks/ws_geometry/requirements-round2-cpu.txt`）；以下在仓库根目录运行，输出路径须是不存在的新路径。Python 3.12.3、NumPy 1.26.4、SciPy 1.13.1、OpenCV 4.10.0、pycolmap 4.2.1、IfcOpenShell 0.8.4，CPU，未使用 GPU。

```bash
WS_K="$HOME/.cache/worldstate-round8/eth3d/kicker"
WS_OUT="$HOME/.cache/worldstate-round9/reproduction-NEW"
WS_PY=/tmp/worldstate-bim-reset-venv/bin/python
export PYTHONPATH=. OPENBLAS_NUM_THREADS=1

# Known-pose、预先运行的 PixCuboid 及同相机源的 UPerNet 掩膜。
$WS_PY benchmarks/ws_geometry/extract_kicker_lintel.py \
  --input "$WS_K/isolated-dev/input" --reconstruction "$WS_K/runs/known-pose-sfm-corrected" \
  --pixcuboid "$WS_K/runs/pixcuboid-8-padded.json" --masks "$WS_K/runs/known-pose-masks" \
  --output "$WS_OUT/observations"
$WS_PY benchmarks/ws_geometry/run_kicker_model_first.py \
  --training "$WS_OUT/observations/training.json" --pixcuboid "$WS_K/runs/pixcuboid-8-padded.json" \
  --images "$WS_K/isolated-dev/input/photos" --reconstruction "$WS_K/runs/known-pose-sfm-corrected" \
  --assume-metres-per-source-unit 1 --assume-thickness-m 0.1 --output "$WS_OUT/model"
$WS_PY benchmarks/ws_geometry/diagnose_local_wall_tracks.py \
  --training "$WS_OUT/observations/training.json" --reconstruction "$WS_K/runs/known-pose-sfm-corrected" \
  --masks "$WS_K/runs/known-pose-masks" --output "$WS_OUT/track-diagnostic.json"
$WS_PY benchmarks/ws_geometry/evaluate_kicker_local_wall.py \
  --freeze "$WS_OUT/model/freeze.json" --reconstruction "$WS_K/runs/known-pose-sfm-corrected" \
  --holdout "$WS_OUT/observations/holdout.json" --images "$WS_K/isolated-dev/input/photos" \
  --scan-dir "$WS_K/evaluation-private/kicker/scan_clean" --stride 50 --output "$WS_OUT/evaluation"

# Photo-only：不传 PixCuboid 和扫描；相机使用既有照片 SfM 与该场景内参。
$WS_PY benchmarks/ws_geometry/extract_kicker_lintel.py \
  --input "$WS_K/isolated-dev/input" --reconstruction "$WS_K/runs/photo-only-sfm/sparse/0" \
  --camera-mode photo-only --masks "$WS_K/runs/photo-only-masks" --output "$WS_OUT/photo-observations"
$WS_PY benchmarks/ws_geometry/run_kicker_model_first.py \
  --training "$WS_OUT/photo-observations/training.json" --images "$WS_K/isolated-dev/input/photos" \
  --reconstruction "$WS_K/runs/photo-only-sfm/sparse/0" --assume-metres-per-source-unit 1 \
  --assume-thickness-m 0.1 --output "$WS_OUT/photo-model"
$WS_PY benchmarks/ws_geometry/evaluate_kicker_local_wall.py \
  --freeze "$WS_OUT/photo-model/freeze.json" --reconstruction "$WS_K/runs/photo-only-sfm/sparse/0" \
  --holdout "$WS_OUT/photo-observations/holdout.json" --images "$WS_K/isolated-dev/input/photos" \
  --output "$WS_OUT/photo-evaluation"
$WS_PY -m pytest tests products/worldstate_bim/tests
```

如需打开该模型，将 `model/optimized-model.json` 和 `model/optimized.ifc` 分别复制为一个**新目录**中的 `model.json`、`model.ifc`，然后运行：

```bash
$WS_PY -m products.worldstate_bim.studio_server \
  --model-dir /path/to/new-model-directory --workspace /path/to/new-local-workspace --port 8766
```

只在本机访问 `http://127.0.0.1:8766/`，上传相同源照片后查看投影。浏览器回归脚本是 `benchmarks/ws_realroom/model_first_studio_check.cjs`；自动化工作区的 `photo-project.json` 必须将 `operator_kind` 明确设为 `automation`，不得把脚本点击算成人工标注。Bonsai 执行使用既有 `benchmarks/ws_bim/bonsai_parameter_edit.py` 与 `products.worldstate_bim.room_cli sync-ifc`。

## 状态与下一步

- Core 与产品全量回归：**232 passed，55 条第三方弃用警告**；原有 Core 公共契约和冻结验收协议未修改。
- 实验分支基于 `2fec82d`；直接求解和 Studio 修订分别提交。原有五处未提交文件未纳入本轮提交。
- 本轮只有一个未确认的局部墙片段；独立尺度、完整墙边界、三面墙、参考 BIM 和人工成本对照均未实现。没有真实人员及至少三组配对运行，人工效率保持 **NOT_MEASURED**。
- 最小下一步：在 kicker 的另外可见墙面上取得真实人工确认的跨图角点或线约束，并由独立人员审核扫描中的相应构件及边界；再用独立实体标尺恢复尺度。仍无法支持的墙应保持未知。正式 Room-Test 需使用未经开发的新授权场景。
- DSH 项目级授权仍是外部阻断，本轮未重复匿名访问；未合并 main 或发布 V0.2。
