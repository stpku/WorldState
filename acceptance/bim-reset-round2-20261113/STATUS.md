# WorldState BIM 产品重置：第二轮实测状态

日期 2026-11-13；环境 Linux x86-64、4 vCPU、约 15 GiB 内存，无 GPU。此前 `ee4b93a` 的失败与 oracle 结果保留；TUM 同帧深度对齐不是独立公制精度，平面拟合残差不是墙体重建误差。版本 **V0.2 NOT RELEASE-READY**。

回归命令：`OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m pytest tests products/worldstate_bim/tests -q`；本轮 156 项通过，11 条上游 IfcOpenShell `utcnow` 弃用警告。测试包含合成单元检查和公开真实 IFC 工件检查；这不是独立真实房间验收。

## 三条路线

| 路线 | 实际结果 | 选择与限制 |
| --- | --- | --- |
| A 多视角 | pycolmap 4.2.1 CPU，固定同一 TUM 房间序列 4/8/16/32 张、真实运行，下表含失败 | 作为密集照片的候选几何 provider；稀疏点不是 BIM。VGGT-Omega 的 GPU 包已准备，模型和 adapter 均 NOT_TESTED，许可证限非商业研究。 |
| B 扫描→语义 IFC | [CRASLAB 真实点云](../../examples/bim_real_scan_craslab/)生成一个 WorldState 墙片段；Cloud2BIM 输出 9 墙、6 窗，PyStruct3D 包围盒组件实测 | 完整 Cloud2BIM 研究管线已跑，IFC 存在 6 个必填属性缺失；参考 IFC 尚未配准、独立尺寸未测；SpatialLM / 完整 BIMStruct3D 未测。 |
| C 视觉 + 辅助建模 | [TUM RGB-D 照片](../../examples/bim_real_photo_tum/) + CPU Depth Anything V2 ONNX 实际推理、分析者选区、同传感器尺度、墙厚假设 → 受限 IR / IFC | 已有局部可编辑墙和浏览器；相对深度模型不提供语义标签或公制尺度。DSH headless 0.2.2-rc.1 最小请求仍返回 `MISSING_CREDENTIAL`，不是 DSH 自动建模。未测试视觉路由、MCP、费用和稳定性。 |

### A：COLMAP 开发试验

32 个公开授权 TUM 彩色帧，嵌套采样并校验 SHA-256，所有组使用相同原始场景、固定 TUM 默认相机内参及 CPU 参数。预先选定的首/尾尺度锚未同时注册，严格协议均失败；下表位姿误差是以「实际注册的首/尾帧」作**事后诊断性** oracle 基线/首帧姿态对齐后，在剩余已注册帧计算的中位误差。不同运行选中的参考与评测帧不同，结果不可直接排序为算法精度；规模和硬件并不足以说明泛化。

| 输入张数 | 注册张数 | 稀疏点数 | 均值重投影 px | 运行秒 | 剩余帧数 | 平移中位误差 m | 旋转中位误差 ° | 相对基线误差中位数 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 0 | 0 | — | 0.34 | — | — | — | — |
| 8 | 0 | 0 | — | 0.40 | — | — | — | — |
| 16 | 8 | 232 | 0.923 | 0.82 | 6 | 0.0761 | 3.38 | 22.91% |
| 32 | 17 | 533 | 1.158 | 2.41 | 15 | 0.2303 | 10.77 | 41.64% |

实际原始结果 [4](colmap/4.json)、[8](colmap/8.json)、[16](colmap/16.json)、[32](colmap/32.json)；均为开发实验、无独立绝对尺度或稠密表面完整度。固定 seed 仍观察到重跑 32 张时注册数和位姿明显变化；此次记录使用最后一次结果，多线程 SfM 的可重复性仍需研究。时间只记录提取、匹配和映射，排除素材准备、审核和人工时间。轨迹用于校准和留出相机评估，不是独立墙尺寸。

### B：CRASLAB

从公开 CC BY 4.0 的 4.27 GB 标注档案中确定性间隔抽样，生成候选期间没有加载类别标签。采样 292,351 点，冻结 IFC 后读取标签：3,042 个候选点中墙体 1,997、白板 975、其他 70。精确率 1,997/3,042；1 个候选无法覆盖全部场景的 44,890 个参考墙点，因此整体召回率低。保留由此暴露的白板误识别，不将推断当成人工确认。厚 0.12 m 只是构建草稿的显式假设。结果详见[案例](../../examples/bim_real_scan_craslab/README.md)。

对同一已冻结的 3,042 个候选点，在独立环境运行 PyStruct3D 0.17.0（源码 `fcbe3070deef2d9ed2662abd77fdf0ad35c39f87`，MIT）`BBox.fit_horizontal_aligned`：包围盒长 2.1826 m、高 2.4670 m、点分布宽 0.0684 m；与本产品候选支持长度 2.1837 m、高 2.4678 m 接近。**相同选择点上的拟合接近不等于相对于独立真值精度高；包围盒宽度不是墙厚。**此试验没有运行 BIMStruct3D 分割、语义识别或完整管线。Open3D 0.19.0、NumPy 2.5.4、SciPy 1.18.1，记录见 [JSON](pystruct-bbox.json)。

同样的 292,351 点还实际运行 Cloud2BIM（源码 `cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e`，MIT，先因缺 LaTeX 中止，后仅禁用绘图 LaTeX 重跑），得到 IFC4：9 墙、2 楼板、6 窗、6 开口及对应关系；9/9 墙能生成几何。IfcOpenShell 独立 schema 校验发现 6 项 `IfcWindowType.PartitioningType` 缺失，地点 0°/0° 为占位，材料/板厚含未核实假设。对两种 IFC 在相同点云、同一 4 cm「点到最近墙三角面」协议下测试：Cloud2BIM precision 0.5956、recall 0.1994；单墙基线 precision 0.6112、recall 0.0454。分别输出 [Cloud2BIM](cloud2bim-ifc-evaluation.json) 和 [WorldState](worldstate-ifc-surface-evaluation.json) 报告。构件数量、覆盖和假设不同，这些仅是开发场景点邻近指标，不是 IFC 实例匹配或独立尺寸误差；Cloud2BIM 值得优先进一步集成和修复，尚不能判为符合发布条件。

### C：RGB-D、独立工具与修订

真实 TUM 照片 `1305031916.701048.png` 与深度帧、人工 ROI、同传感器锚点实跑；Depth Anything V2 Small 的 ONNX SHA-256 `afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c`，本例 CPU 推理 1.85 秒，仅提供相对深度过滤。局部墙可见范围约 0.428 × 0.401 m，厚度 0.12 m 为假设；独立尺度、整墙长度/高度和精度 **NOT_MEASURED**。`0.0002 m/raw-unit` 由输入的距离和像素实际求得，但此距离来自同一深度传感器，不能作为独立标尺结果。

IfcOpenShell 0.8.4 原生 IFC 墙增加轴线和未指定材质的几何层后，Blender 5.2.2 / Bonsai 0.9.0.post1 的墙长工具将其改为 0.500 m 并保存；前后均为单一 `IfcExtrudedAreaSolid`，GUID 都为 `27dj0KkHfVKfCo5Vu6Zcj6`。web-ifc 0.0.77 独立读取原始、Bonsai 修改及同步后文件；IfcOpenShell 几何回读三个文件成功、IFC schema validation 记录 0 项。`sync-ifc` 校验 GUID、轴线、位置、层厚和矩形几何，将长度与外部 IFC 哈希写入 IR，再生成 IFC；不支持其他外部属性、拓扑或开口变更，拒绝未知几何。web-ifc 独立高度编辑另存并回读，但尚不能同步。

早期缺轴线时，Bonsai 墙长工具出现 `ContextIdentifier` 缺失；尝试以一般网格编辑保存需要转成三角面片，不能保持参数。后续通过增加轴线和材料层修复，保留以上失败记录，不能把其他 IFC 类型推定为已兼容。

## 人工成本、基准和门槛

WS-RealRoom 的采集、数据隔离、参考测量和预先冻结门槛见[协议](../../benchmarks/ws_realroom/PROTOCOL.md)。没有独立新房间、配对人工建模或合格模型总数；各阶段人工成本及节省百分比均 NOT_MEASURED。相对深度推理秒数和 COLMAP 算法运行秒数不代表产品人工成本。

固定公开 TUM 输入来自受许可镜像并校验哈希；CRASLAB 和 IFC 示例按 CC BY 4.0 归属发布。未提交客户/公司内部照片、点云、模型权重或 API 密钥。本地 GLB 网格检查和混元/FreeCAD 候选的适用边界见[调研](../../docs/research/2026-11-13-hunyuan-and-scan-to-bim.md)。混元未运行，GPU、云费用和权利条件均未验证。

## 尚缺和后续

1. 采集有授权的新房间：多视角、独立标尺、留出照片、至少三项不参与建模的测量和参考 IFC；按冻结协议运行。
2. 多墙与墙角、墙体完整范围、门窗和开口关系、约束及局部影响；现在只有单块墙面。
3. 在隔离 GPU 上实测许可合适的视觉基础模型、SpatialLM 或混元；对 Cloud2BIM 的 IFC 校验、实例匹配和证据属性继续修复与独立评估。
4. 拓展外部 BIM 编辑读回、自然语言修改、DSH 真实视觉与工具调用；当前只支持明确参数和局部墙长回读。
5. 完成人工基线/审核与失败成本测量、用户场景评估、错误修复及发布门禁。尚未获得的每项结果均不得声称完成。
