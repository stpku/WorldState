# Round 7 补充：公开会议室失败分析

**这次没有得到可信房间模型。** 本目录的[两墙 IFC 草稿](route-a-ifc/original.ifc)在发现地面语义误分类之前生成：其共同地面先验含有椅腿点，剔除该点后地面支持不足。该 IFC 只用于记录编译、Bonsai 编辑和回写过程，**不得用于交付、尺寸测量或宣称重建成功**。正式 V0.2 仍为 **NOT RELEASE-READY**。

这里使用的是 [Eyeful Tower](https://github.com/facebookresearch/EyefulTower) 中与旧 `raf_emptyroom` 不同名的 `meeting_room` 公开数据。上游声明数据采用 MIT 许可；本场景只作为新增开发数据，**不是独立 Room-Test**，不能用于正式精度或人工成本验收。公开数据的原图未加入仓库；来源 URL、各文件大小和 SHA-256 固定在 `benchmarks/ws_geometry/eyeful-meeting-room-*-manifest.json`。上游 COLMAP 数据由 Metashape 导出，上游说明世界坐标为米，但本例的物理尺度未独立核验。照片 44 对应本场景源模型相机 4；使用原图对应的去畸变内参并随图像分辨率缩放，未借用其他房间的参数。

## 相机注册实验

同一台 CPU 的单次开发运行，均使用相机 44 的 32 张照片、同场景固定标定、4 线程 COLMAP；表中各行的分辨率或输入照片不同，只能诊断注册，不可作为相同输入下的精度排名。时间仅包括特征提取、匹配和建图，不包含下载和视觉推理。

| 输入 | 特征提取最大边长 | 已注册 / 输入 | 稀疏点 | 耗时 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| 从 93 帧中均匀选 32 帧，`images_8` | 1200 px | 2 / 32 | 30 | 1.74 s | 注册不足 |
| 同一组帧，`images_4` | 1200 px | 8 / 32 | 313 | 7.57 s | 注册不足 |
| 同一组帧，`images_2` | 2400 px | 10 / 32 | 568 | 22.33 s | 注册不足；运行退出码为 0，但末尾出现 `BLAS : Bad memory unallocation!` 警告 |
| 前 32 帧连续采样，`images_4` | 1200 px | 0 / 32 | 0 | 5.14 s | 未找到满足初始化条件的图像对 |

更高分辨率没有解决注册；2400 px 仅为实验选项，Studio 默认仍为 1200 px。连续帧覆盖较窄，而且没有找到合格初始对；不能仅凭现有日志断言唯一原因。[完整运行日志](run-logs/)和各行的 `sfm-*.json` 保留全部输入照片哈希、相机参数和运行时间。`images_8` 首次实验也是 2/32；重跑的重投影数值略有差异，不应假设多线程 COLMAP 完全逐字节确定。

## 补充位姿后的同输入结构对照

为区分相机注册与墙面恢复两个问题，本实验额外读取上游含 1302 张图像位姿的同场景重建，为这 32 张照片提供已算好的位姿；只使用源相机、位姿和这 32 张照片新提取的匹配进行三角化，**未使用源点云**。32 个位姿是额外提供的输入，不能写成 32 张照片自行注册成功；相关源模型也不是独立真值。[记录](sfm-known-pose/known-pose-summary.json)中保留源文件哈希，三角化得到 450 个点，平均重投影约 0.787 px。语义模型对 32 图 CPU 推理约 88.88 s；重新融合和墙地线阶段分别约 2.84 s、6.99 s。这些阶段耗时不包含上游提供的位姿求解，也不是端到端成本对照。

同一批照片、相机、450 条轨迹和语义掩膜输入下：

- 路线 A（语义轨迹和平面）得到 3 个待核验墙面假设，分别由 89 点/27 图、39 点/19 图、35 点/18 图支持；其中两个方向不同的候选被转换为 IFC 草稿。候选不等于已确认的独立墙实例，墙段也不是完整真实边界。
- 路线 B（多视图墙地线）得到 154 条二维线和 4 组三维线，分别由 17、14、8、3 张照片支持；前三组与稀疏地面冲突，第四组的地面约束逐视图剔除诊断不通过，**0 组满足导出条件**。路线 B 使用路线 A 的地面先验，是混合路线；逐视图剔除只发生在拟合阶段，并非独立留出照片评测。[对照数据](diagnostics/diagnostics.json)、[三维结构](diagnostics/structure.json)和[原图候选叠加](diagnostics/overlays/)保留所有失败候选。

## 已发现的地面误分类

地面平面仅由 8 个三维点、10 张照片支持。检查两张原图中的 track 120，其对应像素实际落在椅腿上，但两张图都被语义模型归为地面；[第一张裁剪](floor-probe/track-120-view-1.jpg)、[第二张裁剪](floor-probe/track-120-view-2.jpg)中的红圈标出原始像素。该判断来自对原图的开发检查，不是人工成本实验或完整地面真值。

不改变最低 8 点要求、删除规则或拟合参数，只排除这一个有明确视觉问题的轨迹后，其余地面候选无法组成满足现有条件的平面：由 1 个候选变为 **0 个**。拟合距离阈值按算法既有规则由剩余点范围重新计算，未为产生结果而放宽。[逐图来源与重算记录](floor-probe/probe.json)可复核。这说明之前的地面及依赖它的墙体位置不可信；目前无法判断其他候选是否正确，也不能因此把某一条冲突线自动当作墙。

## IFC 和外部软件检查

在发现以上问题之前，路线 A 将两个不同方向的平面候选编译为[局部 IFC](route-a-ifc/original.ifc)。为能运行已有 IFC 流程，它采用源重建坐标按米解释的**未独立核验假设尺度**，以及明确假设的 0.12 m 墙厚；尺度端点是自动选取的重建特征，不是物理标尺。[尺度假设](source-frame-assumption.json)和[标尺记录](route-a-ifc/anchor-assumed.json)不可作为实测。此 IFC 在 Blender 5.2.2 / Bonsai 0.9.0.post1 中经脚本将一墙高度改为 2.5 m，之后[回写 IR 和 IFC](bonsai-synced/)；原始、Bonsai 保存及回写三个 IFC 均独立生成两面墙的几何、schema 错误为 0，两个 GUID 均保持。详见[Bonsai 报告](bonsai-report.json)与[独立解析记录](bonsai-synced/ifc-checks.json)。它们只验证可编辑性，不验证墙是否真实或准确；脚本运行时间不计为人工作业。

## 复现已保存结果

安装根目录 `benchmarks/ws_geometry/requirements-round2-cpu.txt`，然后在仓库根目录执行。这里使用已保存的实际位姿三角化、掩膜和语义融合文件；图像下载及校验不会上传本地数据。`/tmp/ws-meeting-*` 应为新目录。

```bash
export OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
WS_PY=/path/to/venv/bin/python
WS_EXAMPLE=examples/bim_eyeful_room/round7/meeting_room_dev
$WS_PY benchmarks/ws_geometry/fetch_eyeful.py \
  --manifest benchmarks/ws_geometry/eyeful-meeting-room-images4-manifest.json \
  --output /tmp/ws-meeting-images4
$WS_PY benchmarks/ws_geometry/run_structure_diagnostics.py \
  --sparse "$WS_EXAMPLE/sfm-known-pose" --images /tmp/ws-meeting-images4 \
  --masks "$WS_EXAMPLE/masks-known-pose" --output /tmp/ws-meeting-diagnostics
$WS_PY benchmarks/ws_geometry/probe_floor_misclassification.py \
  --fusion "$WS_EXAMPLE/fusion-original.json" --images /tmp/ws-meeting-images4 \
  --exclude-track-id 120 --inspection 'Visual inspection: both source pixels fall on a chair leg.' \
  --output /tmp/ws-meeting-floor-probe
$WS_PY benchmarks/ws_geometry/run_multiview_room_example.py \
  --fusion "$WS_EXAMPLE/fusion-original.json" \
  --correlated-reference "$WS_EXAMPLE/source-frame-assumption.json" \
  --output /tmp/ws-meeting-ifc-untrusted
```

从照片重新计算，可先以同样下载器和 `eyeful-meeting-room-calibration-manifest.json` 获取上游源模型，再用 `run_same_scene_sfm.py` 运行实际注册，并用 `run_known_pose_triangulation.py` 显式提供上游位姿；需要重新运行 `run_multiview_fusion.py infer` 才能为新相机结果生成匹配的掩膜。其逐次轨迹 ID 不保证相同，不可把本例 track 120 的编号直接用于另一次求解。四次注册的输入与设置如上表所示，另见[日志](run-logs/)和对应的几何结果文件；较早生成的 `images_4` 结果采用原有的 1200 px 固定默认值，当时尚未在 JSON 中单独记录该值。

实际重新下载并校验 32 张 `images_4` 照片后，使用保存的相机和掩膜重跑，上表中的三个墙面假设、四组线及全部拒绝结果一致；排除 track 120 后仍无合格地面。按上述命令重编译 IFC，两个 GUID 与原草稿一致。Core 和产品的 213 项测试通过；IfcOpenShell 有上游 `datetime.utcnow()` 弃用警告。

## 仍然阻断的验收

尚无独立 Room-Test、物理标尺和留出尺寸，也没有至少三组真实人工与辅助建模配对记录；墙实例 precision/recall、尺寸误差和人工时间均为 **NOT_MEASURED**。已冻结的 WS-RealRoom 验收协议没有变更。最小下一步是在真实授权开发房间获取覆盖三面墙且具备足够视差的照片与独立物理尺度，并针对地面误分类补充可靠的前景排除或少量人工确认；之后用未参与调试的独立房间按冻结协议验收。DSH 项目级授权仍待管理员提供，本轮未再次尝试匿名访问。
