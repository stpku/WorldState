# Round 7：低纹理墙地线与部分 IFC

**结果：仍不能证明新真实房间可以更省人工地生成合格 BIM。V0.2 为 NOT RELEASE-READY。** 以下原始对照使用第六轮已公开的 Eyeful Tower 开发照片；尚无自有授权验收房间、独立标尺、隐藏测量或真实人工成本，不是正式验收集。

后续增加了不同的公开 `meeting_room` 开发场景，并保留[完整实验与失败分析](meeting_room_dev/README.md)：自有 COLMAP 最高只注册 10/32 张，引用额外公开位姿后发现地面支持点将椅腿误识别为地面。该场景的两墙 IFC 因此仅用于编辑流程测试，几何不可信，也不是正式验收结果。

## 同输入对照

两条路线复用同一个 32 张照片的 COLMAP 重建，其中 28 张注册成功、446 条轨迹；照片、相机和 UPerNet 掩膜哈希见[完整对照](comparison.json)。它们使用同一个相关重建推得的**假设尺度**，以及相同的 2.3 m 假设高度和 0.12 m 假设厚度。这些数值不是现场测量。

| | 路线 A：语义轨迹与平面 | 路线 B：多视图墙地线 |
| --- | --- | --- |
| 输入 | 相同相机、语义掩膜与 446 条三维轨迹 | 相同相机与掩膜；同时使用 A 的稀疏地面作关联和一致性先验 |
| 可检查候选 | 两个导出候选，分别由 182 点/28 图、18 点/22 图支持 | 123 条二维线，形成 4 组三维线假设；其中 2 组通过当前一致性诊断并导出 |
| 假设尺度下的可见支持范围 | 约 4.411 m、2.772 m | 约 6.687 m、1.658 m |
| IFC | [两墙草稿](route-a.ifc)，IFC4 几何生成通过 | [两墙草稿](route-b.ifc)，IFC4 几何生成通过 |
| CPU 阶段耗时 | 约 3.24 s | 约 5.63 s |

这只是同机开发诊断：共同的照片注册和语义推理耗时不包含在表中。两组支持范围来自不同的可见片段，不能当作完整墙长或逐项实测误差；也尚未独立证明候选的一一对应。候选数量、重投影误差和拟合残差均不能代替墙实例 precision/recall 或独立实测尺寸，不能据此声称一条路线更准确、更省人工。路线 B 是依赖共享地面先验的**混合路线**，并非完全独立的系统。

同机重新运行对照脚本后，二维线清单的 SHA-256、两路线的 IFC GUID、候选范围和结构诊断结果一致；阶段耗时另行记录，未进行稳定性能基准。

## 真实结构结果与失败

- 路线 B 根据语义墙地边界生成图像线段，逐图核对来源及哈希，并从跨视图反投影平面求自由三维线；地面约束仅用于关联和一致性检查。线段端点标为图像边缘或未确认片段端点，没有自动补齐完整墙长，也没有强制闭合房间。
- 四组线分别得到 28、13、4、3 张图支持。第三组的地面约束逐视图剔除诊断最大误差为 **14.57 px**，高于由掩膜像素分辨率确定的 12 px 容差；自由三维线对应诊断最大误差为 **156.59 px**，因此未导出。第四组的自由线与共享地面方向冲突，也未导出。平行候选根据可见范围内的位置进行区分，但仍不是经过核验的物理墙实例。
- 系统从真实图片的候选线交点得到三个跨图角点候选。一个最大重投影误差约 2.20 px、相对尺度地面残差约 0.036；另一个虽然重投影误差约 3.37 px，其相对尺度地面残差约 **0.376**，与地面候选冲突；第三个也存在地面冲突。这些点都不是已确认实物角点，IFC 没有自动连接墙体。[照片叠加图](overlays/)保留候选和冲突。
- 逐视图剔除只在拟合线上暂时去掉该图；最初的线关联、相机和地面仍使用全部开发照片。它是敏感性检查，不是独立留出视角或工程精度。
- [线段选择对照](line-selection-probe.json)对第三组使用每张图中更长的候选，地面约束诊断最大误差从 14.57 px 降到 8.43 px，但自由三维线的对应误差仍有 **109.11 px**。这表明结果高度依赖共享地面，不能据此宣称第三面墙已经可靠；正式候选和容差均未因这一事后开发实验调整。
- Bonsai 原生算子将路线 B 一段墙的**假设高度**从 2.3 m 改为 2.5 m，随后[回写 IR 与 IFC](bonsai-synced/)；两个 GUID 保持不变。IfcOpenShell 对原始、Bonsai 修改和回写后的 IFC4 均生成两墙几何，schema 错误为 0。这是脚本操作，不是实测或人工成本实验。

## Studio 和开发预览

已有 Studio 现在可对注册照片求解墙地线、查看每条候选的支持图和冲突、选择符合当前诊断的部分候选并导出 IFC。用户可在两张已注册照片中以相同角点编号标记同一物理点；系统会三角化并记录标注来源，但不会自动把墙连接到该点。修改角点后，旧结构结果必须重新求解。用户测量的墙高需要提供来源和不确定性；假设高度须明确标为假设。

[浏览器记录](studio/browser-result.json)和[本地录屏](studio/demo.webm)使用的是另一批第六轮真实开发重建：28 张注册照片、**476 条轨迹**。该批地面候选不同，只有一条线通过当前诊断；[Studio IFC](studio/revised.ifc)因此只有一墙。脚本根据实际 AI 像素候选模拟两次标点、触发旧结果失效、重新求解并修改墙高，记录为 `automation`，不是人类标注或耗时；与上面的 446 轨迹对照不混算。两次 Studio 导出的 IFC 均独立解析并保持相同 GUID。

地面轨迹去重修复后，使用该 **476 轨迹**旧开发项目重新完成[浏览器生成、编辑与导出](studio-floor-fix/browser-result.json)：一条候选通过，IFC 修改前后独立几何生成成功且 GUID 保持。该运行仍是脚本操作和假设尺度，不是新房间验收或人工成本数据。

## 复现

依照 [Round 6 说明](../round6/README.md) 安装固定 CPU 依赖并下载公开照片；原图和模型权重不在仓库中。数据及模型的许可记录见 [Eyeful Tower MIT 许可](../LICENSE.eyeful.txt)和 [UPerNet 导出许可](../../../benchmarks/ws_structure/LICENSE.upernet-export.txt)。以下命令的 `--images` 指向已核验的公开照片目录；输出目录须不存在：

```bash
export OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_structure_comparison.py \
  --sparse examples/bim_eyeful_room/round6/sfm --images /tmp/ws-r6-images \
  --masks examples/bim_eyeful_room/round6/masks \
  --anchor examples/bim_eyeful_room/round6/ifc/anchor-assumed.json \
  --assumed-height-m 2.3 --assumed-thickness-m 0.12 \
  --output /tmp/ws-r7-comparison-new
/tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/probe_line_selection.py \
  --fusion examples/bim_eyeful_room/round6/fusion.json \
  --structure /tmp/ws-r7-comparison-new/structure.json --output /tmp/ws-r7-line-selection-new.json
```

本地 Studio 只监听 `127.0.0.1`；用新的仓库外工作区启动后，可上传授权照片并按界面完成标尺、候选检查与导出：

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python \
  -m products.worldstate_bim.studio_server --workspace /tmp/ws-room-dev \
  --port 8766 --vision-model /path/to/verified-upernet.onnx
```

真实浏览器运行脚本为 `benchmarks/ws_realroom/studio_round7_structure_browser.cjs`，它使用已有的真实照片项目，自动化标注和编辑仅用于功能测试。Core 与产品共 213 项测试通过；回归命令为 `OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m pytest -q tests products/worldstate_bim/tests`。

## 正式验收阻断与最小下一步

尚无带真实标尺的项目自采 Room-Dev 和独立 Room-Test，也没有三个隐藏测量、参考 IFC、留出照片或三组人工/辅助配对实验；实例指标、尺寸误差和人工成本均为 **NOT_MEASURED**。现有 [WS-RealRoom 冻结协议](../../../benchmarks/ws_realroom/PROTOCOL.md)及其 `init_room.py`、`evaluate.py` 未改变。DSH 仍待项目级授权，本轮未检查凭据。

下一步是在 Room-Dev 采集覆盖三面墙与角点、具有足够视差的授权照片和真实物理标尺，优先验证第三组线的跨视图一致性及地面冲突；独立保管尚未用于调参的 Room-Test，再由评测人员按冻结协议测量精度与人工成本。
