# 多构件 Scan-to-BIM 与本地 Studio（草稿）

实现房间级参数化 IR、受控墙体/开口修改、IFC4 导出和局部外部编辑回读，接入 Cloud2BIM 的真实公开点云结果，并提供可交互本地 Studio。原有 Core 和单墙接口保留；冲突构件隔离、未知和推断来源可见。

验证：Core 与产品共 179 项测试通过；CRASLAB 开发样例导出 8 墙、1 板、5 窗及对应开口，Bonsai 修改墙长后保持 GUID 并同步回 IR；web-ifc 独立读取，IfcOpenShell 对原始、修改和同步版本通过 schema 和墙几何检查。Chromium 测试了实际模型加载、编辑、上传和导出。详细操作、评价数字和局限见 [STATUS.md](STATUS.md)。

V0.2 仍 **NOT RELEASE-READY**：缺少授权的新验收房间、独立尺寸和人工成本对照；真实 DSH 调用和混元 GPU/FreeCAD 实验尚未验证。未发起 PR 或合并 main。
