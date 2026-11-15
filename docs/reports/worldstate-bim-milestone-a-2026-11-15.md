# WorldState BIM Milestone A：首次真人试用准备

**结果：可供授权人员试用的本地 Studio 已启动；新增真实墙体尚未确认，正式 V0.2 仍为 NOT RELEASE-READY。** ETH3D kicker 是开发场景，所有预载观察来自自动化，未进行真人试用或独立扫描审核。人工效率、独立墙实例精度和独立尺寸精度均为 `NOT_MEASURED`。未修改冻结的验收协议或 WorldState Core。

## 试用入口及实际验证

详细入口、SSH 转发与图形操作见 [真人试用说明](../../benchmarks/ws_realroom/MILESTONE_A_USER_TRIAL.md)。本机 Studio 只监听 `127.0.0.1:18790`，扫描审核只监听 `127.0.0.1:18791`；二者在独立 tmux 会话运行，没有开放公网。服务器侧 HTTP 已检查，试用者从其电脑登录 SSH/Tailscale 的实际权限尚未验证。服务和工作区不是托管产品，重启后须按说明手动恢复。

工作区 `/home/dev/.cache/worldstate-milestone-a/user-demo-v1` 有 29 张哈希校验的真实照片及 29 组已知相机、2,586 条跨图特征轨迹；42 条同一视图重复的轨迹被排除。视觉 ONNX 权重在启动时已加载到 CPU。第十轮墙片段及原始自动化观察、版本历史均保留；复制到本工作区时重新求解并保留为第 3 个版本。原有观察仍为 `automation_unverified`，新增真人操作才按 `user` 记录。已知相机依赖 ETH3D 官方扫描配准，尚未独立核验；已有 IFC 的尺度、朝上方向、墙厚和矩形近似是假设。

隔离的 `browser-workspace-v2` 使用真实照片和脚本点击进行浏览器验证：默认显示两张有既有观察的照片；使用局部放大修改旧墙观察、求解、生成并下载 IFC；新建另一个候选，并在多张照片标注、求解、查看投影、修改与重新求解。该新候选来自此前未经审核的语义特征凸包，可能包含家具，**不是已确认墙体**。系统按既有非矩形/非竖直检查拒绝其 IFC，不降低门槛。旧 IFC 修改前后通过 IfcOpenShell IFC4 独立读取，墙 GUID 均为 `15K4a41pXJxPHst4KdtLRH`。图形操作、像素与执行时间均为自动化，不是人工标注或人工成本。

真实试用阻断修复：已有边到线片段与新表面可以在同一相机坐标系分别求解，但没有自动创建连接，混合模式遇到跨对象约束仍明确拒绝。新对象创建后自动选中；未保存候选可明确放弃，原观察写入修订日志，已保存对象不能用此入口删除。浏览器实际验证放弃失败候选、重新求解余下模型后可恢复 IFC 导出。

可检查的实际记录：

- 浏览器记录及截图：`/home/dev/.cache/worldstate-milestone-a/browser-result-v2/`。
- 三张图的视觉候选、原图及模型哈希、自动轨迹建议、误差和遮挡限制：`/home/dev/.cache/worldstate-milestone-a/vision-probe-v1/`；3 张叠加图由试用说明中的本地链接提供。
- 扫描审核包：`/home/dev/.cache/worldstate-milestone-a/scan-review-v1/`；其页面只读来源扫描及全场平面提议，没有读取或展示 IFC 候选位置与尺寸。浏览器验证 9 个平面可显示，审核状态仍为空。对齐后全场每 100 个顶点采一个，共 512,373 点；背景显示再抽样，只供查看，不能当作测距真值。

## 实际视觉检查及三面墙的尝试

本运行环境可直接查看真实照片；本地 UPerNet/ConvNeXt ADE20K ONNX 模型实际在 CPU 上处理了三张 kicker 照片，三次约 6.8、7.3、6.3 秒。它是图像分割模型，不是已授权的 DSH 多模态调用；视觉区域只是一类像素，不等于墙实例。下列三处是待核验的物理墙假说，未由真人确认：

| 假说及图像 | 实际结果 | 失败或待确认原因 |
| --- | --- | --- |
| 沙发侧墙，`DSC_6500.JPG` | 发现一条墙顶语义线；线端点 `[4075,1325]` 的 25.96 原始像素内有 COLMAP 轨迹 146。该轨迹来自四张原图，最大重投影误差 2.695 px、最大视差 16.13°。 | 轨迹靠近黑色竖向物体与顶面，可能是柱、隔断或墙角；墙底受沙发等遮挡。几何一致并不能确认物理语义或墙面边界。 |
| 桌球桌侧墙，`DSC_6503.JPG` | 算法产生两条顶面附近的线及墙区域。 | 线段附近没有 30 px 内跨图轨迹；家具/白板被错误识别为窗。右侧大墙的可见边界与遮挡不能由输出可靠区分。 |
| 黄门所在墙，`DSC_6508.JPG` | 算法产生门区域 `[3494,1002,4173,2294]` 及 5 条顶面附近线段。 | 没有满足邻近条件的线端点轨迹；门扇与宿主墙共面尚未证实。这里也是既有局部片段来源，不是新增墙。 |

轨迹 146 是**确定性特征建议**，不是模型识别出的真实墙角，AI 的图像解释同样未确认。其原始像素和照片 SHA-256：

| 文件 | SHA-256 | 原始像素 `(x,y)` |
| --- | --- | --- |
| DSC_6500.JPG | `8b9ced11c2cd99f7948614cda4afa2c9021c927baddc820b3b5e02a48b7a5561` | `(4090.73, 1345.66)` |
| DSC_6502.JPG | `71c7b0f731de179038df5c7a573ffe1ab9cb7d2db9f96052b51086234c274979` | `(2016.42, 1403.20)` |
| DSC_6490.JPG | `6cdf845815af34a21aa79c7c78635a8cbf004023600723f76a06a86461bf12c0` | `(5231.26, 1334.17)` |
| DSC_6489.JPG | `8c187a607e2c374ce9181a8d6660c57355b84b28fbc57ac294c521c0d3a48c86` | `(3092.82, 1476.66)` |

由现有通用求解器计算的新四点候选含柜体及遮挡边界，未能通过 IFC 检查；没有将其计为三面墙或新 IFC。未提供独立物理尺度，也没有新增完整墙体或独立尺寸评测。

## 可复用产品路线判断

| 路线 | 已有实际运行和本次核查 | 当前判断 |
| --- | --- | --- |
| Photo-to-BIM | 已知位姿、假设尺度的 kicker 局部墙片段可修改并导出；新候选多视图求解后被 IFC 门槛拒绝。 | 证据选择、遮挡、语义实例和真实尺度仍是主要阻断；尚未证明完整房间或效率。 |
| Scan-to-BIM | 已有 CRASLAB Cloud2BIM → IR → IFC，8 面候选墙可生成几何；已有 Bonsai 编辑回写。开发样本点级表面 precision 0.5964、recall 0.1601，存在白板误分类。 | 输入扫描条件下有较多可编辑对象，但尚需对象语义、配准和独立尺寸审核；这些点级数值不是墙实例验收。 |
| Model-to-Reality | 已有 kicker 初始模型投影、依据同场照片修订后导出 IFC；本次浏览器再次完成局部模型投影/修订/导出。第九轮训练观察混合重投影 RMS 从 78.04 px 到 1.17 px，同场开发留出图从 113.14 px 到 2.28 px；两版 IFC 中同一 GUID 保持。 | 适合优先做现有局部模型的可视核对试用。留出图已在开发中查看、标注非真人且采用扫描配准位姿；数字不是独立几何精度或现场变化检出能力，也不能证明节省工时。 |

上述路线使用不同开发输入与证据，不构成同条件性能排名。现阶段只能提出优先试用 Model-to-Reality 的判断，不能声称质量、成本或商业效果已验证。

## 复现与测试

数据及衍生产物仍在仓库外；ETH3D 限 CC BY-NC-SA 4.0 非商业研究，不作为商业产品资产。已有扫描提议来自不以待测模型为输入的全场扫描分割，但尚无独立人员审核，不能称为参考墙或真值。用户可按试用说明完成审核；正式 Room-Test 和至少三组同质量真人配对仍缺失。DSH 的项目授权仍为外部阻断，本次未重复匿名检查。

```bash
export PYTHONPATH=. OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=4
WS_PY=/tmp/worldstate-bim-reset-venv/bin/python
WS_K="$HOME/.cache/worldstate-round8/eth3d/kicker"
WS_R10="$HOME/.cache/worldstate-round10/kicker"
WS_OUT="$HOME/.cache/worldstate-milestone-a/reproduction-NEW"

# 所有输出必须不存在；不会下载或覆盖现有数据、模型及试用记录。
$WS_PY benchmarks/ws_realroom/prepare_kicker_user_demo.py \
  --template "$WS_R10/studio-edge-v2" --manifest "$WS_R10/known-cameras-tracks.json" \
  --photos "$WS_K/isolated-dev/input/photos" --output "$WS_OUT/studio"
$WS_PY benchmarks/ws_realroom/prepare_scan_review.py \
  --proposals "$WS_R10/scan-global-proposals-v3.json" \
  --scan-dir "$WS_K/evaluation-private/kicker/scan_clean" --output "$WS_OUT/scan-review"
$WS_PY -m pytest tests products/worldstate_bim/tests -q
```

视觉探针 `benchmarks/ws_realroom/probe_kicker_vision.py` 会向指定本机 Studio 的项目添加真实视觉运行及叠加图；应在独立测试工作区运行。浏览器脚本 `benchmarks/ws_realroom/milestone_a_browser_check.cjs` 要求预载的隔离项目 `operator_kind=automation` 和未审核的第十轮候选输入，不得在真人项目中执行。全量 Core 与产品回归 **240 通过**，59 条 IfcOpenShell 弃用警告。

下一步应等待负责人实际试用，确认可见墙角和边界；同时由未接触模型的独立人员审核扫描。若证据无法识别边界，保留部分候选与失败，不再将家具或封闭先验当作墙。
