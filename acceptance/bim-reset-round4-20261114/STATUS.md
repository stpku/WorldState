# WorldState BIM 第四轮状态

日期：2026-11-14（Asia/Shanghai）。基于 `4cf40ad`，开发分支 `feat/worldstate-bim-photo-studio-20261113`；远端 `main` 最近核对为 `91351fe`。**V0.2：NOT RELEASE-READY。** Core 与 [WS-RealRoom 冻结协议](../../benchmarks/ws_realroom/PROTOCOL.md)未修改；原有五处用户未提交修改未纳入本轮提交。

## 用户可运行的结果

本地 Studio 可在仓库外创建／恢复项目，上传照片并记录墙边界、角点、地面／天花板交线、门窗矩形与尺度标注；相同墙或门窗编号可关联不同照片。用户可选择：

1. **人工俯视草图**：以用户标尺缩放草图。除标尺外，长度和角度来自草图比例，标为待核验推断。
2. **单张照片地面反投影**：手动标注同一张照片的地面角点，提供针孔内参、俯角和标尺，计算光线与假定水平地面的交点，再实际应用尺度。相机横滚为零、地面水平、镜头畸变未补偿；相机参数错误会改变几何。未观测区域不自动闭合。

两条路径均需要明确墙高和厚度来源。门窗矩形不会自动变为公制尺寸：用户需提供或假设 offset、宽高和底高，冲突时拒绝生成。输出采用已有 Room IR 和 IFC 编译器；用户可在 Studio 中选构件、修改尺寸、查看影响、恢复历史为新版本、导出，或上传外部 IFC 进行受限同步。照片质量提示只是亮度、分辨率和清晰度启发式，不验证覆盖或配准。多图可共享标注对象，但**没有**实现多视图相机求解、自动视觉识别或照片到完整房间的自动建模。

启动方式见[产品说明](../../products/worldstate_bim/README.md)。照片和工作区保持本地，未上传至外部服务。

## 本轮实际操作与局限

- [TUM 真照片局部墙](../../examples/bim_real_photo_tum/round4/README.md)：Playwright 自动创建项目、上传两张真实照片、标注一段墙面和地面端点、以近似相机参数和标尺生成一个墙段；修改图像点后模型方向改变。标尺由同场景深度帧计算，**不是独立参照**；俯角、水平地面、墙高和厚度未独立核实。项目将自动化标注明确标为 `simulated`。它只能作为局部、未验证开发样例。
- 同一案例在 Studio 中通过本地规则将墙长增加 0.2 m；Blender/Bonsai 后台原生操作器将墙长再改至 0.9 m，浏览器上传 IFC 并同步 IR。后续另以 Bonsai 修改墙高并浏览器回写。五个产品版本的墙 GUID 保持，web-ifc 独立读回，IfcOpenShell schema 检查及墙几何生成通过。自动点击和修改数值均非人工成本测量或现场测量。
- 增加生成前的标注、标尺及假设确认后，另在新工作区重跑[真实照片浏览器操作](photo-confirmed-browser.json)、[Bonsai 编辑](photo-confirmed-bonsai.json)和[浏览器回写](photo-confirmed-sync.json)。这与上一个持久样例是两次独立的自动化开发运行，均不是人工验收。
- [多墙浏览器记录](multiwall-browser.json)使用真实照片，但墙体关联、四点草图、尺度、门窗参数均为**脚本构造的模拟输入**：生成 3 墙、1 窗和 1 开口；规则修改后影响相邻墙及开口；[Bonsai 墙高编辑](multiwall-bonsai.json)和[浏览器同步](multiwall-sync.json)成功。该测试不代表三面真实墙的识别或尺寸精度。脚本见 [studio_multiwall_browser.cjs](../../benchmarks/ws_realroom/studio_multiwall_browser.cjs) 与 [studio_sync_browser.cjs](../../benchmarks/ws_realroom/studio_sync_browser.cjs)。
- [CRASLAB 独立应用编辑](../../examples/bim_real_scan_craslab/room_round4/README.md)：Bonsai 墙高 3.396→3.5 m、窗洞 offset 1.150116→1.250001 m 分别保存并同步。直接 `recalculate_fill` 曾丢失开口几何，失败文件和拒绝结果保留；另一种原生操作产生不同的墙面三角剖分，经顶点、平面、表面边界和孔洞拓扑检查后回写。8/8 墙几何生成成功，23 个产品 GUID 保持。这不证明扫描语义和尺度真实；白板误识别、漏检、空间边界和配准仍未解决。
- [DSH 授权检查](../../products/worldstate_bim/DSH_INTERFACE.md)：匿名 `/login` 返回 200，受保护根路径返回 401。已找到 Tailscale 浏览器登录入口及最小权限说明，没有读取或传递密码。尚无授权会话接入 Studio，也未在实际 DSH 注册和调用建模工具；真实 DSH 修改和反馈为 **NOT_TESTED**。界面文字命令明确为 Rule-based Mode。
- [验收工具](../../benchmarks/ws_realroom/README.md)：可初始化私有目录、冻结模型和全部 Studio 上传照片哈希，之后在隔离的参考目录计算墙实例匹配、尺寸和配对人工成本；测试验证了候选变动、相同参考 IFC、留出照片泄漏和冻结后输入清单变化会被拒绝。人工匹配、真实独立性和留出视角仍需独立人员审核。工具本身始终把独立 IFC 引擎、独立应用编辑、GUID 与外部回写标为 `NOT_EVALUATED`，不能单凭其报告发布。

## 验证和复现

```bash
# 产品与 Core：本机 Python 3.12 环境，192 项通过
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m pytest tests products/worldstate_bim/tests -q

# 新建本地照片工作区；不要使用仓库内目录
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m products.worldstate_bim.studio_server \
  --workspace /tmp/ws-photo-NEW --port 8766

# 独立房间采集目录；不会产生虚构的测量值
python3 benchmarks/ws_realroom/init_room.py /tmp/ws-realroom-NEW --room-id room-001
```

真实照片及 Bonsai 操作的更多命令、输入哈希和许可证见各样例；照片和深度原始数据未入库。桌面与 390 px 浏览器宽度下均完成加载检查，未发现脚本错误。当前变更的具体提交以 `git log` 为准。

## 未满足的强制门槛与下一步

没有获得新的授权独立真实房间、三面可见墙的参考实例及至少三项留出实测，无法报告实例 precision／recall、独立尺寸误差或留出照片核验。没有至少三组经同质量审核的人工／辅助配对运行，人工成本及 ≥20% 节省为 **NOT_MEASURED**。用户需按[采集清单](../../benchmarks/ws_realroom/README.md)准备输入和由独立人员保管的参考，再冻结并评测；不得将本轮开发场景当作正式验收。

DSH 需要用户通过已有网关授权登录，并由授权管理员为本项目注册受控工具、验证调用与反馈；不得提交凭据或将规则模式冒充 Agent。后续仍需自动视觉候选、多视图配准、扫描语义纠错及真实用户测试。混元／FreeCAD 没有新 GPU 或授权物体，仍为 **NOT_TESTED**。
