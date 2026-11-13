# 建模数据集与评测协议，2026-11-13

数据集许可、权重许可和代码许可独立；“能下载”不等于允许商业使用或再分发。以下除已运行的 TUM 场景外均 **NOT_TESTED**，并非下载承诺。没有核对清楚的条款明确列为未知。

| 数据集 | 场景/真值与可用性 | 数据许可、资源与适用性 |
| --- | --- | --- |
| [TUM RGB-D fr1/room](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download) | 真实办公室、RGB、已注册 RGB-D 和动作捕捉轨迹；整序列约 0.73 GiB、可直接下载；无 IFC/墙构件真值。 | 原作者 [2012 论文](https://cvg.cit.tum.de/_media/spezial/bib/sturm12iros_ws.pdf)标明 CC BY 3.0；保留署名。CPU 可做小规模实验，但只能局部评估重建，不能验收 BIM。 |
| [ScanNet](https://github.com/ScanNet/ScanNet) | 真实室内 RGB-D、姿态、表面和实例语义；需要申请同意条款后下载。 | 原始数据条款单独核查；未见可支持公开再分发的证据，待审；不假定有真实 IFC。GPU 适合大规模推理。 |
| [ScanNet++ v2](https://scannetpp.mlsg.cit.tum.de/scannetpp/) | 1006 真实室内场景，激光、DSLR、iPhone RGB-D、相机及语义；申请批准；默认总数据约 1.5 TB。 | [条款](https://scannetpp.mlsg.cit.tum.de/scannetpp/static/scannetpp-terms-of-use.pdf)明确非商用研究/教育。适合多视角与语义评估，公开演示/商用另审；大规模需云 GPU/存储。 |
| [Matterport3D](https://github.com/matterport/3d-dataset-tools) | 真实室内 RGB-D、位姿、网格与区域/对象标注；申请许可。 | 受专门条款限制，商业和再分发先审核；原始数据不应按仓库代码许可证处理。 |
| [ARKitScenes](https://github.com/apple/ARKitScenes) | 5047 次真实 iPad RGB-D/LiDAR 采集、1661 场景，部分有高质量激光、物体框与位姿。 | [Apple 数据条款](https://github.com/apple/ARKitScenes/blob/main/LICENSE)与下载要求须逐条审查；不在本轮作商业或再分发判断。适合移动采集，不声称原生 IFC。 |
| [Structured3D](https://github.com/bertjiazheng/Structured3D) | 合成室内图、深度、语义和结构化布局；适合训练/可控测试。 | 数据许可与获取步骤须独立核查；不能替代实景验收；大规模推理通常需要 GPU。 |
| [DTU MVS](https://roboimagedata.compute.dtu.dk/?page_id=36) | 标定多视图和扫描真值，偏室内物体，适合几何算法，不是房间 IFC 基准。 | 本轮上游数据页超时；下载条款、商业和再分发许可 **UNKNOWN**，不得当公共产品例子。 |
| [ETH3D](https://www.eth3d.net/datasets) | 室内/外照片、相机与激光几何，部分场景级分包；适合二维/多视图几何评测。 | 数据许可及登录要求仍待上游确认；评测软件许可证不能代替数据许可证。CPU 可测小分包，稠密/神经方法需更多资源。 |
| [Tanks and Temples](https://www.tanksandtemples.org/) | 真实室内外视频/照片和激光扫描真值；适合几何与视觉，不含原生 BIM 真值。 | 获取与许可待进一步核实；公开展示及商用不能预先假定。 |
| [BIMNet](https://thucbims.github.io/bimnet/) | 25 个真实单层点云及对应 IFC；[数据组织](https://github.com/LydJason/BIMNet/blob/main/data_organization.md)说明原始点云来源 Matterport3D。 | 必须遵守上游数据条款；不能因为论文称开源就假设可商用。适合 Scan-to-BIM，非照片到 IFC 完整真值。 |
| [DeKH / BIMStruct3D](https://huggingface.co/datasets/RPTU-FGMB/DeKH) | 四个真实医院场景、语义点云与 IFC 真值；约 17.2 GB。 | **CC BY-NC-SA 4.0**，仅非商业研究；适合对象与拓扑评测，不代表照片可用。 |
| [GNI BIM Dataset](https://github.com/ZijianWang-ZW/GNI-BIM-Dataset) | 多个 IFC 文件；用于 IFC 解析、编辑和属性回读基准。 | 项目声明 CC BY 4.0；非照片重建真值。下载或再分发时核对每个源文件与署名。 |

单张非标定照片、环拍、手机 LiDAR、无人机、图纸/PDF、点云、既有 IFC、多时相与合成/真实混合需要分别建任务，不应混成一个“照片输入”分数。目前 TUM、DeKH、GNI 是不同场景和输入，不可拼接成同一栋楼的真值。

## 数据台账和分割约束

每个可使用版本记录：来源 URL、作者/引文、许可证及取得日期、原始文件大小/SHA-256、派生处理/代码版本、采样与坐标/单位、模态/标注、使用限制、训练数据来源、场景与采集日期。模型代码和权重各自记录版本与哈希。原始下载/模型权重放仓库外；不得提交未经授权的客户/内部资料。

1. 以**建筑或独立场景**划分 train/dev/test，优先按数据集官方划分；同一房间的相邻帧、不同阶段或同一建筑不能跨严格独立 test 与 train。
2. 本轮 TUM 仅有一个房间，固定两张图片是**开发集**；像素级或同序列时间留出不构成跨场景独立 test，不允许报告泛化。
3. 位姿/深度供独立评估，除非明确标成 oracle 标定；标定数据与被测尺度/深度必须隔离，任何对齐方法及训练数据污染风险都要记录。
4. 评估几何（相机位姿、重投影、尺度、Chamfer/Accuracy/Completeness/F-score、尺寸）、辅助视觉（PSNR/SSIM/LPIPS/保留视角）、语义（类别与实例 F1、楼层/空间/开口关系）、BIM（原生 IFC、解析/独立编辑回读、GUID 和参数修改）、证据（属性级覆盖、未知/冲突）及成本（CPU/GPU、调用、人工修正/审核）。
5. 应预先固定容差、数据和脚本，并记录失败分母与人工时间；目前不存在足够真值来评测墙尺寸、语义 F1、手工效率或完整 BIM，结果一律 **NOT_MEASURED**。真实用户的总人工耗时与达到质量门槛的成功率是首要产品指标。
