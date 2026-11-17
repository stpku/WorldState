# WorldState V0.2 Research Preview：自动化研发记录

## 发布体系与状态

负责人决定不再将自采房间、真人审核、现场测距、三组真人配对或完整三墙照片重建作为研究预览前置条件。新 [Research Preview 协议](../../benchmarks/RESEARCH_PREVIEW_PROTOCOL.md)与原 [WS-RealRoom 工程协议](../../benchmarks/ws_realroom/PROTOCOL.md)并存；原协议未变，工程级真实验收仍未完成。当前是研究预览候选，不是生产 Release 或版本标签。

## 合成数据与冻结匹配

基于现有 Room IR / IfcOpenShell 生成 4 墙矩形和 6 墙 L 形房间，将实际 IFC 网格交给 Blender 5.2.2 CPU Cycles 渲染。两种房间均生成 6 视角，包含家具遮挡、门窗、不同墙面纹理和光照；L 形场景的输入位姿加入 0.006 m 平移与 0.12° 旋转噪声。参考目录包含精确 IR、IFC、相机、Z 深度、语义/实例和可见性；原始输入照片及相机在独立目录。特征角点的接缝遮挡没有被强判为可见。

开发集使用 seed 717；冻结集使用私有随机种子，参考只存服务器隔离目录。冻结计划在运行前提交，固定每场景使用照片 1/2、GlueStick 与 Tiny RoMa、3 px 匹配阈值。首个生成的冻结目录因相机清单缺少 Studio 要求的来源字段被停止使用，未进行模型评测；修复输入契约并重新生成独立冻结集。源码和清单哈希固定，测试输出后没有针对该测试集调参。目录隔离无法阻止拥有服务器完全权限的恶意程序；不宣称密码学意义的盲测。

| 冻结场景 | 方法 | 提交点匹配 | 严格正确 / 可评 | 可见点正确 / 可见可评 |
| --- | --- | ---: | ---: | ---: |
| 3ad96a511bd4 | GlueStick | 0 | 无分母，NOT_MEASURED | 无分母 |
| 3ad96a511bd4 | Tiny RoMa | 1000 | 0/999 | 0/586 |
| 686c6a6176bb | GlueStick | 4 | 2/4 | 2/2 |
| 686c6a6176bb | Tiny RoMa | 1000 | 313/1000 | 313/923 |

严格分母把参考投影出画或被遮挡的匹配记为失败，源深度无效另列；深度/实例可见性容差 0.05 m。Tiny RoMa 使用 512×352 输入、GlueStick 使用原始小图，不能据此作公平速度排名。DeepLSD 在早期开发对照两图各检测到 4/6 条线，未建立跨图线匹配，因此不计对应准确率。实验不证明真实墙体识别；冻结测试没有提交独立重建模型，墙实例、尺寸和布局指标均为 `NOT_SUBMITTED`。开发集使用真值自身作为**评测器控制**仅核对了 4/4 墙与 IFC，无模型性能含义。

## WS-Agent 与模型修订

[固定任务清单](../../benchmarks/ws_agent/tasks.json)含 23 项模拟房间语言任务；真实 Codex `gpt-6.1-terra` 使用现有 Modeler/MCP，在每项隔离副本中执行。自动评分最初为 22/23；随后发现 A19 的预览实际返回的是不支持参数，Agent 却声称确认角度冲突，属于解释错误。保留原结果并只对原日志重新评分，严格结果为 **21/23**。另一失败是 A23：Agent 无版本恢复预览工具。规则模式同题为 0/23，因固定格式无法解析这些自然语言；另以其文档格式验证可正常修改墙高。拒绝/澄清题使用简单文本匹配，不能证明通用语义理解能力。

23 个 Agent 任务总计 1,556,883 输入 token（其中 1,330,176 缓存输入）、9,242 输出 token，各任务耗时之和约 496.58 秒；并发两任务，不能将耗时总和解释为实际墙钟时间或人工成本。实际费用与人工成本 `NOT_MEASURED`。[逐项结果](../../benchmarks/ws_agent/results/2026-11-17.json)含工具调用数、失败原因及初始/复核分数。

A20 的真实 Agent 建议经隔离 Playwright 自动确认后，在 Studio 按顺序将 `wall-2` 高 2.8→2.9 m、`opening-door` 偏移 1.0→1.2 m，保存版本 2 和 3；一次确认之前展示重新计算的影响范围。IfcOpenShell 检查 13 个产品 GUID 不变、schema 0 错误，未受影响的 4 个有几何构件顶点不变。保存中断的故障注入证明当前版本不会推进；可能产生孤立版本目录，需要检查。交互和确认均为自动化，不代表真人使用。

自生成示例的 wall-2 在 Blender 5.2.2/Bonsai 0.9.0.post1 中实际由 2.894→2.994 m，再由 `sync-ifc` 回写；13 个 GUID 保持，schema 0 错误。该模型及图像均为合成，不是照片推算。原有 CRASLAB/TUM 和前期 IFC/Bonsai 记录保持不变。

## 公开真实扫描开发诊断

对 ETH3D kicker 已冻结的单个已知位姿局部墙片，使用先前**不读取模型**得到的 9 个全场 RANSAC 平面提议，以及按固定步长采样的整个 scan1/scan2：没有依据候选位置裁剪参考。2,100 个候选表面样本到两幅全场扫描的最近点距离中位数分别 0.0253 和 0.0170 源单位；两扫描相互最近邻距离中位数 0.0285 和 0.0317 源单位。全场点到局部片的距离比例仅反映整个场景，不能叫墙体召回或完整性。全场平面仍可能是家具，且扫描与官方相机姿态共享配准，尺度未独立测量；墙实例与尺寸仍为 `NOT_MEASURED`。这不是盲测或工程验收。

## 安装、回归和限制

干净 CPython 3.12.3 环境按 `products/worldstate_bim/requirements-research-preview.txt` 安装后，已导入公开合成示例；新环境浏览器实测见运行目录。最初使用系统 Python 3.14 安装遇到无相容 NumPy 轮子及临时目录配额问题；随后按明确的 Python 3.12 和磁盘临时目录重试。第一次 3.12 导入又暴露缺少 `pycolmap`，已补入依赖并在新的虚拟环境重新安装。首次浏览器恢复步骤因测试脚本没有展开版本面板而超时，原失败截图保留；修正脚本后在新项目成功运行。

Core、产品及新增基准回归 **270 passed**，80 条 IfcOpenShell `datetime.utcnow()` 弃用警告。原工作区 5 处未提交修改、Core 公开契约、历史结果和现有用户项目均保留。自动化多浏览器在受限 `/tmp` 下的历史崩溃未被本轮证明完全修复；磁盘临时目录是测试缓解而非根因结论。真实 Windows 客户端、现场独立精度、人工成本和模型实际费用均 `NOT_MEASURED`。

现有 Studio 服务已切换到独立 `c8f3e85` 部署副本，沿用既有本地工作区、Tailscale 映射和权限。切换前备份工作区，7 个项目与模型文件的 SHA-256 在切换后不变；服务器端 Chromium 使用 Windows User-Agent 通过 HTTPS 验证 29 张照片、只读求解和 IFC 下载，项目版本与事件数未变。非法 Host、Origin 和缺少令牌的批量 API 请求均返回 403。服务器系统服务已启用，但本轮没有重启整机或实际操作 Windows 客户端。

按预览协议，本候选的既有 BIM 编辑与合成演示范围为 **Research Preview Ready**；照片建模与扫描语义仍为 `EXPERIMENTAL`。具体验收边界见[候选状态](../../acceptance/research-preview-20261117/STATUS.md)；没有合并 main、创建公开 Release 或打正式标签。

本地记录在 `~/.cache/worldstate-research-preview/`；公开结果摘要不包含 ETH3D 原图、扫描、受限权重或隐私资料。公开合成示例由自生成几何与材质构成，随仓库 MIT 许可分发；[Blender 手册](https://docs.blender.org/manual/en/latest/getting_started/about/license.html)说明其软件许可不自动覆盖用户创建的作品。[IfcOpenShell/Bonsai 官方说明](https://docs.ifcopenshell.org/introduction)分别列出 LGPL 与 GPL 许可。GlueStick 官方组合的 SuperPoint 为[非商业用途](https://github.com/cvg/GlueStick#licence-)，不打包其代码或权重。
