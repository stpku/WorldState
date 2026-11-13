# 开源技术调研与初选，2026-11-13

调研范围包括 2025–2026 新项目和成熟基线；“项目宣称”与本项目实测分开。全部许可均须对具体代码、模型权重、训练数据、下游软件分别核查。下表中未明确写实测的均为 **NOT_TESTED**，不是性能排名。

| 路线/项目 | 输入与实际交付类型 | 选择理由与边界 | 本轮状态 |
| --- | --- | --- | --- |
| [OpenCV SIFT + 两视图几何](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) | 标定 RGB → 相对位姿与稀疏三角点 | 依赖纹理/重叠；单目无绝对尺度，低重投影误差不能代表墙面准确。仅用于小样本基线。 | **TESTED**，见实验报告。 |
| [COLMAP](https://github.com/colmap/colmap) | 多视图 SfM/MVS → 相机/点云/表面 | 成熟多视图对照；CPU 稀疏流程可行，检查具体版本及稠密阶段 GPU 要求。官方仓库当前声明库为 BSD；各依赖分别核查。 | NOT_TESTED；本机未安装。 |
| [OpenMVG](https://github.com/openMVG/openMVG) + [OpenMVS](https://github.com/cdcseacave/openMVS) | SfM + 稠密点云/Mesh | 备选多视图管线，几何不等于语义 IFC。 | NOT_TESTED。 |
| [DUSt3R](https://github.com/naver/dust3r), [MASt3R](https://github.com/naver/mast3r) | 非标定图片 → 点图/匹配 | 少视图与弱标定候选；DUSt3R 代码和衍生组件存在非商用条款，须逐项核查。 | NOT_TESTED。 |
| [VGGT](https://github.com/facebookresearch/vggt) / [VGGT-Ω](https://github.com/facebookresearch/vggt-omega) | 多图 → 相机/深度/点图；Ω 2026 | 优先 GPU 复验最新候选；VGGT 官方说明原权重非商用，商业权重另申请且有用途限制，Ω 许可证/权重须单独核验。输出不等于 BIM。 | NOT_TESTED；无 GPU。 |
| [HunyuanWorld-Mirror](https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror) | 多图及可选几何先验 → 深度、位姿、点云等 | 2026 多表示候选，许可和实际资源需逐项复核。 | NOT_TESTED。 |
| [Depth Anything V2 Small](https://github.com/DepthAnything/Depth-Anything-V2) | 单图 → 相对深度 | 适合作低成本先验，不能从先验直接恢复可验证的尺度或遮挡；Small 与更大权重许可不同。 | **TESTED**：社区 ONNX，CPU；只得到相对深度。 |
| [3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting) / [Nerfstudio](https://github.com/nerfstudio-project/nerfstudio) | 标定多视图 → 新视图/隐式或高斯表示 | 用于照片对照和预览的候选；PSNR/外观不证实表面或构件精度；原始 3DGS 实现的非商用许可须核查。 | NOT_TESTED。 |
| TSDF/SDF、[Open3D](https://github.com/isl-org/Open3D) | RGB-D/注册点云 → 融合表面 | 传感器与位姿误差会传播；表面不会自动生成可编辑构件。 | NOT_TESTED。 |
| [SAM 2](https://github.com/facebookresearch/sam2)、[SAM 3](https://github.com/facebookresearch/sam3) | 图像/提示 → 分割 | 分割可协助选择墙、窗的可见区域，但掩膜不证明厚度、尺度或语义正确；各权重条款不同。 | NOT_TESTED。 |
| [SpatialLM](https://github.com/manycore-research/SpatialLM) | 点云 → 结构化室内元素 | 可比较对象级语义和布局；输出格式、许可及转 IFC 的几何保持尚未实测。 | NOT_TESTED。 |
| [Cloud2BIM](https://github.com/VaclavNezerka/Cloud2BIM) | 点云 → 论文/项目声明的 IFC | 值得作为真正 Scan-to-IFC 对照；具体构件、参数修改、许可证和独立读回仍须实测。 | NOT_TESTED。 |
| [BIMStruct3D/pystruct3d](https://github.com/humantecheu/pystruct3d) | 语义点云 → 几何与拓扑；配套 DeKH IFC 真值 | 2026 可测 scan-to-BIM 候选，不自动等价于 photo-to-BIM；数据为非商用。 | NOT_TESTED。 |
| [Text2BIM](https://github.com/dcy0577/Text2BIM)、[MCP4IFC](https://show2instruct.github.io/mcp4ifc/) | 文本/工具 → 声称结构化 IFC 操作 | 适合借鉴工具反馈；文字设计生成不是历史事实恢复，须在受限对象 API 内操作。 | NOT_TESTED。 |
| [IfcOpenShell / Bonsai](https://github.com/IfcOpenShell/IfcOpenShell) | IFC 解析/参数化几何；Bonsai 为独立 authoring 工具 | 拟作为编译和独立编辑检查组合，IfcOpenShell 库 LGPL、Bonsai GPL，须逐组件核查。 | 合成 IFC 导出/读回 **TESTED**；Bonsai **NOT_TESTED**。 |
| [FreeCAD](https://www.freecad.org/)、[Open CASCADE](https://dev.opencascade.org/)、[CadQuery](https://github.com/CadQuery/cadquery) | 参数几何/约束建模 | 墙和开口复杂化后可比较；一般 CAD/CSG 不自动保留 IFC 语义。 | NOT_TESTED。 |

## 同输入对照矩阵与暂定路线

| 候选 | 共同输入 | 可比较量 | 本轮结果/缺口 |
| --- | --- | --- | --- |
| 传统：SIFT + 两视图 | 两张 TUM RGB、相机内参 | 匹配、重投影、独立轨迹角误差、传感器深度误差；需要外部尺度 | 已真实运行。不是完整 COLMAP/SfM/MVS；室内遮挡与低视差仍有风险。 |
| 基础模型：Depth Anything V2 Small | 同一对照片中的首张 RGB | 相对深度、同一深度图上的校准/留出像素误差、CPU 时间 | 已真实推理；只用单图、没有位姿，不可与双视图轨迹分数直接排名。 |
| 混合：视觉理解 + 受限参数模型 + IfcOpenShell | 同样的 RGB、必要的独立尺度与人工反馈 | IFC 构件、尺寸、覆盖、修订、人工成本 | DSH headless 实际调用因凭据失败；完整链 **NOT_TESTED**。既有合成 IFC 测试不等于混合链成功。 |
| 可选：VGGT-Ω 或 3DGS | 相同照片和额外必要输入 | 位姿/深度或保留视角；BIM 须另评 | **NOT_TESTED**，当前无 GPU；不以渲染画面代替工程精度。 |

建议先用**传统几何或可替换视觉模型产生可核查候选 + 受约束参数化 IFC 编译 + 人工确认未知**作为产品主线；多视图丰富时先试 COLMAP，少图时用基础模型给候选而保留尺度/遮挡未知。此选择是可证伪的工程假设，不是三路线实测后的获胜结论。暂不把直接生成 IFC 文本、单图外推完整建筑、3DGS 漂亮渲染或单模型置信度当作验收路线。

下一轮应在统一开发集及锁定的独立场景上运行 COLMAP、一个多视图基础模型及真实视觉/Harness→参数编译链，记录所有失败和资源；如模型训练数据与评测数据是否重叠未知，则禁止宣称严格独立泛化。
