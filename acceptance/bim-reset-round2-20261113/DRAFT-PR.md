# WorldState BIM: assisted evidence-to-wall IFC and real scan baseline

真实照片/深度辅助工作流以前不能生成可检查的 BIM 构件，也不能从独立建模应用回读修改。本变更增加可追溯的单墙参数化 IR、实际尺度约束、IFC4 轴线/材料层、受控墙长修订与 Bonsai 修改回读；加入来自 CRASLAB 真实点云的局部语义 IFC、Cloud2BIM 同输入对照和 TUM CPU COLMAP 实测。

结果仅为实验性建模：照片尺度来自同一深度传感器，扫描基线误将白板识别为墙，Cloud2BIM 多构件 IFC 有 6 处 schema 缺陷，均未完成独立房间几何验收或人力成本比较。DSH 最小请求缺少凭据；GPU 模型和混元未运行。V0.2 未达到发布条件。

验证：`OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m pytest tests products/worldstate_bim/tests -q`，156 项通过；Bonsai 保存真实照片墙的参数修改后由 web-ifc 和 IfcOpenShell 回读、GUID 保持；[完整运行与失败记录](STATUS.md)，[Benchmark 和复现](../../benchmarks/README.md)。

保留 Core 契约与既有 5 处用户未提交文档变更。本说明供审阅；上轮 PR 创建返回 403，未重复尝试。
