# CRASLAB：Bonsai 墙高与窗位置回写

输入是第三轮[真实扫描开发候选](../room_round3/README.md)，不是经过验收的房间。以下数值是人为指定的编辑演示，不是现场实测。Blender 5.2.2 / Bonsai 0.9.0.post1 在后台启动图形应用并通过其原生操作器执行，不是人工鼠标操作。

- 墙 `wall-cf1d15bbd93c2d52`：Bonsai `change_extrusion_depth` 将高度从 3.396 改为 3.5 m。[外部 IFC](height-bonsai.ifc)、[回写 IR](height-synced.json)、[差异](height-diff.json)。
- 开口 `opening-34fcb929a4856871`：在 Bonsai 中同时移动窗和开口，并使用 placement / edit-openings 操作器，将沿墙 offset 从约 1.150116 改为 1.250001 m。[外部 IFC](window-bonsai.ifc)、[回写 IR](window-synced.json)、[差异](window-diff.json)。墙、窗和开口身份保持；原始、编辑和同步版均有 23 个相同的 IFC 产品 GUID。
- **失败案例保留**：直接移动窗后调用 `recalculate_fill` 得到的[文件](window-recalculate-failed.ifc)丢失了开口的几何表示，虽然 schema 检查没有报错，WorldState 拒绝同步。不能把 schema 通过当作开口几何正确。

窗位置的正确文件使用了不同的墙面三角剖分。首次回写因逐三角形比较而拒绝；检查发现对应墙的 32 个顶点最大偏差约 0.000625 mm，但有 6 对不同的三角形。当前回写首先要求顶点一对一匹配（0.01 mm）、平面匹配、投影表面边界及孔洞拓扑一致，才允许等价的重新剖分；额外几何、关系和被检查属性变化仍拒绝。未检查的其他 IFC 元数据不导入并明确告警。

IfcOpenShell 0.8.4 对两个成功的外部 IFC 和同步 IFC 均报告 schema 问题 0，且 8/8 墙生成几何；web-ifc 0.0.77 独立读取到 8 墙、5 窗、5 个开口。这些检查不验证构件识别、真实尺寸或材料。

复现时指定本机 Blender、Bonsai 扩展配置，以及新的输出路径：

```bash
BLENDER_USER_CONFIG=/path/to/blender-config BLENDER_USER_EXTENSIONS=/path/to/blender-extensions \
  /path/to/blender -b --python-exit-code 1 --python benchmarks/ws_bim/bonsai_parameter_edit.py -- \
  examples/bim_real_scan_craslab/room_round3/model.ifc height '270zBQX71J0wAulN$ejl1L' 3.5 \
  /tmp/ws-height-NEW.ifc /tmp/ws-height-NEW.json

BLENDER_USER_CONFIG=/path/to/blender-config BLENDER_USER_EXTENSIONS=/path/to/blender-extensions \
  /path/to/blender -b --python-exit-code 1 --python benchmarks/ws_bim/bonsai_parameter_edit.py -- \
  examples/bim_real_scan_craslab/room_round3/model.ifc window_offset '0qj_0dhFbNhfKaJWeRiKN4' 1.25 \
  /tmp/ws-window-NEW.ifc /tmp/ws-window-NEW.json

PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.room_cli sync-ifc \
  --model examples/bim_real_scan_craslab/room_round3/model.json \
  --baseline-ifc examples/bim_real_scan_craslab/room_round3/model.ifc --edited-ifc /tmp/ws-window-NEW.ifc \
  --element-id opening-34fcb929a4856871 --attribute offset --operator analyst \
  --reason 'Bonsai edit; not a field measurement' --output-dir /tmp/ws-window-sync-NEW
```

将脚本的模式改为 `window_recalculate_fill` 可复现失败分支；该文件不得用作交付模型。
