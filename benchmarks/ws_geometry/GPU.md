# VGGT-Omega GPU 实验包：NOT_TESTED

本机无 CUDA GPU，故未运行或验证此脚本，不报告模型质量。候选使用 [VGGT-Omega 上游](https://github.com/facebookresearch/vggt-omega) 修订 `48b23c8ce72c9a8fcf987f0d7f43d8e4870759f6`，许可证为[非商业研究许可](https://github.com/facebookresearch/vggt-omega/blob/main/LICENSE)，不得作为默认商业 provider。权重需按上游方式取得并记录完整 SHA-256。

供应商在 A100、模型 `VGGT-Omega-1B-512`、25 帧时报告 7.80 GB 峰值，包含模型加载；不同 GPU、分辨率、模型和图片数可能显著不同。建议从有余量的 16 GB CUDA GPU 开始，记录实际驱动、CUDA、显存、原始依赖锁定与错误；这不是本项目实测。准备过程可能涉及用户需同意的权重条款，不能将权重纳入公开仓库。

```bash
# 使用经核准的独立 GPU 机器和环境；请先阅读上游依赖及许可证。
git clone https://github.com/facebookresearch/vggt-omega.git /tmp/vggt-omega
cd /tmp/vggt-omega
git checkout 48b23c8ce72c9a8fcf987f0d7f43d8e4870759f6
python -m pip install -r requirements.txt
# 在上游指导下下载 checkpoint，计算其 SHA-256，准备固定 TUM 32 帧。
# 在 WorldState 根目录运行（将变量替换为实际路径和哈希）：
PYTHONPATH=/tmp/vggt-omega:. python benchmarks/ws_geometry/vggt_omega_infer.py \
  --images /tmp/ws-tum-32 --manifest benchmarks/ws_geometry/tum-32-manifest.json \
  --checkpoint /path/to/authorized/model.pt --checkpoint-sha256 CHECKPOINT_SHA256 \
  --output-dir /tmp/ws-vggt-omega --count 16 --resolution 416
```

本接口及依赖组合尚未经 GPU 运行验证。`416` 是复现实验入口参数，不是引用上游 `512` 指标；必须在同一输入、预先确定的尺度锚与留出轨迹上评测，并先验证相机坐标约定。输出尺度默认 unknown，不能直接冒充公制 BIM。完成前结果和性能均为 NOT_TESTED。
