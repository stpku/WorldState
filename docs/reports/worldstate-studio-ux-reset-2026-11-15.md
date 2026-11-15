# WorldState Studio UX Reset — 2026-11-15

## 范围与限制

工作台统一了首页和多视图 Modeler：左侧为构件与照片，中间为真实 IFC 三维几何及两张原始照片视图，右侧为属性、证据、标注和本地规则助手。照片标注、跨图建议、局部放大、候选求解、IFC 导出、参数修改、外部 IFC 回写及版本历史使用既有后端；照片入口和旧版兼容工具仍可访问。原始 JSON 与高级设置不再占据主要操作区。

三维渲染使用本地的 Three.js r128（MIT，许可证随代码保存），支持旋转、平移、缩放、正视/俯视、构件选择、网格、坐标轴和近似尺寸。已保存的 IFC 几何与源坐标中的未验证候选分开显示，不把两个坐标系叠加成同一模型。AI 视觉建议需要人工核查；右侧助手是明确标识的本地规则模式，不是 DSH 调用。

本次没有改变 Core、建模算法或冻结的验收协议。实际数据为 ETH3D kicker 开发场景，依据项目此前许可审查按 CC BY-NC-SA 4.0 作非商业研究。照片、截图、测试工作区及 IFC 衍生物仅保存在服务器缓存，不提交仓库。已有局部墙不是完整房间，假设尺度、墙厚等并未变成实测数据。未进行真人试用或人工成本配对评测，V0.2 仍为 **NOT RELEASE-READY**。

## 浏览器结果

使用含 29 张真实照片、29 个已注册相机和既有 IFC 草稿的独立工作区。所有点击均为 `automation`，不代表真人标注、正式验收或人工耗时。

| 页面及尺寸 | 先前文档高度 | 新文档高度 | 结果 |
| --- | ---: | ---: | --- |
| 首页，1440×900 | 1412 px | 900 px | 核心操作可见，无整页滚动 |
| Modeler，1440×900 | 2116 px | 900 px | 同上 |
| 首页，1920×1080 | 1412 px | 1080 px | 同上 |
| Modeler，1920×1080 | 2116 px | 1080 px | 同上 |

上一轮报告与截图：`~/.cache/worldstate-milestone-a/playwright-review-6NWPBO/`。本轮截图与记录：`~/.cache/worldstate-milestone-a/ux-reset-browser-final2/`、`~/.cache/worldstate-milestone-a/ux-reset-evidence-final3/`。本机对照页为 `~/.cache/worldstate-milestone-a/ux-reset-comparison/index.html`。

实际浏览器操作包括：已有墙的照片点修改、求解、IFC 导出；创建新的未确认候选，连续提交 10 次跨图观察，延迟网络响应后再排队 4 次标注，均成功保存；该候选不满足墙体几何条件，IFC 编译器按预期拒绝，而非将其冒充真实墙。放弃候选后重新求解并导出，前后同一墙体 GUID 保持。独立 IFC 引擎读取测试导出。另一次浏览器回归通过上传入口提交已存在的真实照片，实际修改高度、运行本地规则指令、使用 CPU UPerNet 分析照片（该次 6.832 秒、5 项未确认建议），并从三维视图选择真实 IFC 墙并显示尺寸。照片列表实际峰值为两张缩略图同时请求；正式复测未捕获 API 请求失败或页面脚本异常。

## 连续标注问题

先前审查的输出没有保留原始 `Failed to fetch` 的网络细节；服务结束记录来自测试清理，不能证明原服务崩溃。对旧界面的独立复现中，连续标注期间照片画布等待超时而服务仍存活。审查和回归暴露了两个具体风险：大图哈希校验与解码原来在项目共用锁内执行；同一照片刷新时清空画布，可能与下一次点击竞争而丢失观察。

新实现将授权照片的索引快照与磁盘读取分开，仍逐次验证原始文件哈希，并限制大图解码并发；同图刷新保留已加载画布。观察请求按用户点击次序排队，并固定每次点击时的对象、照片和特征；连接失败不会自动重复写入。随后一次压力复测还发现照片列表同时加载多张大预览时，浏览器出现 `ERR_INSUFFICIENT_RESOURCES`：为此改用按可见区域加载的 240 像素缩略图，客户端最多同时请求两张，并避免选择构件时重建整个列表。一次真实照片压力检查中 12 个预览与 4 次状态读取均为 HTTP 200，状态读取最慢约 0.009 秒。这是本机单次诊断，既不是性能保证，也不足以证明先前每次网络错误的唯一原因。

## 复现

在安装产品依赖的环境中运行：

```bash
python -m pytest -o addopts='' -q tests products/worldstate_bim/tests
```

本机 Core 与产品测试共 249 项通过；依赖 IfcOpenShell 发出了 `datetime.utcnow()` 弃用提示。

浏览器交互需先从演示工作区建立**独立副本**，将副本项目的操作者设为 `automation`，用独立端口启动 Studio 并配置已有的本地 ONNX 模型。不得将下列修改性脚本指向真人项目；脚本会检查操作者及 `127.0.0.1` 地址，输出目录必须为新路径。

```bash
NODE_PATH=/path/to/node_modules WS_CHROMIUM=/path/to/chromium \
  node benchmarks/ws_realroom/studio_ux_reset_browser.cjs \
  http://127.0.0.1:PORT/ /path/to/general-track-input.json /path/to/new-output
NODE_PATH=/path/to/node_modules WS_CHROMIUM=/path/to/chromium \
  node benchmarks/ws_realroom/studio_ux_evidence_browser.cjs \
  http://127.0.0.1:PORT/ /path/to/another-new-output /path/to/existing-real-photo.jpg
```

用户的具体操作说明见 [首次真人试用](../../benchmarks/ws_realroom/MILESTONE_A_USER_TRIAL.md)。原有五处用户修改和现有工作区不纳入提交。允许的 Host、Origin 和令牌校验仍由原服务器执行，静态资源采用明确路径白名单。
