# 建模候选：混元 3D、Blender/FreeCAD 和点云路线

调研与运行日期：2026-11-13。本页区分供应商资料和本项目实测。

## 朋友建议的工作流

建议将「实物多张照片 → 混元 3D → Codex 协助 → Blender 修视觉 / FreeCAD 修实用几何」列为**可替换的快速资产路线**，与参数化 BIM 路线在同一照片、独立测量及人工成本协议下对照。它有助于快速观察轮廓、制作展示资产，也可能帮助操作者定位待重建对象；不能把生成背面或纹理的外观当成现场观测，也不能假定 GLB/mesh 自动具备公制尺度、IfcWall、开口关系或可编辑参数。

- 腾讯 [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) 的 **2mv** 明确支持多视图图像到形状，官方仓库也有 Blender 扩展；[2mv 权重协议](https://huggingface.co/tencent/Hunyuan3D-2mv/blob/main/LICENSE)是 Tencent Hunyuan 社区协议，不等同于无条件 Apache/MIT。模型、代码和服务条款应分别核查。**本地模型未运行：无 GPU，NOT_TESTED。**
- [Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) 官方报告约 10 GB 显存生成形状、21 GB 纹理、29 GB 联合，官方示例以单张图像为主，不能直接假设与 2mv 输入接口相同。[2.1 许可](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE)有地域和其他使用条件，商用前需单独审阅。以上为供应商资料，并非本项目测量。
- [Hunyuan3D-Buffalo1.0](https://github.com/Tencent-Hunyuan/Hunyuan3D-Buffalo1.0) 截至本轮为技术报告仓库；不可因论文或展示将其记作本地可运行结果。[腾讯云 3D API](https://intl.cloud.tencent.com/document/product/1284/75540) 是不同的托管服务，需另查费用、授权和输入数据规则；本轮没有调用，也没有上传校园或用户照片。
- **已运行 Blender 5.2.2**：导入现有本地校园 GLB，发现 1,588 个 mesh、805,514 顶点、593,324 面，导入约 3.0 秒；有限检查没有找到名称包含 IFC/GlobalId 的对象自定义属性。该输入**不是混元生成物**；检查不能证明该资产完全没有语义或单位。本轮未复制或提交校园 GLB。
- **已运行 Bonsai 0.9.0.post1**：旧 IFC 缺少墙轴线和材料层，直接使用墙长参数报错；通用网格修改可保存但会丢失挤出参数。补齐轴线和材质未指定的几何材料层后，Bonsai 使用墙长参数修改并保存，web-ifc / IfcOpenShell 重读后仍为挤出实体且 GUID 不变；单墙长度修改已受控同步回 IR。FreeCAD 本机未安装，NOT_TESTED。

下一步以一件经授权且有真实尺寸的构件为同源输入：混元 mesh、Blender 编辑、FreeCAD 的可编辑实体重建、受控 IR/IFC 编译与独立尺寸/留出照片检查。分别记录调整和审核时间、失败数及材料/权利；对未观测部分保持 unknown/inferred。缺少相关资产或 GPU 时不报告虚构的效果或成本。

## 结构化重建项目

| 项目 | 输入及输出范围 | 本轮状态 |
| --- | --- | --- |
| [SpatialLM](https://github.com/manycore-research/SpatialLM) | 点云生成结构化空间布局；模型权重及工具链有独立许可和资源要求 | 未运行，NOT_TESTED；不是现成已验证 IFC 编辑器。 |
| [BIMStruct3D / PyStruct3D](https://github.com/humantecheu/pystruct3d) | MIT 的实例边界盒、评估和点云工具；PyStruct3D 不是完整的实例分割或 IFC 产品 | 参见本轮状态报告；分割输入、参数和环境必须单独报告，不能声称完整 BIMStruct3D 已实测。 |
| [Cloud2BIM](https://github.com/VaclavNezerka/Cloud2BIM) | MIT 的点云到 IFC 研究管线，支持墙、楼板、开口等；实际质量依赖数据和配置 | 已审查代码与依赖，完整运行 NOT_TESTED；其配置、依赖及输出必须在隔离环境测量。 |
| WorldState 点云几何基线 | 明确 Z 竖直先验，用点密度选一块垂直平面，生成一个局部原生 IfcWall | **已运行**，见 [真实案例](../../examples/bim_real_scan_craslab/README.md)。精确率 65.6%，大量白板混入；未确认类别，不能作为可靠自动语义模型。 |

优先继续将真实用户辅助标注、明确尺度、参数化 IFC 和独立验证贯通；候选项目须做统一输入对照后才可宣称优于当前方法。
