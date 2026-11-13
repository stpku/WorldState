# WorldState Benchmark（开发中）

| 套件 | 目的 | 本轮真实状态 |
| --- | --- | --- |
| WS-Geometry | 相同真实照片、相机位姿与重投影 | [TUM + CPU COLMAP 4/8/16/32](../acceptance/bim-reset-round2-20261113/STATUS.md)；不提供独立尺度或稠密完整性。 |
| WS-Structure | 可见构件语义、实例与布局 | [CRASLAB 多构件开发集](../examples/bim_real_scan_craslab/room_round3/README.md)：8 面推断墙及窗洞；点级表面覆盖不足，实例与独立尺寸未测。 |
| WS-BIM | 原生 IFC、可编辑性、拓扑和 GUID | 墙、板、门窗、开口及部分空间拓扑已有产品实现；真实扫描例已通过 Bonsai 墙长、墙高、窗位置修改和受限同步，完整房间尚未验收。 |
| WS-RealRoom | 用户照片到可编辑 BIM 和人工成本 | [冻结协议](ws_realroom/PROTOCOL.md)与[采集和评测工具](ws_realroom/README.md)；真实独立验收房间未采集。 |
| WS-Campus | 授权建筑公开展示 | 规划；校园素材没有新上传或对外发布。 |

WS-RealRoom 尚无满足冻结协议的独立验收场景。负责人可以在仓库外初始化隔离的采集目录，按其中清单采集并保管私有真值：

```bash
python3 benchmarks/ws_realroom/init_room.py /path/outside/repo/room-001 --room-id room-001
```

脚本不会填造照片或测量值，也不会覆盖已有目录；生成的私有目录默认整体被 Git 忽略，不能把冻结验收真值提供给待测算法。

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

Cloud2BIM 和 PyStruct3D 试验需使用**独立** Python 3.12 环境，避免 Open3D 与产品依赖互相升级。`requirements-cpu-py312.txt` 为本轮 Linux x86_64 实际依赖版本（Open3D wheel SHA-256 `01e4590dc2209040292ebe509542fbf2bf869ea60bcd9be7a3fe77b65bad3192`），不同平台须重新解析依赖和验证。

```bash
python3.12 -m venv /tmp/ws-structure-venv
/tmp/ws-structure-venv/bin/pip install -r benchmarks/ws_structure/requirements-cpu-py312.txt
git clone https://github.com/humantecheu/pystruct3d /tmp/pystruct3d
git -C /tmp/pystruct3d checkout fcbe3070deef2d9ed2662abd77fdf0ad35c39f87
/tmp/ws-structure-venv/bin/pip install --no-deps -e /tmp/pystruct3d
git clone https://github.com/VaclavNezerka/Cloud2BIM /tmp/cloud2bim
git -C /tmp/cloud2bim checkout cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e

OPENBLAS_NUM_THREADS=1 /tmp/ws-structure-venv/bin/python benchmarks/ws_structure/run_pystruct_bbox.py \
  --points /tmp/ws-craslab-sample/xyz.npy --mask /tmp/ws-craslab-output/predicted-mask.npy \
  --source-checkout /tmp/pystruct3d \
  --output /tmp/ws-pystruct-bbox.json

OPENBLAS_NUM_THREADS=1 /tmp/ws-structure-venv/bin/python benchmarks/ws_structure/run_cloud2bim.py \
  --source-checkout /tmp/cloud2bim --points /tmp/ws-craslab-sample/xyz.npy --output-dir /tmp/ws-cloud2bim
OPENBLAS_NUM_THREADS=1 /tmp/ws-structure-venv/bin/python benchmarks/ws_structure/evaluate_ifc_surface_labels.py \
  --ifc /tmp/ws-cloud2bim/cloud2bim.ifc --points /tmp/ws-craslab-sample/xyz.npy \
  --labels /tmp/ws-craslab-sample/labels.npy --output /tmp/ws-cloud2bim-evaluation.json
```

PyStruct3D 使用产品同一批候选点，不是两个独立分割方法的准确率比较；包围盒宽度不是墙体厚度。Cloud2BIM 完整管线在同一未标注 XYZ 上运行，headless 包装器只关闭 LaTeX 绘图排版；其 IFC 有已知 schema 错误、未经核实的材料和占位地理位置，不可当作工程模型。

抽样代码会校验原始文件 SHA-256；推理先写 IFC、IR 和预测掩码，之后才加载独立存放的标签。该标注来自同一开发场景，**不是独立场景泛化验证**。不提交原始点云。模型推理、采集、标注、修订、审核和失败重试分别计时；当前人工工时与每个合格模型成本均未测。

VGGT-Omega GPU 包详见 [GPU 实验](ws_geometry/GPU.md)。允许的公开数据许可须逐个核查；私有、客户和无授权数据不得进公开仓库。
