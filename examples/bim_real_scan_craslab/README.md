# CRASLAB 真实点云到局部语义 IFC

本例的 [IFC4 草稿](scan-wall.ifc)、[参数化 IR](scan-ir.json)、[几何候选](geometry-candidate.json)和[评测](evaluation.json)由真实点云生成，可独立下载检查。仅一个可见墙面片段，类别由规则推断，尚未人工确认，**不代表完整墙体、房间或准确的自动 BIM**。

数据来源：N. Abreu 等，[Indoor point cloud dataset for BIM related applications](https://doi.org/10.5281/zenodo.7948116)，CC BY 4.0；[数据说明与论文](https://www.mdpi.com/2306-5729/8/6/101)。数据集的 X/Y/Z 原生单位为米；样本来自 584,701,977 个扫描点中每 2000 条确定性抽取，共 292,351 点。完整压缩包 SHA-256 `933732e81910116cec5e74c9205074b82d1f571f3d9816386b68a0a909112671`，样本 hash 见评测；原始点云、标签、BIM 不纳入仓库。

推理只读取 XYZ，以 Z 竖直和局部面密集为先验，先保存 IFC、IR、预测掩码，再读取标签。3,042 个预测点中 1,997 为参考 wall，1,045 为其他类别：其中 975 点为参考 board，说明垂直几何不能可靠区分墙和白板。点级 precision 0.6565；对整个多房间抽样场景算 recall 0.0445，单块候选并不试图覆盖所有墙。开发标签用于开发评估，不是独立场景测试；不可将 fit 残差当作墙体真实误差。

IFCOpenShell 及 web-ifc 均读取到一个 `IfcWall`、GUID `3GH0h4u7XQCRyf_8mGlGBt`；IfcOpenShell 生成了 8 顶点实体。长度 2.184 m、可见高度 2.468 m 是所选表面支持范围，不是整墙尺寸。厚度 0.12 m 为显式假设；完整边界、门窗、整墙和 storey 均未核实。数据集还提供 IFC 参考，但它与点云坐标系不同；本轮没有完成配准，因此与参考 IFC 的几何误差 **NOT_MEASURED**。

复现及依赖安装见 [Benchmark 入口](../../benchmarks/README.md)。使用前检查数据集与本示例的来源、许可及标注限制。
