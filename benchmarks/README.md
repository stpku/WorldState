# WorldState Benchmark（开发中）

| 套件 | 目的 | 本轮真实状态 |
| --- | --- | --- |
| WS-Geometry | 相同真实照片、相机位姿与重投影 | [TUM + CPU COLMAP 4/8/16/32](../acceptance/bim-reset-round2-20261113/STATUS.md)；不提供独立尺度或稠密完整性。 |
| WS-Structure | 可见构件语义、实例与布局 | [CRASLAB 标签点云开发集](../examples/bim_real_scan_craslab/README.md)：仅一块未确认墙体。 |
| WS-BIM | 原生 IFC、可编辑性、拓扑和 GUID | 一个墙的 IfcOpenShell、Bonsai 和 web-ifc 局部回读；门窗、开口和完整拓扑未实现。 |
| WS-RealRoom | 用户照片到可编辑 BIM 和人工成本 | [采集、隔离与冻结门槛](ws_realroom/PROTOCOL.md)；真实独立验收房间未采集。 |
| WS-Campus | 授权建筑公开展示 | 规划；校园素材没有新上传或对外发布。 |

## CPU 安装和复现

Python 3.12、Linux x86_64，建议使用独立虚拟环境；Core 不依赖这些库。以下下载均为公开数据，实际耗时和镜像可用性因网络不同而异。

```bash
python3.12 -m venv /tmp/ws-bim-venv
/tmp/ws-bim-venv/bin/pip install -r benchmarks/ws_geometry/requirements-round2-cpu.txt

# 取首轮固定输入（含轨迹，可加 --with-model 下载视觉模型）
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/bim_real_room/fetch.py --data-dir /tmp/ws-bim-data
# 单一场景固定的 32 张照片，校验 SHA-256
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/fetch_tum.py --output-dir /tmp/ws-tum-32
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_geometry/run_colmap.py \
  --images /tmp/ws-tum-32 --manifest benchmarks/ws_geometry/tum-32-manifest.json \
  --groundtruth /tmp/ws-bim-data/groundtruth.txt --output-dir /tmp/ws-colmap \
  --counts 4 8 16 32

# 4.27 GB CRASLAB 全数据（注意本地存储与网络成本）
curl -fL -C - --retry 5 -o /tmp/craslabannotated.zip \
  'https://zenodo.org/records/7948116/files/craslabannotated.zip?download=1'
PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_structure/extract_craslab.py \
  --archive /tmp/craslabannotated.zip --output-dir /tmp/ws-craslab-sample
OPENBLAS_NUM_THREADS=1 PYTHONPATH=. /tmp/ws-bim-venv/bin/python benchmarks/ws_structure/run_scan_to_ifc.py \
  --sample-dir /tmp/ws-craslab-sample --output-dir /tmp/ws-craslab-output
```

抽样代码会校验原始文件 SHA-256；推理先写 IFC、IR 和预测掩码，之后才加载独立存放的标签。该标注来自同一开发场景，**不是独立场景泛化验证**。不提交原始点云。模型推理、采集、标注、修订、审核和失败重试分别计时；当前人工工时与每个合格模型成本均未测。

VGGT-Omega GPU 包详见 [GPU 实验](ws_geometry/GPU.md)。允许的公开数据许可须逐个核查；私有、客户和无授权数据不得进公开仓库。
