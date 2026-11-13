# TUM 真实办公室：照片、相对深度与可见墙面片段

**研究开发集，非 V0.2 验收。** 本实验使用 TUM fr1/room 真实彩色图、运动捕捉轨迹与 Kinect 深度；没有墙体尺寸、语义或 IFC 真值。原始输入与模型不进仓库；固定源、SHA-256、许可证及镜像版本见 [manifest](manifest.json)。三个彩色帧与官方压缩包部分解压内容的哈希一致，轨迹与官方单独下载的轨迹一致；两张深度图来自固定版本镜像，尚未与完整官方归档逐字节对照。完整归档首次下载中断，不把部分文件哈希冒充全归档哈希。

TUM 数据作者为 J. Sturm、N. Engelhard、F. Endres、W. Burgard、D. Cremers；数据 [获取页](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/download)、[格式和标定](https://cvg.cit.tum.de/data/datasets/rgbd-dataset/file_formats)、[CC BY 3.0 许可声明的原作者论文](https://cvg.cit.tum.de/_media/spezial/bib/sturm12iros_ws.pdf)。研究数据许可与模型权重分开核对。相对深度模型是 [Depth Anything V2 Small](https://github.com/DepthAnything/Depth-Anything-V2) 的 [固定社区 ONNX 导出](https://huggingface.co/onnx-community/depth-anything-v2-small)，模型卡为 Apache-2.0。

## 本机实测，2026-11-13

Linux x86_64、4 vCPU AMD EPYC、15 GiB RAM、无可见 NVIDIA GPU；Python 3.12.3，版本见 [requirements](requirements-cpu-py312.txt)。完整机器可读记录见 [双视角](../../acceptance/bim-reset-20261113/two-view.json)、[单目深度](../../acceptance/bim-reset-20261113/relative-depth.json) 和 [可见表面](../../acceptance/bim-reset-20261113/visible-surface.json)。

| 路线 | 输入和实际输出 | 定量结果及限制 |
| --- | --- | --- |
| SIFT + 两视角 | 2 张 RGB + ROS 默认内参 → 第一相机坐标系下任意尺度稀疏点、相对旋转和平移方向 | 129 匹配，66 正深度点；中位重投影 0.299 px、视差 1.934°；与动作捕捉比较旋转 0.567°、平移方向 6.606°。用动作捕捉的 0.0891 m 基线作 **oracle 尺度**后，在 52 个有深度采样点上中位绝对深度误差 0.338 m，均值 0.439 m。没有恢复真实墙边界。 |
| Depth Anything V2 Small | 同一对中的首张 RGB → 相对逆深度；CPU ONNX | 一次推理约 1.4 s。用**同帧** 110,213 个像素深度拟合逆深度 scale/shift，在交错留出的 110,333 个有效深度像素上中位绝对误差 0.0178 m、均值 0.0511 m；同帧像素相关，且用了大量传感器真值标定，不是照片独立公制重建。 |
| 人工 ROI + RGB-D 平面 | 另一张 RGB 和其对应深度，人工标选可能是墙面的可见区域 → 相机坐标中的局部平面候选 | 1224 个有效采样中 1140 个 RANSAC 内点，中位拟合残差 0.00824 m。深度既用于拟合又用于算残差；它不是独立面精度。标签来自人工，完整墙高、边界、厚度未知。 |
| 视觉模型 + 参数 BIM/Harness | 目标同上并生成可编辑 IFC | **NOT_TESTED**：DSH headless 最小调用缺少凭据；图片到构件尚未打通。现有合成 IFC 的成功不可代替本项。 |

模型与双视角在同一张图片的 27 个共有留出像素上，中位误差分别约 0.0206 m 和 0.307 m；前者使用同帧大面积深度标定，后者使用轨迹基线标定，输入信息不等价，**不能做独立算法胜负结论**。模型预训练是否见过该场景未知。面片拟合用另一时刻、额外深度和人工 ROI，也不可并入照片自动建模对比。

三条实验都不产生可信的完整语义 IFC；尺度误差、墙尺寸、Chamfer、F-score、语义 F1、独立 authoring、留出视角、人工成本与产品成功率目前均 **NOT_MEASURED**。

## 从头复现

下面将公开源与模型下载到仓库外；数据约数 MB，模型约 100 MB。下载器检查文件 SHA-256、不覆盖不同的已有文件，并对暂时性的网络错误重试。网络或上游镜像不可用时请保留失败记录。使用其他系统时需要重新验证依赖及数值。

```bash
python3.12 -m venv /tmp/worldstate-bim-venv
/tmp/worldstate-bim-venv/bin/python -m pip install -r benchmarks/bim_real_room/requirements-cpu-py312.txt
python3 benchmarks/bim_real_room/fetch.py --data-dir /tmp/worldstate-bim-data --with-model

PYTHONPATH=. /tmp/worldstate-bim-venv/bin/python benchmarks/bim_real_room/run_two_view.py \
  --image1 /tmp/worldstate-bim-data/1305031910.765238.png \
  --image2 /tmp/worldstate-bim-data/1305031911.097196.png \
  --groundtruth /tmp/worldstate-bim-data/groundtruth.txt \
  --depth1 /tmp/worldstate-bim-data/1305031910.771502.png \
  --output /tmp/worldstate-bim-data/two-view.json \
  --tracks /tmp/worldstate-bim-data/tracks.json --cloud /tmp/worldstate-bim-data/cloud.ply

/tmp/worldstate-bim-venv/bin/python benchmarks/bim_real_room/run_depth_anything.py \
  --image /tmp/worldstate-bim-data/1305031910.765238.png \
  --depth /tmp/worldstate-bim-data/1305031910.771502.png \
  --model /tmp/worldstate-bim-data/depth-anything-v2-small.onnx \
  --tracks /tmp/worldstate-bim-data/tracks.json --two-view-report /tmp/worldstate-bim-data/two-view.json \
  --output /tmp/worldstate-bim-data/relative-depth.json

PYTHONPATH=. /tmp/worldstate-bim-venv/bin/python benchmarks/bim_real_room/run_visible_surface.py \
  --image /tmp/worldstate-bim-data/1305031916.701048.png \
  --depth /tmp/worldstate-bim-data/1305031916.711186.png --roi 10 228 90 295 \
  --output /tmp/worldstate-bim-data/visible-surface.json

/tmp/worldstate-bim-venv/bin/python -m pytest tests products/worldstate_bim/tests
```

RGB 与深度的时间差分别约 6.3 ms 和 10.1 ms；使用 TUM 文档推荐的 ROS 默认内参和 `depth/5000` 米。实验没有校正像素级异步误差。点云 `.ply` 单位任意且非建筑 IFC；用户定义的墙高和厚度不能从可见平面残差中推断。
