# WorldState Studio：多模态建模 Agent 与稳定性 — 2026-11-16

## 实际结果

**部分完成。** Codex CLI 的 `gpt-6.1-terra` 已在隔离工作区实际查看 ETH3D 照片，并通过受限 MCP 调用场景、照片、特征轨迹、视觉假设和参数修改预览工具。kicker 与 office 的本轮照片都没有产生可靠的新墙面或新 IFC；Agent 遇到遮挡和不足的墙面对应后停止，并保留未确认假设和失败记录。当前结果不是完整房间、独立精度或效率验收，V0.2 仍为 **NOT RELEASE-READY**。

Studio 增加可选的 AI 建模模式。用户选择两张已注册照片并明确同意发送给配置的模型后，Agent 才能读取这两张照片；它只能访问所选项目的受限工具，不能运行通用 shell，也不能自行选择其他照片。视觉假设绑定原图和相机哈希、原始像素区域、模型来源与不确定性，显示在原图上时标为未确认。点、线和面建议保留为 AI 提议；多视图求解使用既有确定性几何门槛，平面语义目前只记录，未作为几何损失。

已求解候选与修改建议先保存在项目外的私有目录。用户必须明确选择并确认，Studio 才会将候选导入或应用参数修改；修改前会重新核对模型版本、照片、相机和相关轨迹。缺少操作人员批准的尺度、朝向、厚度和矩形近似时，Agent 工具拒绝自行编译 IFC。任务结果和工具记录保留在本机；服务重启时可恢复已完成任务，中断任务标为 `INTERRUPTED`，不会自动重试。

## 稳定性复验

独立复验的 `waitForFunction` 在动画帧中请求状态，缺少明确的轮询间隔。受控重放也实际捕获 `net::ERR_INSUFFICIENT_RESOURCES`；独立复验的 SIGTERM 是测试清理，不能证明服务崩溃。状态读取现在按 300 ms 间隔轮询，遇到网络错误或临时 502/503/504 最多重试三次并记录失败；写入结果不明时提示刷新核验，绝不自动重发。服务端使用带超时的 HTTP/1.1 连接复用，拒绝的 POST 关闭连接，避免未读取的请求体留在连接中。

`~/.cache/worldstate-milestone-a/ai-agent-stability-v2/` 和 `ai-agent-stability-final2/` 各完成三次独立完整回归：每次 10 次跨图观察和 4 次排队修改均保存，未捕获请求失败。故障注入让状态读取连续返回两次 503 后恢复；另一项测试让写入在服务器成功后丢失响应，确认只发送一次、提示状态不明并可手动刷新。

一次同时运行模型和其他测试的尝试中，Chromium 页面发生崩溃，记录在 `ai-agent-stability-final/continuous-1/`；同批其余两次通过。可用日志不能证明崩溃的根因，因此不能声称高负载下所有浏览器资源问题已解决。

## 真实模型与工具记录

| 开发场景 | 同一输入照片上的规则诊断 | 实际多模态 Agent 结果 |
| --- | --- | --- |
| kicker，照片 3 和 13 | 43 条共享轨迹，其中 28 条在两张 UPerNet 掩膜中均标为墙，7 条标签不一致。 | 两项未确认视觉假设；检查叠图后认为墙面可靠对应不足，0 个已求解新候选、0 个新 IFC。一次运行 69.38 秒，记录 97,683 输入 token（其中 70,272 缓存）、1,306 输出 token。 |
| office，照片 1、2、7、24 | 11 条四图共享轨迹，其中 1 条在四张掩膜中均标为墙，1 条墙/非墙标签不一致。 | 两项未确认视觉假设；检查到的轨迹主要位于白板边框及附件，0 个已求解新候选、0 个新 IFC。一次运行 73.69 秒，记录 141,033 输入 token（其中 117,504 缓存）、1,079 输出 token。 |

上述规则统计复用了已有语义掩膜；墙标签、标签分歧和轨迹数量都不是经审核的墙实例真值或错误对应率，不能用作精度排名。模型费用未取得计费数据，标为 `NOT_MEASURED`。真人直接使用 Modeler 的对照未进行，人工操作次数、人工成本和合格模型效率均为 `NOT_MEASURED`。

在 kicker 的另一次真实 Agent 交互中，模型检查既有局部墙片段并提出长度增加 0.2 m 的预览；隔离浏览器确认后，IFC4 从版本 3 更新到版本 4，墙体 GUID 保持 `15K4a41pXJxPHst4KdtLRH`。该尺度仍是假设，模型没有相邻墙或门窗，Agent 明确表示无法检查这些对象，不能当成实测或完整房间。运行记录位于 `~/.cache/worldstate-milestone-a/ai-agent-systemd-edit-v1/` 及对应 `ai-agent-systemd-runs/`。

另一次真实测试中，模型先错误地将 `0.2 m` 当作最终墙长，随后提出正确的增量预览。旧界面默认选中了早先建议，自动化复测因此应用了错误值；此失败保存在 `ai-agent-systemd-edit-final/`，只影响隔离副本。界面现要求显式选择建议，并展示修改前、修改后及变化量；随后在另一隔离版本中选择正确建议，实际增量为 0.2 m，GUID 保持。该自动化确认不代表真人审核。

最终同权限 systemd 隔离测试在原始版本上再次完成真实 Agent 修订：长度约 `0.9532 → 1.1532 m`，增量 `0.2 m`，结果仍需现场验证；记录在 `ai-agent-recovery-browser-v1/`。重启该隔离服务后，已完成任务及建议被恢复，已经应用的旧建议在界面中标为过期。Core 与产品全量测试共 **258 项通过**；依赖 IfcOpenShell 发出 `datetime.utcnow()` 弃用提示。

实际浏览器及 systemd 隔离运行、照片分析、工具调用、拒绝和候选数据分别保存在 `~/.cache/worldstate-milestone-a/ai-agent-systemd-browser-v4/`、`ai-agent-systemd-edit-final2/`、`ai-agent-office-run2/`、`ai-agent-kicker-comparison.json` 和 `ai-agent-office-comparison-v2.json`。ETH3D 数据和衍生结果按此前审查的 CC BY-NC-SA 4.0 仅用于非商业研究，未提交仓库。

## 现有 Studio 部署

已在既有 Studio 用户服务上启用可选 Codex Agent，地址仍为 `https://skyswind.tailf4fad8.ts.net:18790/`。仅增加该服务的 systemd drop-in 和私有网络环境文件；原服务单元、Tailscale Serve 配置与独立扫描审核服务未修改。Agent 输出位于项目外的私有目录，现有用户项目在部署前已备份。

部署后的服务端 Chromium 只读检查验证了 HTTPS、29 张照片、三维模型、非持久化求解、IFC 下载及 Agent 模式入口；未在正式用户项目启动模型任务，项目状态版本与事件数未变。错误 Host、错误 Origin 和错误令牌返回 403，未确认照片传输的 Agent 请求返回 400。在线检查使用 Linux Chromium 的 Windows UA，不代表实体 Windows 设备实测；systemd 服务已启用且 lingering 开启，本次未重启整台服务器。

## 配置与复现

可选 MCP 依赖与 Core 分离。管理员在已授权的环境中安装并指定一个项目和项目外的私有输出目录：

```bash
npm ci --ignore-scripts --prefix products/worldstate_bim/agent
python -m products.worldstate_bim.studio_server \
  --workspace /path/to/workspace --enable-codex-agent \
  --agent-output /path/outside/workspace --agent-codex /path/to/codex \
  --agent-node /path/to/node --agent-model gpt-6.1-terra --port 8766
```

只有选中照片获得使用和向提供商传输的授权时才应在界面确认。工具最多读取授权照片，单任务限制 60 次工具调用、12 次图片读取及 300 秒；模型调用、工具拒绝、图片哈希和 token 用量可在私有运行目录复核。实际费用取决于授权账户及服务，不在此推算。无可用配置时仍为本地规则模式。

`benchmarks/ws_realroom/run_studio_resilience.py`、`studio_ux_retry_check.cjs` 和 `studio_agent_browser.cjs` 只能指向隔离 `automation` 项目。`prepare_agent_photo_project.py`、`run_codex_modeling_agent.py` 和 `compare_agent_routes.py` 分别用于新建研究副本、显式授权的真实模型实验和同输入照片的有限诊断。测试与依赖命令需在仓库根目录设置 `PYTHONPATH=.`；运行结果不得覆盖现有用户工作区或提交受限照片。

DSH 项目级程序化授权仍是外部阻断；本轮没有声称 DSH 调用成功，也没有再进行匿名探测。正式 Room-Test 和至少三组真人配对效率实验仍未完成。
