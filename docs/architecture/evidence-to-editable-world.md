# WorldState — Evidence-to-Editable World

架构草案，2026-11-13。图例：**已实现**仅指可运行的现有局部能力；**实验中**不代表产品可用；**规划**未实现。矢量总图见 [SVG](evidence-to-editable-world.svg)，决策见 [ADR 0004](../adr/0004-evidence-to-editable-product-scope.md)。

## 能力、数据与控制流

```mermaid
flowchart LR
  E["证据接入 / 标定 / 许可<br/>规划"] --> R["重建 Provider<br/>双视图与相对深度实验中"]
  R --> S["可见范围与语义 / 参数模型<br/>规划"]
  S --> A["受限构件校验 → IFC<br/>合成墙编译已实现"]
  A --> V["独立验证 / 编辑 / 版本<br/>规划"]
  V -- "误差与修订" --> S
  E -. "来源、时效、未知与冲突" .-> C["WorldState Core<br/>状态契约已实现"]
  S -. "证据投影（规划）" .-> C
  V -. "版本/变化投影（规划）" .-> C
  H["DSH 或其他 Harness<br/>适配器规划"] -. "受控工具调用" .-> E
  H -. "受控工具调用" .-> R
  H -. "受控工具调用" .-> S
  H -. "受控工具调用" .-> V
  G["GeoTask：任务上下文<br/>外部"] -.-> H
  AR["AgentReality：grounding<br/>外部"] -.-> H
```

实现顺序以真实房间为主线，不建设长期运行时。照片少/未标定时使用不确定的先验候选和用户补测；密集重叠照片可尝试 SfM/MVS；有深度/点云时使用显式传感器融合。所有路线在独立尺度、坐标、采集时间和遮挡上须说明依据。

## 对象生命周期（规划，已有 GUID 机制可复用）

```mermaid
stateDiagram-v2
  [*] --> EvidenceRegistered: source hash / license / time
  EvidenceRegistered --> GeometricCandidate: algorithm + frame + uncertainty
  GeometricCandidate --> SemanticCandidate: visible support / inference
  SemanticCandidate --> ParametricDraft: constrained proposal + anchors
  ParametricDraft --> VerifiedRevision: independent evidence + review
  ParametricDraft --> UnknownOrConflict: missing or disputed evidence
  VerifiedRevision --> Affected: new evidence / edit
  Affected --> ParametricDraft: dependency-scoped recalculation
  UnknownOrConflict --> ParametricDraft: new evidence or explicit correction
```

不可将 `VerifiedRevision` 简化成某个模型的 confidence。可见面、不可见厚度及门窗开口等属性应分别追溯。历史版本不覆盖；删除/拆分/合并应有显式身份事件，不能只依据新几何重新生成 ID。

## Harness 建模与修复时序（规划）

```mermaid
sequenceDiagram
  actor U as 用户
  participant H as 可替换 Harness
  participant T as 受限产品工具
  participant P as 重建/语义 Provider
  participant I as IFC 编译器
  participant V as 验证器
  U->>H: 输入已授权证据和建模目标
  H->>T: 检查授权、清单、尺度、缺失
  T->>P: 运行所需算法（受限输入）
  P-->>T: 候选 + 坐标、来源、不确定性
  T-->>H: 结构化校验错误 / 未知
  H->>T: 约束内请求局部更正
  T->>I: 校验后的版本化模型提案
  I-->>V: IFC + 来源映射
  V-->>H: 几何/语义/拓扑误差、失败项
  H-->>U: 模型、未知、需补测项和人工确认
```

## 建议契约（均未冻结、除现有 proposal 外未实现）

| 契约 | 最小字段/行为 | 不变量 |
| --- | --- | --- |
| `EvidenceAsset` | 内容 hash、来源与许可、捕获时间、媒体、坐标/内参、获取方式 | 保留时间/许可未知；外部路径须受权限约束。 |
| `GeometryCandidate` | provider/version、输入哈希、坐标系、单位与尺度依据、点/面、相机、可见性和不确定性 | 不把未知尺度写成米；候选可重放，算法不得被当作真值。 |
| `ElementCandidate` | 稳定 ID、类别、参数与每个属性的证据/观测模式、拓扑依赖、待确认 | 墙面可见不推断已知厚度；保留冲突值。 |
| `ModelRevision` | 输入版本、构件映射、修改操作、影响闭包、评测、不可变父版本 | 局部修改后重跑依赖检查、几何/拓扑与来源校验；回滚为新版本。 |
| Provider / Harness seam | typed input → candidates/errors；受控 `inspect`, `validate`, `compile`, `compare`, `revise` | 模型只建议结构化值；提供商或 Harness 替换不改变产品语义。 |

Core 现有 `StateAssertion | Unknown | Conflict` 与历史/变化接口可承载经过验证的状态投影，但产品需要先明确属性粒度、坐标和时效映射；这项集成尚未编写。当前 `proposal/0.1` anchor 只有声明，不能证明尺度已应用。

## 风险与验证

以带真实尺寸和授权的完整房间为 V0.2 目标；TUM 的 RGB-D 轨迹只用于前期几何实验，没有真实墙或 IFC 真值。必须增加独立尺度及留出照片核验、Bonsai/其他编辑器打开修改回读、GUID 保持与人工耗时对照，再评估 V0.2 发布。V0.3–V1.0 的具体门槛见 [路线图](../roadmap/worldstate-bim-product-reset.md)。
