# WorldState：多构件修订与跨图视觉对应 — 2026-11-17

## 结果与边界

产品主线完成了隔离的 CRASLAB 多构件模型修订、真实 Codex 工具调用、Studio 确认、IFC 导出及 Bonsai 编辑回写。技术主线实际运行了 COLMAP 轨迹、GlueStick、DeepLSD、语义边界筛选和 Tiny RoMa；office 场景得到一个**未审核的局部几何面**，但其特征位于窗框附近，Agent 没有将其当作墙体，也没有产生新墙 IFC。两条结果不能互相替代。真实人工审核、独立场景精度和人工成本仍未测量，V0.2 保持 **NOT RELEASE-READY**。

本轮的实验、浏览器截图、原图衍生文件和模型运行轨迹均保存在 `~/.cache/worldstate-visual-correspondence/`，不提交受限 ETH3D 原图、模型权重或客户数据。ETH3D 用于 CC BY-NC-SA 4.0 约束下的非商业研究；kicker 和 office 均是开发场景，不是盲测房间。CRASLAB 示例来源和 CC BY 4.0 许可沿用仓库现有记录，其 Cloud2BIM 构件类别、墙厚和尺寸均未独立核实。

## A：多构件 BIM 与真实证据修订

创建独立的 `craslab-demo-v1`，未复制或关联任何未配准的照片。原始模型含 8 个墙候选、1 个楼板、5 个窗及其开口；没有门对象，也没有已确认的相邻墙拓扑。真实 Codex `gpt-6.1-terra` 读取对象类型、位置、宿主和开口关系，并逐次调用确定性预览工具。下面的确认均为隔离 Playwright 自动化操作，**不代表真人确认或人工效率**：

| 修订 | 模型参数变化 | 结果 |
| --- | --- | --- |
| 墙高增量 | 3.396 → 3.496 m，+10 cm | 预览后生成版本 2 |
| 窗开口偏移 | 1.150116 → 1.200116 m，沿宿主轴 +5 cm | 版本 3 |
| 窗开口宽度 | 1.314209 → 1.334209 m，+2 cm | 版本 4 |
| 墙长 | 9.2 → 9.3 m，+10 cm | 版本 5 |
| 墙体起点 X | 10.33 → 10.35 m，整墙沿 X 平移 +2 cm | 版本 6 |
| 墙高绝对值 | 3.496 → 3.48 m，输入 348 cm | 版本 7 |

目标墙的三个开口和三个窗均列为影响范围；已有开口越界、重叠与拓扑约束由现有几何检查拒绝。本轮新增未关联墙轴相交提示；它只是二维轴线与竖向范围诊断，**不是完整实体碰撞检查**。该模型没有相邻墙连接，因此没有证据证明相邻连接正确，也没有真实门对象可供本轮验证。模型中的米制数字是源模型参数，不是本轮现场测量。

IfcOpenShell 独立解析版本 1 和 7，IFC4 schema 检查 0 项错误，23 个 `IfcProduct` GUID 集合一致；10 个未列入影响范围、可生成几何的墙/窗/楼板，其世界坐标顶点集合一致。顶点对照不等于语义正确性或完整实体相等。首次对照脚本曾因提早释放 IfcOpenShell 的几何所有者而错误报告楼板变化；修正生命周期后重新运行，原始失败和修正报告分别保留为 `craslab-agent-identity-report-v1.json` 与 `-v2.json`。

Blender 5.2.2 / Bonsai 0.9.0.post1 的原生编辑操作实际将版本 7 的墙高从 3.48 改为 3.55 m，再通过现有 `sync-ifc` 回写 IR 版本 8；23 个产品 GUID 仍一致，IFC4 schema 检查 0 项错误。脚本操作标为 `analyst`，不是现场测量。外部修改仅同步请求的受支持属性，其他 IFC 元数据不会自动导入。

对于具有真实照片和相机来源的 ETH3D kicker 门上局部墙片，复用了此前明确记录的**受控高度扰动**：0.333911 m 的假设尺度模型被人为改为 0.374 m。真实 Agent 查看两张哈希匹配照片及投影，调用受限确定性工具拟合高度，并在隔离浏览器确认后生成 IFC 版本 4。两张用于拟合的原始顶边线合并 RMS 从 **25.106 px 降至 0.205 px**，最大线残差 0.284 px。此结果只说明对参与拟合的观测一致；原观测、语义及相机未独立核实，尺度和墙厚仍为假设，不能称为现场变化、独立精度或完整房间。项目 `projection-demo-v2` 和 `projection-browser-v2/` 保存实际工具轨迹及确认记录；新 IR 保留参与拟合的照片、相机哈希和残差。

Studio 新增显式的“仅已有模型”模式；该模式不暴露照片工具，发送模型信息前仍需确认。真实照片模式支持查看未确认 AI 点线建议。本地视角推荐使用已求解对象的投影范围、对象区域图像质量、视线方向、现有边界/语义观察及视差；对于尚未求解的对象，若已有两个视角中的同名点满足既有三角化门槛，也可以仅依据该未确认三维点提出视角建议，不能推断整面墙可见。遮挡始终标为未知，建议不等于可见性真值。kicker 现有局部对象的开发数据中有 6 个可投影视图，首两组为图 9/26 和 9/19，估计视差分别约 23.08°、21.74°。隔离浏览器已实际授权并向模型发送图 9、19、26；Agent 记录待确认墙角，但因家具遮挡与可信对应不足没有生成新墙。界面要求在发送前确认列出的全部照片和模型信息。没有足够对象几何或跨图观察、旧观察失效或源相机/照片哈希改变时，不给出有效推荐。

## B：同输入照片的 CPU 视觉匹配

两组照片分别为 kicker 图 1/13 和 office 图 1/7；使用各自 ETH3D **已知位姿**，不是自动相机恢复。GlueStick 和 DeepLSD 缩至最长边 1024 px；Tiny RoMa 使用 512×352 以控制 CPU 内存。表中的极线 Sampson 残差换算为原图像素，仅表示与已知位姿的几何一致性；UPerNet 语义及线段物理对应均未经真人审核。

| 场景/方法 | 实际运行结果 | 限制 |
| --- | --- | --- |
| kicker / 已有 COLMAP | 同图对共享轨迹 0 | 复用既有轨迹，耗时不含特征提取 |
| kicker / GlueStick | 114 个点候选，32 对线，1 对语义边界候选；点极线残差中位数 14.82 px | 多个匹配落在球桌、柜体与灯具上 |
| kicker / DeepLSD | 两图各 505/398 条检测线，语义边界候选 7/18 | 仅逐图检测，未实现跨图线匹配 |
| kicker / Tiny RoMa | 采样 1000 点，极线残差中位数 90.36 px | 稠密采样不是 1000 个正确物理点 |
| office / 已有 COLMAP | 99 条共享轨迹，极线残差中位数 0.74 px | 原始已缓存轨迹，和缩图方法分辨率不同 |
| office / GlueStick | 425 个点候选，99 对线，4 对语义边界候选；点极线残差中位数 3.40 px | 白板、桌面、窗框都产生特征 |
| office / DeepLSD | 两图各 307/277 条检测线，语义边界候选 15/17 | 只测线检测，不把它称为匹配 |
| office / Tiny RoMa | 采样 1000 点，极线残差中位数 7.11 px | 使用较小、略经拉伸的推理输入 |

同图对的单次运行：GlueStick 分别 7.93/6.91 秒，DeepLSD 18.84/19.29 秒，Tiny RoMa 2.70/3.06 秒。算法输入分辨率、缓存状态和样本量不同，这些数字不是质量或公平成本排名。再次运行 office 时，50 ms 进程 RSS 采样峰值 GlueStick 约 **1037 MiB**、DeepLSD 约 **1728 MiB**；分别测量，未与大量浏览器并行。

office 的 99 对匹配线中，确定性计算得到 21 个满足该开发诊断条件的跨图线交点，未找到四条互相连接成闭环的匹配线。选择四个未经确认的交点后，复用既有 Modeler 得到四点局部几何拟合：点重投影 RMS 0.989 px、最大 1.549 px、估计视差约 3.01°–5.26°。平面约束是模型先验，所选四点之间的边界并未全部由匹配线闭合。真实多模态 Agent 在两张图及交点叠图中将它们归为窗框/窗洞候选，并将另一些点归为桌面家具候选，因此没有调用墙体导出。该几何实验因现有 Modeler 接口要求 `IfcWall` 类型而传入该类型作为**求解器占位符**，结果没有导入 Studio 或导出 IFC，不构成墙体分类。

已生成 15 项跨两场景的线对应审核任务 `runs/correspondence-review-v1/index.html` 与 `tasks.json`，含原图 SHA-256、相机 SHA-256、原图像素、可见性未知和分类问题。所有项目保持 `AWAITING_INDEPENDENT_HUMAN_REVIEW`；家具、窗框、遮挡及真实墙角的对应 precision/recall 均为 **NOT_MEASURED**。AI 识别不是独立真人审核。

### 第三方版本与许可

- [GlueStick 官方仓库](https://github.com/cvg/GlueStick) commit `7d816730ef939caa1c61e2564eceda77304874fa`，代码 MIT；其 SuperPoint 组件使该官方组合受非商业限制。GlueStick 权重 SHA-256 `5a7013a1987978c23d71f338f3673d80f9090c4791a955c2f9e1ed4f4dbb3207`，SuperPoint 权重 `52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e`。
- [DeepLSD 官方仓库](https://github.com/cvg/DeepLSD) commit `f7d9d6258c0cd25d4f6eea882853565403d289be`，官方说明代码及提供的权重为 MIT。Wireframe 权重 SHA-256 `6d0c1bc78f79eb9e564404e4fef797d12ab18f30ba596208cca16116c2429406`；只使用官方 inference 路径，未使用 Ceres 线精化。
- [RoMa 官方仓库](https://github.com/Parskatt/RoMa) commit `77f8d68803526dcddfd9b7a46bc76125bdc25f15`；实际运行 Tiny RoMa，权重 SHA-256 `3e2ac3481f754243eb3f5c8ea0358667561f1ce139c3edd03d7d21927ffba30c`。XFeat 来源 [官方仓库](https://github.com/verlab/accelerated_features)，commit `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`，代码 Apache-2.0；权重 SHA-256 `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b`。商业使用前须分别复核各权重和数据的使用权。
- CPU 环境：Python 3.12.3、PyTorch 2.5.1+cpu、OpenCV 4.10.0、NumPy 2.1.3、SciPy 1.13.1，PyTorch 2 线程。`pytlsd` 为 GlueStick 指定版本 `4180ab8990ae68cc9c8797c63aa1dc47b2c714da`，使用隔离目录内的匹配 Python 3.12 头文件编译，未安装或修改系统软件。官方权重加载路径使用 PyTorch pickle；只应加载可信、经过核验的来源。

## Agent 成本与稳定性

模型模式仅注册必要的三个 MCP 工具；完整的几何前后详情保存在本地建议文件中，模型调用只接收精简预览。对同一 CRASLAB 开发任务，两次实验中 `preview_revision` 单次返回约由 23,300 字符降至 885–930 字符；总输入 token 从 143,489 降至 92,080，工具调用从 13 次变为 11 次。另一次旧运行是 88,959 token，说明样本少、模型调用路径变化，不能声称稳定的整体成本下降。实际计费金额未取得，**NOT_MEASURED**。跨图 office Agent 首次超出 30 条工具限制被拒，随后按上限重试；失败记录保留。

原始并发崩溃已在只读隔离负载中复现。一个 Chromium 加载并解码 6 张预览通过；三个使用 `/tmp` 的双浏览器尝试均有一个页面崩溃；两个使用磁盘隔离 `TMPDIR` 的双浏览器尝试均通过，每次共解码 12 张预览。一次对照中浏览器进程 RSS 总和峰值约 2.0–2.1 GiB（共享页重复计数），服务约 295–382 MiB；可用内存最低约 4.9–5.0 GiB，swap 接近耗尽，cgroup `oom_kill` 计数未变化。Chromium 使用的启动器带 `--disable-dev-shm-usage`，日志出现软件 WebGL 的 ReadPixels stall。磁盘临时目录可作为测试环境缓解，但这些观测不能证明唯一根因，也不能推出实体 Windows 浏览器表现。测试工具新增可选 `--browser-tmp`，不隐藏或自动重试写入失败。

Core 与产品全量回归 **263 项通过**，依赖 IfcOpenShell 的 72 条 `datetime.utcnow()` 弃用提示保留。使用磁盘临时目录的三次连续跨图标注回归各通过，故障注入也通过；这些是自动化而非真人操作。推荐视角的首次浏览器脚本因把相同照片集合的顺序当成不同权限而误报失败；保留该次运行，随后仅以只读方式检查已完成任务并修正测试断言，没有重发模型写入。

## 现有 Studio 部署复核

现有服务已切换到独立的 `ea0ddac` 部署副本，沿用原有项目、回环监听、可信 HTTPS 域名和 Tailscale 配置；切换前备份了用户工作区，切换后 7 个项目及模型文件的 SHA-256 与切换前一致。用户 systemd 服务为 enabled，linger 为 yes，故配置支持登录前随用户管理器恢复；本轮没有重启整台服务器，因此实际重启恢复仍未验证。

服务器 Chromium 使用 Windows User-Agent 访问现有 HTTPS 地址，证书校验通过：29 张照片与相机可读取，照片预览、已有对象只读求解（不持久化）及 IFC 下载成功；模型状态版本和项目事件数不变。新界面可切换仅模型模式，本地推荐出 6 张视角且均标记遮挡未知；取消确认没有发起 Agent 任务。非法 Host、非法 Origin 和缺少 CSRF 令牌的请求均返回 403。结果保存在 `runs/live-ea0ddac-tailnet-v1/`、`live-ea0ddac-agent-v1/` 及 `live-ea0ddac-features-v1/`。这些是服务器端浏览器检查，不代表已经在真实 Windows 客户端测试。

## 复现与产物

所有命令从仓库根目录执行；路径应替换成已下载并验证的本机资料。原始照片、外部代码与权重均不放入 Git。

```bash
PYTHONPATH=. python benchmarks/ws_realroom/prepare_craslab_model_demo.py \
  --source examples/bim_real_scan_craslab/room_round3 \
  --output /path/to/new-private-project --operator automation

PYTHONPATH=. python benchmarks/ws_realroom/compare_visual_correspondence.py \
  --workspace /path/to/office-project --masks /path/to/office-known-pose-masks \
  --images 1 7 --mode gluestick --upstream /path/to/GlueStick \
  --weights /path/to/checkpoint_GlueStick_MD.tar --output /path/to/new-output

PYTHONPATH=. python benchmarks/ws_realroom/prepare_correspondence_review.py \
  --sample /path/to/kicker-project /path/to/kicker-gluestick-output \
  --sample /path/to/office-project /path/to/office-gluestick-output \
  --output /path/to/new-private-review
```

`probe_line_intersections.py`、`prepare_line_intersection_project.py`、`studio_craslab_agent_browser.cjs`、`studio_projection_agent_browser.cjs` 和 `studio_recommendation_agent_browser.cjs` 保存对应的开发实验入口；浏览器脚本只允许本地、隔离、`automation` 项目。`verify_room_revision.py` 独立检查 IFC schema、身份和未受影响构件的顶点。真实 Agent 的模型调用、token 与工具记录保存在各自私有运行目录。模型服务实际费用、真人操作与效率仍为 **NOT_MEASURED**。
