# WorldState BIM 第三轮研发状态

日期：2026-11-13。开发分支 `feat/worldstate-bim-room-studio-20261113`，基于 `becc0df`；最近一次获取的远端 `main` 为 `91351fe`。本轮未修改 Core，原有 5 处用户未提交修改保持在工作区。功能分支的提交和远端状态以 `git log` / `git status -sb` 为准。**V0.2：NOT RELEASE-READY。**

## 实际结果

1. [房间 IR 和 IFC 编译](../../products/worldstate_bim/room_ir.py)：墙共享角点，楼板、门、窗、开口、空间和楼层可表达；导出 IFC4 void/fill 关系。墙长、墙高、窗洞位置等可版本化修改，平行、垂直和重合约束参与求解，相交仅检查。人工输入、推断和假设保留来源。测试覆盖相邻墙角传播、越界开口、冲突、GUID 和版本差异。空间 IFC 尚无实体几何；并非完整通用 BIM 系统。
2. [真实扫描集成](../../examples/bim_real_scan_craslab/room_round3/README.md)：公开 CRASLAB 点云经 Cloud2BIM 的已有真实输出 → 产品 IR → IFC。源 9 墙、2 板、6 窗/开口中，导入 8 墙、1 板、5 窗/开口，隔离 4 个冲突实体。适配器不采用源 0°/0° 地点和材料默认值，源 6 处窗类型 schema 缺项没有进入重编译模型；这不是语义正确性证明。已识别点云白板等可能误分类，材料、墙厚和遮挡仍未核实。
3. 同一开发场景的墙面点级邻近评价，4 cm 阈值下 precision **0.5964**、recall **0.1601**；[原始记录](../../examples/bim_real_scan_craslab/room_round3/surface-evaluation.json)包含输入哈希。这是点对表面指标，不是实例识别、独立房间精度或尺寸误差，不能与验收墙实例 precision/recall 直接比较。墙几何转换包围盒差异小于 0.001 mm 只证明转换一致性，不是实测精度。
4. Blender 5.2.2 / Bonsai 0.9.0.post1 实际将一面真实扫描候选墙由约 5.10 m 改为 5.30 m，GUID 保持并保存；产品受限同步至 IR。原始、Bonsai 修改、同步后的 IFC 均由 web-ifc 独立读取 8 墙、5 窗，IfcOpenShell schema 问题为 0 且 8/8 墙生成几何。该修改是交互演示，不是实测。墙高和开口位置回读有 IfcOpenShell 程序化测试，尚未在独立 BIM 图形应用逐项实测。回写不导入未检查的 IFC 元数据并给出警告，不支持的几何/拓扑修改拒绝。
5. [本地 Studio](../../products/worldstate_bim/README.md#run-worldstate-studio-locally) 使用真实 IFC 三角面，支持旋转、选择、显示证据与未知、修改参数、导出 IFC/IR/报告、展示隔离对象；可选点云显示最多 8,000 个抽样点，坐标对齐未自动确认。Chromium 实际测试了 19 个构件加载、墙高修改、新版本、图片上传及 IFC/报告下载，浏览器无脚本错误。上传照片暂不参与模型生成；底部中文命令是本地规则，**不是 DSH**。
6. [DSH 检查](../../products/worldstate_bim/DSH_INTERFACE.md)：部署的 Web、gateway、auth 服务运行，本地 Web 和网关返回 HTTP 401；当前会话没有可用授权连接。历史 headless `MISSING_CREDENTIAL` 与受保护服务的 401 是两个不同结果，不能推断服务侧缺失凭据。产品工具已实现，但真实 DSH 的视觉输入、工具注册、结构化输出及反馈修正为 **NOT_TESTED**。配置中出现模型名称不证明模型可用，未读取或输出密钥。
7. [混元/FreeCAD 离线实验包](../../benchmarks/ws_mesh/hunyuan_freecad/README.md) 已准备，含输入与权重哈希、许可记录、留出尺寸检查和人工耗时要求。当前没有 CUDA GPU、FreeCAD 或满足许可和尺寸要求的实物数据，模型生成、FreeCAD 宏、网格质量和成本均为 **NOT_TESTED**；没有租用 GPU 或上传私人资料。
8. 单独准备了[明确模拟的完整房间示例](../../examples/bim_synthetic_room_round3/README.md)：四墙、板、门、窗、两个开口和空间边界；从 4 m 到 5 m 的墙长修改使相关角点联动。原始和修改版均无 IFC schema 问题，墙几何可生成且 GUID 保持。该样例不代表真实房间质量。

## 验证和复现

```bash
# 独立 Python 环境依 benchmarks/README.md 安装产品依赖；以下是本机实际路径
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m pytest tests products/worldstate_bim/tests -q

# 只创建隔离采集目录，不生成假数据；目标目录不能预先存在
python3 benchmarks/ws_realroom/init_room.py /tmp/room-capture-NEW --room-id room-001

# 从已固定哈希的公开源再生成模型；目标目录请使用新的路径
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m products.worldstate_bim.room_cli import-cloud2bim \
  --ifc examples/bim_real_scan_craslab/cloud2bim-unverified.ifc \
  --project-id craslab-room-development --output-dir /tmp/ws-room-NEW

# 本地工作区必须位于仓库外
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/worldstate-bim-reset-venv/bin/python -m products.worldstate_bim.studio_server \
  --model-dir examples/bim_real_scan_craslab/room_round3 --workspace /tmp/ws-studio-NEW --port 8766
```

`pytest`：**179 项通过**；25 项来自 IfcOpenShell 的 `datetime.utcnow` 弃用告警。详细的 Bonsai、单项回读和真实数据复现命令见[样例说明](../../examples/bim_real_scan_craslab/room_round3/README.md)。照片路线仍是第二轮 [TUM RGB-D 局部墙](../../examples/bim_real_photo_tum/README.md)：使用同传感器参照，不是完整房间或独立公制精度结论。

## 数据采集和未满足门槛

项目负责人需选择有授权的真实房间；按[冻结协议](../../benchmarks/ws_realroom/PROTOCOL.md)收集至少 3 张建模照片、1 项独立尺度参照、至少 3 项不可用于建模的独立实测、2 张留出照片，并由独立人员建立参考 IFC。分别留存人工标注、Assisted/手工各至少 3 组运行与失败/复核耗时。`init_room.py` 在仓库外生成隔离目录、清单及私有真值模板；不得提交私有资料或将真值给待测算法。

当前没有通过冻结协议的验收房间、独立墙尺寸误差、留出视角审查或三组配对人工成本。完整照片到多墙自动候选及图片关联仍缺失；真实扫描案例无 `IfcSpace`，也没有可确认的完整房间拓扑。实例 precision ≥ 0.90、recall ≥ 0.80，尺寸容差、GUID、独立工具回读及人工时间中位数减少 ≥ 20% 等门槛必须在新验收场景全部达标后才能发布；当前费用和效率为 NOT_MEASURED。

下一轮应使用新授权房间打通照片标点/视觉候选 → 多墙 IR → 用户确认 → IFC；完成独立尺寸和人时对照。并在批准的会话中接通 DSH 真实工具反馈，验证扫描构件的配准和语义；空间实体、真实开口和外部多构件编辑需要独立验收。
