# 混元 → Blender → FreeCAD 资产实验包

**状态：NOT_TESTED。** 本机无 CUDA GPU，未安装 FreeCAD；没有租用 GPU、调用托管服务或上传图片。尚无满足授权和独立尺寸条件的实物数据，不能提供网格质量、尺寸误差或人工成本结果。Blender 5.2.2 曾在第二轮打开本地既有校园 GLB；该模型不是混元生成物。

## 数据与许可

选择一个可公开或明确授权本地处理的独立箱体/家具，拍摄至少 front、left、back 三张真实照片，另留未参与建模的照片。记录数据采集许可、时间、文件 SHA-256；用一项标尺进行尺度校准，至少三项由独立测量人提供的尺寸作为私有留出真值。数据与权重保存在仓库外。不得使用留出尺寸进行建模或校准。

候选 [Hunyuan3D-2mv](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) 官方多视图形状模型及 [模型协议](https://huggingface.co/tencent/Hunyuan3D-2mv/blob/main/LICENSE)须分别核查；代码和各权重可能有不同许可。上游说明 Hunyuan3D 2.0 形状生成约 6 GB 显存、形状加纹理约 16 GB，是其环境说明而非本项目测量。建议使用有余量的已授权 CUDA 环境。FreeCAD 与 Blender 的安装及其许可须由执行者确认；不得未经批准租用收费 GPU 或发送私有照片到第三方。

## 离线执行包（尚未在 GPU 验证）

上游代码修订 `f8db63096c8282cb27354314d896feba5ba6ff8a`，2mv 模型快照 `3a761b539b29fe4ff64714813aa9560fd66f5de0`。先在授权环境按 [上游说明](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/tree/f8db63096c8282cb27354314d896feba5ba6ff8a)安装合适 PyTorch/CUDA 和依赖，并将指定权重快照预先安全放入本机目录；记录所有权重与配置哈希。该实验包及依赖组合尚未实跑，可能需要按实际环境调整。

```bash
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2 /tmp/hunyuan3d-2
git -C /tmp/hunyuan3d-2 checkout f8db63096c8282cb27354314d896feba5ba6ff8a
# 在仓库外准备来自同一个物体的透明背景 RGBA front/left/back 图片。
# 按 manifest.example.json 建立清单：允许本地推理、许可、模型修订及各图片哈希。
# 校验事先取得的 checkpoint；路径和 SHA-256 替换成实际值。
python benchmarks/ws_mesh/hunyuan_freecad/run_hunyuan.py \
  --repo /tmp/hunyuan3d-2 --weights-dir /path/to/local-model-snapshot \
  --checkpoint /path/to/local-model-snapshot/hunyuan3d-dit-v2-mv/model.safetensors \
  --checkpoint-sha256 ACTUAL_SHA256 --manifest /path/to/private/manifest.json \
  --image-root /path/to/private/images --output-dir /tmp/worldstate-hunyuan-run
```

脚本启用 Hugging Face / Transformers 离线模式，校验一项 checkpoint 和输入照片哈希，并只输出未验证 mesh、设备及时间；仍需由执行者验证整个权重目录的版本/哈希、模型路径、依赖以及未见区域。禁止将网格坐标和生成背面直接称为实测。

使用本机 Blender 打开 GLB 并记录人工修订时间和结果；FreeCAD 中按有来源的输入参数重建可编辑实体。`freecad_box.FCMacro` 是待验证的简单参数化包围盒示例，依 `WORLDSTATE_ASSET_CONFIG` 所指 JSON 中的 `length_m`、`width_m`、`height_m` 和 `output_fcstd` 创建对象；它没有实现 mesh 自动转参数化 CAD。当前 WorldState BIM 房间 IR 也没有通用家具/机柜 IFC 类型，不能声称这些步骤已经集成。

在冻结后分别提供 `prediction.json`（`dimensions_m` 和 `used_measurement_ids`）及私有 `reference.json`（`measurements` 列表，每项含 `id`、`axis`、`value_m`），用 `evaluate_dimensions.py` 输出每项绝对/相对误差；如真值 ID 与建模测量重叠，脚本会拒绝。照片质量、网格外观、物体完整性、FreeCAD 可编辑性、IFC 语义和人工耗时必须单独记录。

至少记录素材整理、标注、模型推理、Blender 修订、FreeCAD 建模、复核、失败重试、GPU 小时及费用，和同输入/同质量手工基线比较。若模型未达到质量门槛，不得计算虚构的合格模型成本。
