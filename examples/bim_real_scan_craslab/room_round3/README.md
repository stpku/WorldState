# CRASLAB 多构件：Cloud2BIM → IR → IFC → Bonsai → IR

这是公开 CC BY 4.0 的 [CRASLAB](https://doi.org/10.5281/zenodo.7948116) 真实扫描生成的**未验证开发场景**，不是完整房间验收，也不是工程交付。源候选来自本仓库[第二轮 Cloud2BIM 原始 IFC](../cloud2bim-unverified.ifc)，该输入有 6 处 `IfcWindowType.PartitioningType` 缺失、占位经纬度和无依据的材料名称。

| 文件 | 内容 |
| --- | --- |
| [model.json](model.json)、[identities.json](identities.json)、[import-report.json](import-report.json) | 版本化多构件 IR、外部 GUID/几何指纹映射及隔离原因。墙窗分类和尺寸为推断，板厚/窗板厚为假设，材料与地点未知。 |
| [model.ifc](model.ifc) | 重编译 IFC4：8 墙、1 楼板、5 窗、5 个 IfcOpeningElement、5 对 void/fill 关系；未生成未观察的房间边界。 |
| [bonsai-edited.ifc](bonsai-edited.ifc)、[报告](bonsai-report.json) | Blender 5.2.2 / Bonsai 0.9.0.post1 将 `wall-cf1d15bbd93c2d52` 从约 5.10 改为 5.30 m；这是操作演示，不是新实测。 |
| [synced.json](synced.json)、[synced.ifc](synced.ifc)、[diff](diff.json) | 限定单个属性的外部编辑读回；保留源 IFC SHA-256 和原 GUID。重新验证必需。 |
| [height-edit.json](height-edit.json)、[window-edit.json](window-edit.json)、[window-edit.ifc](window-edit.ifc)、[修改差异](window-diff.json) | 另一条演示分支：先修改墙高，再移动窗洞；数值仅供展示，不是现场测量。 |

来源中的一块自交楼板、0.006 m 异常薄墙、一个越过宿主墙的开口及对应窗被隔离；没有自动修补或伪装成已确认。源墙体中心线与墙面有半墙厚偏移，适配器显式保留中心线语义；重新导出墙体包围盒与源候选最大差距小于 0.001 mm，这只衡量转换保真，不表示相对于实物的精度。

IfcOpenShell 0.8.4 对原始、Bonsai 修改和同步版本进行 IFC schema 检查，各 0 条；web-ifc 0.0.77 独立读取到 8 面墙，修改目标 GUID 保持 `270zBQX71J0wAulN$ejl1L`。没有引入源 IFC 的无效窗类型；这并不能证明构件识别正确或门窗位置准确。

```bash
# 从仓库根目录，Python 3.12 环境按 benchmarks/README.md 安装
PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.room_cli import-cloud2bim \
  --ifc examples/bim_real_scan_craslab/cloud2bim-unverified.ifc \
  --project-id craslab-room-development --output-dir /tmp/ws-room-v1

PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.room_cli revise \
  --model /tmp/ws-room-v1/model.json --element-id opening-34fcb929a4856871 \
  --attribute offset --value 1.25 --reason 'Demo edit, not measured' --operator analyst \
  --output-dir /tmp/ws-room-v2

PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.room_cli sync-ifc \
  --model examples/bim_real_scan_craslab/room_round3/model.json \
  --baseline-ifc examples/bim_real_scan_craslab/room_round3/model.ifc \
  --edited-ifc examples/bim_real_scan_craslab/room_round3/bonsai-edited.ifc \
  --element-id wall-cf1d15bbd93c2d52 --attribute length \
  --reason 'Bonsai edit, not measured' --operator analyst --output-dir /tmp/ws-room-synced
```

同步会对全模型对象身份、拓扑、材料、属性集及网格作受限核查，并校验请求属性对应的预期模型；不在已检查范围内的其他 IFC 元数据不会导入，操作会明确提示需人工核对。当前只支持单次墙长/墙高及开口 offset/width/height/sill 回写；不支持的几何和拓扑变更拒绝同步。
