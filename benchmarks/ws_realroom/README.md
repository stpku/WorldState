# WS-RealRoom 采集与独立评测工具

完整要求和阈值以未改动的 [PROTOCOL.md](PROTOCOL.md) 为准。这里的脚本只实现部分自动核查；不能自动证明参考资料的独立性、留出视角的人工作业、独立 BIM 软件编辑或完整发布门槛。

## 采集与隔离

负责人应先取得场地、照片、图纸和模型的处理／公开授权，再收集至少三张可见墙角的不同视角照片；另外保留两张不能用于建模或调参的视角。一项建模标尺需要记录对应端点、测量工具和不确定度；房高、相机参数、门窗尺寸和墙厚按实测或假设分别标记。独立评测人员另外测量至少三面不同墙的尺寸，制作参考 IFC；这些数据不得进入建模输入。分别保存人工及辅助建模至少三组配对的素材整理、标注、修订、审核、自动运行、GPU、费用及失败记录。

在仓库外创建新目录，目录默认被 Git 忽略：

```bash
python3 benchmarks/ws_realroom/init_room.py /path/outside/repo/room-NEW --room-id room-001
```

填写 `capture-manifest.json`、授权记录及 `input/`；评测人另行保管 `private-reference/` 中的参考 IFC、独立尺寸和留出照片。模板中的空数组和 `NOT_COLLECTED` 均不是测量数据。文件和测量必须有来源、时间、操作者及 SHA-256；不要把私有资料提交到公开仓库。

## 先冻结候选，再由独立评测人解封参考

以下命令采用产品虚拟环境和仓库根目录。第一次运行必须选择尚不存在的输出路径，避免覆盖已冻结结果。

```bash
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_realroom/evaluate.py freeze \
  --candidate-dir /path/to/studio/revision-001 --output /path/to/runs/frozen-candidate.json

# 只有候选冻结后，独立评测人才能读取 private-reference 并运行：
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_realroom/evaluate.py evaluate \
  --candidate-dir /path/to/studio/revision-001 --frozen /path/to/runs/frozen-candidate.json \
  --reference-dir /path/to/room-NEW/private-reference \
  --reference /path/to/room-NEW/private-reference/reference.json \
  --labor /path/to/room-NEW/runs/labor.json --output /path/to/room-NEW/reports/evaluation.json
```

根据 `reference.template.json` 建立 `reference.json`：

- `reference_ifc` 和 `holdout_photos` 每项提供相对于私有参考目录的 `path` 与实际 `sha256`；参考 IFC 的可见墙 GUID 列入 `visible_wall_guids`。
- `matches` 每项包含 `reference_guid`、候选 `candidate_id` 和 `reviewer`。这些是一对一的独立人工对应，不是算法自动实例匹配。
- `measurements` 每项包含唯一 `id`、`reference_guid`、`attribute`（`length` 或 `height`）、`value_m`、`uncertainty_m`、`method` 和 `operator`。至少涉及三面不同墙，建模标尺不可重复作为真值。
- `runs/labor.json` 的 `pairs` 每项有唯一 `pair_id` 及 `manual`、`assisted`。每个运行记录 `quality_passed`、`reviewer`、`human_seconds`（`prepare`、`annotate`、`correct`、`review`）、`automatic_seconds`、`gpu_seconds`、`cost`、`failures`。失败运行也要保留，质量结论是审核人声明而不是脚本证明。

脚本核对候选冻结哈希、参考文件哈希、留出照片是否出现在候选证据、一对一匹配、冻结的实例／尺寸门槛及人工成本中位数，并以 IfcOpenShell 做 schema 和墙几何诊断。它无法仅凭哈希证明建模者没有看到参考资料，也不自动检查留出照片内容；照片与标尺是否真正独立仍需访问控制和人工审核。IfcOpenShell 同时用于产品导出，不代替独立 IFC 引擎。独立 BIM 软件编辑、GUID 保持和 IR 回写在本工具中一律标为 `NOT_EVALUATED`；本报告单独不能将版本标为 release-ready。
