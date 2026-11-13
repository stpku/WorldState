# 基线审计：Evidence-to-Editable World

审计日期：2026-11-13；起点 `68dbfc7`，分支 `feat/worldstate-bim-vertical-slice-20261111`。这是本轮执行时的工作区观察，非生产发布证明。

## 已实现与本轮验证

| 范围 | 存在的能力 | 能证明什么 |
| --- | --- | --- |
| Core M0–M4 | 类型契约、内存解析、来源/时效、Unknown/Conflict、provider wire、三种提供方式、跨域示例和集成向量 | M1–M4 报告记录冻结时的有限测试；本轮回归见下。外部历史集成报告不等于本轮重新验证了外部系统。 |
| Core M5–M9 | 时态变化、冲突策略、change SDK、独立冷链消费者、因果 frontier | 相应代码和测试存在；M6b–M9 报告是确定性 fixture 范围内的 PASS，不代表真实生产可靠性。 |
| BIM v0.1 | `worldstate-bim-proposal/0.1` 输入、图片 SHA-256 检查、来源引用、缩放声明检查、IfcOpenShell IFC4 四墙样本、UUID5 压缩 GUID | 隔离环境下现有 IFC 测试可解析并创建墙几何，重复导出 ID 保持；只测合成提案。Bonsai 独立编辑未测。 |
| WORLD / VERIFY | `examples/world_verify` 合成证据视图；`aigc-3d/standalone-sites/world-verify` 有公开叙事与浏览器测试 | 可复用叙事、照片来源核查与可视化；仓库 evidence view 与真实展示资料尚未连通，不能把合成结果当实测。 |
| 新实验 | 两张 TUM RGB 照片的 SIFT/双目三角化；单张同源照片的 Depth Anything V2 Small CPU 推理；人工 ROI 的 RGB-D 平面 | 实验记录和局限见 [benchmark](../../benchmarks/bim_real_room/README.md)；人工的“可能是墙”标签不是自动语义或 IFC。 |

原始回归命令：`/tmp/worldstate-bim-reset-venv/bin/python -m pytest tests products/worldstate_bim/tests`；在加入本轮新增测试前 **139 passed，2 个上游弃用警告**。Python 3.12.3、IfcOpenShell 0.8.4、4 vCPU、15 GiB RAM、无可见 NVIDIA GPU。系统 Python 3.14 起初没有 pytest、NumPy、OpenCV 和 IfcOpenShell，直接 unittest discover 因依赖与 `src` 路径未配置失败，不能误报为 Core 回归失败。完整最终测试数以本轮状态报告为准。

## 本地工作与边界冲突

审计时 `AGENTS.md`、`README.md`、`docs/compatibility/stack-observation-2026-08-18.md`、`docs/reports/m4-integration-compatibility.md`、`docs/roadmap/m0-m4.md` 已有用户未提交改动；本轮不覆盖或纳入自己的提交。已修改的 AGENTS 把仓库整体描述为 foundation 冻结期，README 仍把项目最终目标写成 Truth Fidelity，且其未提交段落称其不是三维重建产品。用户新指令明确把产品北极星扩展到可编辑世界；[ADR](../adr/0004-evidence-to-editable-product-scope.md) 将其解释为**产品目录的新增作用域**，保留 Core 和跨项目边界，不声称旧冻结/生产门禁失效。需要所有者后续协调根 README/AGENTS；本轮不替用户覆盖其修改。

## 可复用但不自动获得公开授权的资产

`/home/dev/work/aigc-3d` 含 WORLD/VERIFY 的独立站、浏览器测试、校园 GLB 和部分 Blender 文件；`docs/PKU_PHOTO_CALIBRATION_OLD31.md` 有历史照片校准记录，`docs/PKU_TEXT2BIM_TEXT2CAD_ASSESSMENT.md` 有 Text2BIM 对照，`data/学院路小学校园模型_完整包.zip` 为既有资产。实际文件、拍摄时间、来源及其衍生物的许可须逐项复核，**不因本地存在或网站公开而推断可重新发布或用于训练**。本轮没有把这些照片或公司资料复制进本仓库。

## DSH 的实际环境

`dsh --version` 返回 `0.2.2-rc.1`；headless help 支持非交互任务、JSON 事件、权限预设。Web 配置中有 DeepSeek 模型及 `dsh-vision-router`，插件本地说明写明某些视觉提供方会接收图像；是否走本地/远程须实际核对。实际执行无工具的最小 headless 请求返回 `MISSING_CREDENTIAL`（`deepseek-official`）；不能据此断言 Web 路由也不可用。多模态输入、结构化输出、MCP 工具、自动修复、成本、并发与稳定性均 **NOT_TESTED**。官方 [DeepSeek Vision 文档](https://api-docs.deepseek.com/guides/vision/)描述 `deepseek-flash` 可输入图像，这不证明当前 DSH 路由已配置或实际可用。未发送用户/校园照片给外部模型。

## 未实现、技术债务与首轮必须处理的问题

- 没有照片/视频到语义墙的自动流程、经独立尺度核验的真实照片 IFC、真实房间尺寸/保留视角评测、真实用户操作与人工成本基线。模型不具备可验收的自动建模能力。
- `MetricAnchor` 仅保存某个照片 ID、数字和声明 basis，未关联照片中的两点、长度计算、来源文件、测量不确定性或验证过程；`has_metric_anchor` 只检查声明。不能将这一布尔值视为实际完成尺度校验。墙体属性目前只有整体 evidence_refs，非属性级来源。
- 当前墙的 `basis` 是整体状态，尚无法对观测的墙面、不可见厚度和假设高度分别表达未知或证据。缺少受影响构件的约束依赖图、局部重算、空间/开口语义与独立编辑回读。
- 科研路线与数据/权重许可、尺度标定、几何和语义真值、输入划分、人工成本都需要逐项记录；本轮先建立最小可复现协议与候选矩阵，而非把论文结果宣称为实测。
- 数据及结果应留在受控工作区；公共案例先完成许可证与重新发布权核验。任何生产替换、工程审批或公开 Release 仍须对应授权。
