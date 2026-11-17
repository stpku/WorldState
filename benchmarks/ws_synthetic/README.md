# WS-Synthetic — 合成真值和冻结评测

这套工具生成程序化房间并用 IFC 几何渲染，不含任何真实房间。公开开发演示在 [examples/bim_research_preview](../../examples/bim_research_preview/README.md)。合成结果只能称为**合成数据表现**。

## 数据与隔离

一次生成两个不同房间：矩形与 L 形，每个 6 视角；门窗开口来自参考 IFC，另含家具遮挡、不同光照和墙面纹理。一个场景向输入相机平移和旋转加入小扰动。输入目录只有渲染图与允许的相机清单；参考目录包含 Room IR、IFC、精确相机、每像素的深度/实例/语义以及特征的可见性。深度是相机 Z、单位米，未命中为 NaN；`visibility` 中接缝不确定的点保持 `occluded_or_edge_ambiguous`。

开发和测试必须使用不同输出路径和随机种子。测试生成后以 `manifest.json` 绑定逐文件 SHA-256；评测时验证它，不得用测试参考调参。[本轮冻结计划](FROZEN_RUN_PLAN.md)预先固定两图、模型、权重与阈值。目录隔离只能防止意外泄露；拥有本机完整文件权限的进程仍可访问参考，因此不是防恶意盲测。相同种子固定设计和相机，但 IFC 文件的时间戳/关系 GUID、不同 Blender 版本及渲染平台可能产生不同字节；应记录各自产物哈希。

## 生成及评测

安装产品依赖与 `pip install -r benchmarks/ws_synthetic/requirements.txt`，单独安装 Blender 5.2.x。渲染使用 CPU Cycles；无图形桌面的 Linux 通常需要 xvfb 和 EGL 软件渲染支持。以下命令需要根据实际系统安装调整 Blender 路径：

```bash
PYTHONPATH=. python benchmarks/ws_synthetic/generate.py \
  --output /path/to/new-dev --seed 717 --split dev --blender /path/to/blender --xvfb
PYTHONPATH=. python benchmarks/ws_synthetic/generate.py \
  --output /path/to/new-frozen-test --seed PRIVATE_RANDOM_INTEGER --split frozen-test \
  --blender /path/to/blender --xvfb
# 候选 IFC 对应的 Room IR、匹配 NPZ 均应由待测算法只读取 input/ 后生成，并保存在数据集外。
PYTHONPATH=. python benchmarks/ws_synthetic/evaluate.py --dataset /path/to/new-frozen-test \
  --scene SCENE_ID --model /path/to/candidate-model.json \
  --matches /path/to/candidate-matches.npz --images 1 2 --output /path/to/new-evaluation
```

`matches.npz` 包含相同长度的原图像素二维数组 `a`、`b`；未提交模型或匹配则明确显示 `NOT_SUBMITTED`。墙以中心距离 ≤0.15 m、方向差 ≤10° 作一对一匹配；开口参数门限为 0.1 m。IFC 表面误差由各 16,000 个墙体表面样本估算，含开口，但不是精确解析 Hausdorff 距离。对应评测使用参考深度与精确相机、3 px 阈值及 0.05 m 可见性容差，同时报告不可评数量和严格分母。未测精度不能由参考模型自比结果代替。

`run_matcher.py` 接受单个 `input/<scene>` 与外部已核验代码/权重目录，不读取参考；GlueStick 官方组合因 SuperPoint 受非商业限制，Tiny RoMa 和其他权重应分别核查许可。两者不随本仓库发行。
