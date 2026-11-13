# 模拟房间：墙、门、窗和约束修订

这是**虚构的模拟输入**，不是照片或点云重建结果。它用于体验房间 IR 的四墙、楼板、门窗、开口关系、空间边界和共享角点：[original](original/model.ifc) 是 4 m × 3 m 房间；[revised](revised/model.ifc) 将墙 1 延长到 5 m，求解相邻角点和关联构件，产生[版本差异](revised/diff.json)并保留 GUID。`IfcSpace` 当前只有边界关系，没有空间实体几何。

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python \
  examples/bim_synthetic_room_round3/generate.py /tmp/ws-synthetic-room-NEW

# 通过 Studio 打开仓库中的模拟原始模型，输出目录请放在仓库外
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python -m products.worldstate_bim.studio_server \
  --model-dir examples/bim_synthetic_room_round3/original --workspace /tmp/ws-studio-synthetic-NEW --port 8766
```

实际扫描生成的未验证多构件示例及独立应用回读结果见 [CRASLAB 样例](../bim_real_scan_craslab/room_round3/README.md)。不能把本模拟例作为真实房间验收。
