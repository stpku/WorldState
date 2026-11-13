# WorldState BIM 产品目录作用域

本目录实现 WorldState 的第一个领域产品；其北极星是 Evidence-to-Editable World，设计决策见 [ADR 0004](../../docs/adr/0004-evidence-to-editable-product-scope.md)。

允许产品自有图像/深度/点云处理、三维几何、建筑构件、IFC 编译、用户交互适配器、独立可选依赖和产品验收；不得把它们导入 `src/worldstate`，也不改变既有 Core、provider wire 或消费者的语义。通用 Agent 会话/工具循环由外部 Harness 负责；本目录只能定义受限工具和交换契约。

图像、几何与 IFC 属性需可追溯；推断、模拟、未知和冲突不能标记为观测。真实输入驱动的中间点云不代表已经生成墙；Mesh 不代表可编辑 IFC。未经核验的尺度声明不能视为经过独立校验的标尺。私有图片与权重留在仓库外，数据许可及发送到外部提供方的权限必须明确。

本目录现有 JSON→IFC v0.1 是合成提案可运行原型；`two_view.py` 是任意尺度稀疏重建实验，`visible_surface.py` 从人工圈定的 RGB-D 区域拟合可见表面片段。它们尚未构成自动照片→IFC 管线。
