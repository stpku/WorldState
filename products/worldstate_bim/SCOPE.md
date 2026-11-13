# WorldState BIM 产品目录作用域

本目录实现 WorldState 的第一个领域产品；其北极星是 Evidence-to-Editable World，设计决策见 [ADR 0004](../../docs/adr/0004-evidence-to-editable-product-scope.md)。

允许产品自有图像/深度/点云处理、三维几何、建筑构件、IFC 编译、用户交互适配器、独立可选依赖和产品验收；不得把它们导入 `src/worldstate`，也不改变既有 Core、provider wire 或消费者的语义。通用 Agent 会话/工具循环由外部 Harness 负责；本目录只能定义受限工具和交换契约。

图像、几何与 IFC 属性需可追溯；推断、模拟、未知和冲突不能标记为观测。真实输入驱动的中间点云不代表已经生成墙；Mesh 不代表可编辑 IFC。未经核验的尺度声明不能视为经过独立校验的标尺。私有图片与权重留在仓库外，数据许可及发送到外部提供方的权限必须明确。

本目录保留 JSON→IFC v0.1 与 RGB-D 单墙路径；新增 room IR 0.3、Cloud2BIM 候选适配、开口 IFC、受控编辑回写和本地 Studio。真实扫描样例仍有未确认和隔离构件，照片路径仍是人工选区局部墙面，尚未构成自动完整照片→IFC 管线，也未通过独立房间验收。
