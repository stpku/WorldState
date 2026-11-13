# DSH → WorldState BIM：受限工具接口和运行状态

2026-11-13 第三轮：本机部署的 `dsh-web.service`、`dsh-gateway.service` 和 `dsh-auth.service` 均为 active/running。只读探测显示本机 Web `127.0.0.1:3080` 和网关 `127.0.0.1:9092` 可达，但当前会话收到 HTTP 401；没有读取或输出任何凭据，也没有绕过认证。Web profile 文件出现 `deepseek-flash` 和 `dsh-vision-router` 名称，这只证明配置文本引用，并不证明当前服务成功加载、可调用或有视觉授权。第二轮独立 headless profile 的最小任务返回 `MISSING_CREDENTIAL`；**不能据此认定 Web 服务的模型配置或凭据也缺失**。当前会话无法验证部署服务中的模型调用、图像输入、结构化输出、MCP 调用与反馈修复，均为 NOT_TESTED。

`dsh web --help` 在本机触发插件启动日志，其中指出 rc.2 插件与 rc.1 runtime 版本不兼容；这是独立风险，不证明 401 的原因。没有修改服务、插件、凭据或发布设置。

## 已实现的产品工具

[modeling_tools.py](modeling_tools.py) 提供本地 Python 函数，可由外部 Harness 的授权适配器包装：

- `inspect_evidence(model)`：只读来源和状态。
- `propose_elements(model)`：列出 IR 中已有的未确认候选，明确标记不执行新推理。
- `inspect_element(model, id)`：读取属性、节点、约束和冲突。
- `apply_constraint(...)`：在现有几何满足时增加有来源的约束；冲突时报错。
- `update_element(...)`：版本化修改参数，传播角点并检查开口。
- `validate_geometry(model)`：列出显式冲突，不把通过检查称为实测准确。
- `compile_ifc(model, output)`：仅生成新本地 IFC 文件，不覆盖。
- `compare_revisions(before, after)`：按稳定 ID 比较构件和节点。
- `sync_ifc(...)`：在全模型校验通过后回读一个受支持的外部 IFC 修改。

这些函数不是 DSH MCP 注册结果，也不是 Agent 会话、运行循环、权限或调度器。DSH 工具调用和自主反馈修复尚未实测；仓库内的直接 Python 测试和 Studio 的明确标注本地规则命令不能冒充 DSH 调用成功。

旧的 `worldstate-bim-proposal/0.1` 和 `parametric-ir/0.2` 单墙路径保持兼容；多构件产品路径使用 `worldstate-bim-room-ir/0.3`。视觉模型和几何 provider 输出必须带来源、坐标与不确定性；对不可见的墙、开口、材料和尺寸保留未知/假设。Agent 不得直接写任意 IFC 文本、覆盖权威模型或执行工程审批。

要开展真实 DSH 验证，需通过已批准的会话认证或管理员提供的受控接口，在不接触明文密钥的前提下验证已配置模型、图像支持和工具注册；若不具备授权，继续使用本地受控工具和人工参数操作。
