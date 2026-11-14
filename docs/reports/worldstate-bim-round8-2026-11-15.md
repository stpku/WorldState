# WorldState BIM 第八轮：ETH3D 开发场景与结构恢复

**结论：尚不能交付新场景的可靠 IFC，V0.2 仍为 NOT RELEASE-READY。** `office` 的稀疏地面支持不足；`kicker` 虽产生三个墙面候选，但其地面拟合使用了家具支架上的误分类轨迹，且缺少独立尺度与可确认边界。排除一组经过照片复核的重复误分类观测后，地面候选消失；没有降低阈值或将封闭长方体当作实际房间。缺少独立墙实例标注、独立尺寸、参考 IFC 和真人配对实验，precision、recall、尺寸误差、真实人工成本均为 **NOT_MEASURED**。

本轮依据 [ETH3D 官方数据与许可](https://www.eth3d.net/)和[数据格式说明](https://www.eth3d.net/documentation)执行非商业研究。数据及照片衍生叠加图留在仓库外；没有提交原始数据、扫描、模型权重或照片。两个场景都是 ETH3D 官方训练数据中的**开发场景**，不是 WS-RealRoom 独立 Room-Test；冻结协议未修改。

## 数据、许可与隔离

| 文件 | 字节 | 本地计算的 SHA-256 | 完整 7z CRC |
| --- | ---: | --- | --- |
| office_dslr_undistorted.7z | 288765137 | `316c0c10c79cc173e4b5c26102fed3caedbde7e1865fd896ae15423f0f8cf04c` | 通过 |
| office_scan_clean.7z | 296246589 | `ac7b15a29302931b85f48d1c33255268ca1d551d986e72bd38dab81ed3679570` | 通过 |
| kicker_dslr_undistorted.7z | 433074686 | `cc4ee2c119f296dc8f8fbce97fd76a25ce2f21d983bf81b2ca0f7849949fc070` | 通过 |
| kicker_scan_clean.7z | 362446109 | `d95a6fa02589e10df6c3311ee04bfb0e63d8ca0c8c9a521471a571c1cff06035` | 通过 |

两个 office 文件的长度与任务中提供的值一致；kicker 是另一组不同文件。以上哈希为本机计算，**并未与官方发布的独立 SHA-256 清单比对**；CRC 检查证明压缩包内部完整，不证明源站签名。ETH3D 数据采用 CC BY-NC-SA 4.0，只能在符合许可的非商业范围内使用，不能作为商用产品资产。

- `office`：26 张去畸变照片；24 张建模，`DSC_0254.JPG`、`DSC_0255.JPG` 留出。照片中地面和墙被家具部分遮挡；无法仅凭照片确认三面独立墙均可测量。
- `kicker`：31 张照片；29 张建模，`DSC_6519.JPG`、`DSC_6520.JPG` 留出。多方向墙面和地面可见，但书架、白板、桌椅及低纹理造成遮挡和语义歧义。
- Photo-only 只使用建模照片和该场景的官方 PINHOLE **内参**，未读取官方位姿、扫描或留出照片；尺度未知。Known-pose 额外使用本场景官方位姿，不能称作自动位姿恢复。两种模式分别记录。
- 扫描解压在 `evaluation-private`，建模输入在 `isolated-dev/input`。候选、运行摘要及源代码快照先哈希冻结，随后评测才读取扫描点。官方位姿与扫描配准相关，照片路线对齐时又拟合了相似变换；扫描是额外传感器数据，但这**不是完全独立的尺度或相机精度验收**。
- 扫描数据没有现场测距记录或经独立人员标注的墙体/房间参考 IFC。扫描衍生的诊断不能冒充现场人工测量，也未由独立评测人员完成语义标注。

## 真实运行

Linux x86-64、Python 3.12、CPU、pycolmap 4.2.1、ONNX Runtime 1.20.1、IfcOpenShell 0.8.4；未使用 GPU。语义模型为已有 UPerNet ConvNeXt-Tiny ADE20K，模型 SHA-256 为 `fea729ab6c5d338bc79ad3d986b073e6faa12c97255eafd78a1f7145326e534e`。重投影误差和同一批点的平面拟合残差都不等于独立墙体尺寸误差。

| 场景 / 输入 | 实际运行 | 结果与限制 |
| --- | --- | --- |
| office / Photo-only，24 图 | COLMAP CPU 4 线程 | 注册 16/24，相对尺度 492 点，平均重投影 1.183 px；总计 22.41 s。UPerNet 对注册 16 图用时 47.57 s。2 个地面轨迹去重后仍仅 2 个；无地面或墙面候选，墙地线求解因地面不足而未运行。 |
| office / Known-pose，24 图 | 提供全部 24 个官方姿态并固定 | 505 点，平均重投影 1.375 px；UPerNet 24 图用时 71.54 s；2 个地面轨迹，仍无可靠地面。官方姿态是额外输入。 |
| office / 相同 8 图、相同 Known-pose | 稀疏语义轨迹与 PixCuboid 分别运行 | 稀疏路线 216 点但无地面/墙面；PixCuboid 约 25.71 s 得到待验证闭合长方体，语义地面像素在 4 图支持其一个先验面。该面未自动确认，不代表独立地面精度。 |
| kicker / Photo-only，29 图 | COLMAP CPU 4 线程 | 注册 26/29，2722 点，平均重投影 1.096 px，40.82 s；UPerNet 26 图 81.37 s。13 条地面轨迹去重为 10 条，出现 1 个使用 8 点的拟合面和 3 个墙面候选；墙地线有 2 条二维提议，但无可导出的三维线或角。 |
| kicker / Known-pose，29 图 | 固定 29 个官方姿态 | 2654 点、平均重投影 1.211 px；固定姿态与归一化后的官方姿态矩阵最大差约 `4.44e-16`。不得与 Photo-only 按输入相同直接排名。 |
| kicker / 相同 8 图、相同 Known-pose | 两条路线及同一 UPerNet 权重 | 稀疏路线 846 点、0 地面支持、0 墙面；PixCuboid 在 CPU 上 25.43 s 返回闭合长方体候选。8 图中有 8 图的部分地面语义像素落在其一个先验面，其他面也有冲突支持；没有自动确认地面。 |
| kicker / 相同 8 图、相同 Known-pose，扫描摘要已查看后追加 | Depth Anything V2 Small + 同图稀疏点标定 + UPerNet | 8 图推理共 12.18 s（不含加载与图像处理）；6 图的拟合通过预设的同源稀疏诊断门槛，2 图没有可用稀疏点。6 图的地面语义像素融合产生一个未确认平面；它不是独立公制重建或可交付地面。 |

`kicker` 的初次 PixCuboid 运行因 480×721 输入触发上游 U-Net 上采样形状断言而失败，日志保留在缓存。第二次只在右边/底边补零至 16 的倍数，沿用经缩放的相机尺寸和内参，成功产生候选；补零可能影响预测，必须算作该实验的预处理。模型没有输出 IFC，长方体闭合和 Manhattan 假设不能证明被遮挡墙面存在。office 16 图 PixCuboid 进程以 137 退出，原因未确认；8 图进程记录峰值约 4.43 GiB。不同图数、预处理和输入条件下的结果不作精度排名。

`kicker` 照片复核定位轨迹 `1134` 在家具支架上，轨迹 `1135` 与它在至少两个视图使用相同像素。按原有规则一并排除这组观测后，10 条独立地面轨迹变为 9 条、地面拟合从 1 个变为 0 个；最小支持数始终为 8。裁剪图和源照片哈希由 `render_floor_review.py` 可复现。该复核是分析者的开发诊断，不是独立真值或真人效率试验。

补充的相对深度路线使用 [Depth Anything V2 Small 的固定社区 ONNX 导出](https://huggingface.co/onnx-community/depth-anything-v2-small)（模型卡标注 Apache-2.0；权重预训练与本场景是否重叠未知）。该路线不读取参考扫描，也不把相对深度直接当作公制深度：每图使用同一照片集三角化得到的稀疏点拟合逆深度的尺度及偏移，再以固定已知位姿融合。23 个有重叠的**有向**视图对产生 1107 个地面语义像素比较，预测深度相对不一致的中位数为 3.48%、P90 为 15.83%；受共享相机、拟合数据、语义误分类及遮挡影响，这不是独立精度。1536 个采样像素中 1150 个支持一个 6 图候选平面，拟合阈值约 0.0936 源坐标单位、残差约 0.0474；邻近模型像素高度相关，1150 不是独立测量点，残差不是地面误差。照片与像素坐标保存在缓存的 `samples.npz`。此方法在查看过该场景扫描摘要之后提出，**未纳入先前冻结批次，也不能当作盲测**；没有据此生成或验证 IFC。

## 扫描诊断

扫描采用官方 `scan_alignment.mlp` 将两个扫描文件变换到数据集坐标系；各扫描文件按原始存储顺序每 50 点抽 1 点，非空间均匀抽样，整场包含家具及遮挡。每个方案均在读取扫描前冻结。以下是**源坐标单位**下最近邻距离，并非 ETH3D 官方评测、墙面尺寸、IoU、F-score 或完整度。Photo-only 使用官方相机中心拟合尺度、旋转和平移后才比较扫描，不能衡量独立尺度误差。全场扫描与闭合盒面距离还受到家具、未观测面、抽样和遮挡影响。

| 场景 | 相似配准相机数 / 留一相机中心 RMSE | 稀疏点到抽样扫描中位数 / P90 | 已知位姿 PixCuboid 的六个假设面到抽样扫描中位数 / P90 |
| --- | --- | --- | --- |
| office | 16 / 0.01128 | 0.01273 / 0.05181 | 8 图：0.10352 / 0.44153 |
| kicker | 26 / 0.00394 | 0.01456 / 0.05125 | 8 图：0.20670 / 0.46086 |

`office` 采样 971865 个有限扫描点，`kicker` 采样 1024746 个；场景和图像不同，不依据这些数字对方法排名。两个场景的报告、冻结文件和可视化均在本机缓存：`~/.cache/worldstate-round8/eth3d/{office,kicker}/`。

## 第三方路线与产品回归

- [PixCuboid](https://github.com/ghanning/PixCuboid) 上游 `ff26dafd4aa608bfdff0e68e404f6fbe74a817ce`，代码 Apache-2.0。官方 ScanNet++ 训练 checkpoint 使用 CPU 安全权重加载，权重 SHA-256 `ff6ee1d09a98e73b372c5c9b0cc11284daf69fd69646c34b10af7890ed1212ac`；权重单独使用范围和训练数据限制需在商用前确认。
- [MultiViewRoomLayout](https://github.com/ghanning/MultiViewRoomLayout) 上游 `cb45ace442b6f988216f9607a67f7ab2b8608968`，代码 MIT。实际执行了其 Cuboid 转换和 3D IoU：office 的 5 图及 8 图两个**预测之间** IoU 为 0.2982。这两个输入不同且均非参考真值，数值只说明这两次预测的一致性，不能叫布局准确率或方法排名。IoU 所用 [MeshLib SDK](https://meshlib.io/documentation/License.html) 另有许可：非商业/教育免费，商用需要商业许可；仅在隔离研究环境使用。
- [PolyLayout](https://github.com/ghanning/PolyLayout) 上游 `e4220b702fa01181802f001a28fb7ff8631fd0da` 已检查：基于带姿态的 PINHOLE 图像，针对 Manhattan 多房间，公开代码及约 298 MiB checkpoint；本轮未下载权重或运行，标记 **NOT_TESTED**，CPU 时间、内存和权重使用许可不能推断。
- [ScanNet++](https://scannetpp.mlsg.cit.tum.de/scannetpp/) 的图像和扫描需账号申请与获批的下载权限，本轮没有取得该数据；MultiViewRoomLayout 提供布局标注及评测代码，并不等于已经下载完整 ScanNet++ 场景。独立深度精度与真实布局 IoU 均 **NOT_MEASURED**。
- [BIMNet](https://github.com/LydJason/BIMNet) 已实际克隆并检查 `61c3c2621074d708f23f2db6cc76eb7e276ded04`：当前仓库只有许可证、说明和图片，没有可运行的重建或评测代码，也不包含 IFC 或点云。作者提供的[数据组织说明](https://github.com/LydJason/BIMNet/blob/main/data_organization.md)列出 25 个单层扫描、14 类点云语义、对应 Revit/IFC 和点云到 OBJ 的配准矩阵；这些是潜在 Scan-to-BIM 评测资产，而不是已实测结果。作者要求先取得 Matterport3D 的书面许可，再向 BIMNet 作者申请访问；仓库 MIT 许可不能替代上游数据授权。本机常见数据目录未发现已授权副本，故实际数据、IFC 读取及官方指标为 **NOT_TESTED**。本轮未代表用户发送邮件、签署协议或绕过授权。
- 新的 `cuboid-semantic-ray` 地面候选提供 6 个来源清晰的先验面和照片像素支持，显式保持 `UNCONFIRMED_NO_AUTOMATIC_FLOOR_SELECTION`；不把相邻分割像素当成独立三维点。它依赖 PixCuboid 输出，尚未成为 Studio 内自动可选的地面约束，也未替代稀疏求解器。
- Studio 显示去重、地面不足及语义冲突，允许查看原始照片像素、记录/撤回疑点；疑点会阻止使用包含相同像素的旧或新融合结果。识别、人工复核及事件分开保存；同一物理点若跨运行像素不完全相同，当前不会自动关联。补充点云/人工约束的自动求解尚未接入。为避免 ETH3D 高分辨率照片导致浏览器崩溃，服务端提供哈希核验后的 1600 像素预览，标注和证据仍以原图坐标保存；原始照片文件不被修改。上传上限调整为 16 MB，图像像素上限仍为 3000 万。
- 用已运行的真实 office 融合结果作为 Studio 测试夹具，浏览器实际定位轨迹 `399`、记录疑点并收到 HTTP 400 阻断；原图 6221×4146 在 1600×1066 画布点击时，记录坐标与原图映射一致。另一独立浏览器工作区实际上传 10929589 字节的 ETH3D `DSC_0219.JPG` 并核验源哈希及预览尺寸。脚本操作者标记为 `automation`，这不是一次完整重建或真人操作时间。
- 既有 CRASLAB 模型独立编辑回归：Blender 5.2.2 / Bonsai 0.9.0.post1 实际将墙高从 3.396 改为 3.5 m，再同步回 IR；原始、外编和再生成 IFC 的 23 个产品 GUID 集合一致，回写文件 8/8 墙可生成几何。它不是 ETH3D 新场景 IFC 或实测精度证明。

## 可复现命令

以下命令只在外部缓存操作。环境需 Python 3.12、产品依赖 `pip install -r benchmarks/ws_geometry/requirements-round2-cpu.txt` 和已许可的本地 UPerNet ONNX 文件。`--output` 必须使用不存在的新路径；本轮结果不得被覆盖。下面以 kicker 为例；office 使用 `prepare_eth3d_office.py` 和 `run_eth3d_photo_sfm.py`。先遵照 ETH3D 下载及许可完成 7z CRC，再分别解压到 `modeling-input` 和 `evaluation-private`。

```bash
WS_K="$HOME/.cache/worldstate-round8/eth3d/kicker"
WS_PY=/tmp/worldstate-bim-reset-venv/bin/python
WS_MODEL="$HOME/.cache/worldstate-round5/upernet-convnext-tiny-ade.onnx"
export PYTHONPATH=. OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4

$WS_PY benchmarks/ws_geometry/run_eth3d_kicker.py prepare \
  --images "$WS_K/modeling-input/kicker/images/dslr_images_undistorted" \
  --cameras "$WS_K/modeling-input/kicker/dslr_calibration_undistorted/cameras.txt" \
  --output "$WS_K/reproduction"
$WS_PY benchmarks/ws_geometry/run_eth3d_kicker.py reconstruct \
  --input "$WS_K/reproduction/input" --output "$WS_K/reproduction/photo-sfm"
$WS_PY benchmarks/ws_geometry/run_multiview_fusion.py infer \
  --sparse "$WS_K/reproduction/photo-sfm/sparse/0" --images "$WS_K/reproduction/input/photos" \
  --model "$WS_MODEL" --output "$WS_K/reproduction/masks"
$WS_PY benchmarks/ws_geometry/run_structure_diagnostics.py \
  --sparse "$WS_K/reproduction/photo-sfm/sparse/0" --images "$WS_K/reproduction/input/photos" \
  --masks "$WS_K/reproduction/masks" --output "$WS_K/reproduction/structure"
```

由固定姿态路线与 PixCuboid 复现同 8 图时，先运行 `run_eth3d_kicker.py known-pose`，再运行 `run_pixcuboid_kicker.py --views 8`，最后用其照片选择运行 `known-pose --selection`。PixCuboid 使用独立环境：PyTorch 2.5.1+cpu、torchvision 0.20.1+cpu、NumPy 2.1.3、SciPy 1.13.1、OpenCV 4.10.0、OmegaConf 2.4.0；代码固定到上述 upstream commit，[权重来源](https://github.com/ghanning/PixCuboid#pre-trained-weights)单独下载并核对哈希。无需 DeepLSD；本次没有提供线段，亦没有启用消失点优化。

当前缓存中的冻结及评测可用下列命令重验，先确认冻结指向的源码和工件未改变。`evaluate_eth3d_kicker.py` 会先检查所有冻结哈希，再访问扫描；如果要复现实验，输出应换成新文件名。冻结文件是在读取该场景扫描前创建的，不能在查看参考后重新冻结并继续称为独立评测。

```bash
$WS_PY benchmarks/ws_geometry/evaluate_eth3d_kicker.py \
  --freeze "$WS_K/isolated-dev/model-freeze-v1.json" \
  --source-poses "$WS_K/modeling-input/kicker/dslr_calibration_undistorted/images.txt" \
  --scan-dir "$WS_K/evaluation-private/kicker/scan_clean" \
  --output "$WS_K/evaluation-private/scan-diagnostic-repeat.json"
$WS_PY benchmarks/ws_geometry/render_floor_review.py \
  --review "$WS_K/runs/floor-review-1134.json" --images "$WS_K/isolated-dev/input/photos" \
  --output "$WS_K/runs/floor-review-repeat"
$WS_PY benchmarks/ws_geometry/run_relative_depth_multiview.py \
  --sparse "$WS_K/runs/known-pose-8-sfm" --source-known-pose "$WS_K/runs/known-pose-sfm-corrected" \
  --images "$WS_K/isolated-dev/input/photos" --masks "$WS_K/runs/known-pose-masks" \
  --selection "$WS_K/runs/pixcuboid-8-padded.json" \
  --model /path/to/depth-anything-v2-small.onnx --output "$WS_K/runs/relative-depth-repeat"
$WS_PY -m pytest tests products/worldstate_bim/tests
```

`freeze_eth3d_kicker.py` 接收 `--artifact NAME=PATH` 和 `--code PATH`，需在访问参考扫描前冻结输入清单、Photo-only 几何/语义/结构、两组 Known-pose、PixCuboid 成功和失败记录、人工复核及地面候选；具体必填名称见该脚本。Kicker 的 Photo-only 已运行后，场景入口脚本只补充了 Known-pose 子命令及文本修正，照片求解调用本身未改变；冻结记录的是当时最终代码快照，不是对运行时原始脚本哈希的独立证明。

测试：Core 与产品 **226 passed，50 条第三方弃用警告**。DSH 授权仍为外部阻断，本轮未重试匿名访问；真人配对效率、独立 IFC 参考、正式验收、V0.2 发布均未完成。下一步应优先增加不依赖单一稀疏地面的可验证约束，并在独立标注的扫描墙面和物理尺度上评估后，再导出只覆盖有证据区域的参数化 IFC。

浏览器复核夹具和真实上传可分别复现；夹具复制的是已实际运行的融合结果，只用于 UI 复核，不重新运行建模。Playwright 和 Chromium 路径应指向本机安装：

```bash
# 终端 1：新的外部自动化工作区，不覆盖用户项目。
$WS_PY benchmarks/ws_realroom/serve_fusion_review_fixture.py \
  --fusion "$HOME/.cache/worldstate-round8/eth3d/office/runs/photo-only-structure/fusion.json" \
  --images "$HOME/.cache/worldstate-round8/eth3d/office/isolated-dev/input/photos" \
  --workspace "$WS_K/studio-review-NEW" --port 18732

# 终端 2：BASE、轨迹 ID、源照片名、尚不存在的输出目录。
NODE_PATH=/path/to/node_modules CHROMIUM_PATH=/path/to/chromium \
  node benchmarks/ws_realroom/studio_floor_review_browser.cjs \
  http://127.0.0.1:18732 399 DSC_0248.JPG "$WS_K/studio-review-output-NEW"

# 在另一个空白 Studio 工作区启动服务器后，独立验证原图上传。
NODE_PATH=/path/to/node_modules CHROMIUM_PATH=/path/to/chromium \
  node benchmarks/ws_realroom/studio_real_photo_upload_browser.cjs \
  http://127.0.0.1:18733 \
  "$HOME/.cache/worldstate-round8/eth3d/office/isolated-dev/input/photos/DSC_0219.JPG" \
  "$WS_K/studio-upload-output-NEW"
```
