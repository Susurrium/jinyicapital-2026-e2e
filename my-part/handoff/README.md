# A → B/C 云端联合训练交接包

本目录保留 2026 年 10 月 11 日的交接源材料，适用当时的外部 Qlib 依赖和首轮配置。完整集成代码见 [project/](../../project/README.md)，当前保存范围见 [归档说明](../../ARCHIVE.md)。原始交接 ZIP 保留于 `my-part/deliverables/ptop-A-to-BC-20261011.zip`。

交接日期：2026 年 10 月 11 日。主线使用云端授权的原始 1 分钟数据，首轮配置为 **R1 + N1 + 当日 120 分钟窗口 + MSE**。A 已提供数据规范化、窗口、预处理、encoder、完整参照模型和 JSON 模型包接口。

本包用于 B/C 接通云端联合训练。完整训练循环、实际数据合同、云端依赖安装和平台提交入口由下述分工完成；包内没有已训练的比赛权重。本轮不开展额外本地数据验收。

## 阅读顺序

1. **B、C 共同阅读** [云端依赖](docs/云端依赖.md)，在目标训练环境准备固定依赖，并记录 Torch 的完整构建版本。
2. **C 准备运行输入**：实际 `datasources`、股票映射、分钟网格、标签支持区间和授权日期，规格见 [B/C 职责与接口](docs/B_C职责与接口.md)。
3. **B 使用调用示例** [cloud_bridge.py](examples/cloud_bridge.py)，接入训练循环、验证 loss、早停和 checkpoint。
4. **C 完成提交封装**：从 JSON 包恢复固定模型，提供 `main(datasources, start_date, end_date)`，返回 `date、instrument、score`。

## 包内内容

| 路径 | 用途 |
| --- | --- |
| `src/ptop/` | 与当前工程一致的 11 个核心 Python 模块 |
| `examples/cloud_bridge.py` | 真实 query 注入、N1 拟合和数据加载器、单步训练／验证、纯推理调用 |
| `configs/first_run.json` | 首轮模型和训练起点；未知运行输入明确列出 |
| `docs/` | 云端依赖、接口、B/C 分工和剩余工作 |
| `third_party/` | 锁定 Qlib 源码 ZIP、许可证、来源哈希与算法引用 |
| `references/official_templates/` | 用户提供的训练／预测模板原文，供 C 核对平台接入 |
| `tests/` | 现有核心组件的合成测试，供后续需要时运行 |
| `MANIFEST.json` | 包内逐文件 SHA-256 清单 |

## 接口调用顺序

```python
import torch
from ptop.bundle import create_model, save_bundle, load_bundle
from examples.cloud_bridge import (
    fetch_cloud_training, prepare_fold, supervised_step, predict_cloud,
)
```

训练按以下顺序接入。函数所需的真实运行参数及返回值详见接口文档：

```python
raw, expected, targets = fetch_cloud_training(
    query, datasources,
    start_date=start_date, end_date=end_date, history_start=history_start,
    instrument_map=instrument_map, support=label_support, label_spec=label_spec,
    bar_end_is_available=bar_end_is_available,
)
prepared = prepare_fold(
    raw, expected, targets,
    label_spec=label_spec, trading_grid=trading_grid, fold=fold,
    scale_review=scale_decision_record, window_length=120, seed=17,
)
torch.manual_seed(17)
model = create_model("R1").to(device)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
for batch in prepared.train_loader:
    result = supervised_step(model, optimizer, batch, prepared.train_targets, device=device)
```

这是 B 训练循环中的数据与单步调用示例。B 继续实现 epoch、验证、早停、按样本数加权汇总 loss 和恢复训练状态。完整截面不能静默丢弃尾批；全部 A/B 学习参数需要进入优化器。

示例中的 `query` 传 `dai.query`；日期、映射、网格、`LabelSpec`、`TimeFold` 和支持表由 C/B 按接口文档提供。`prepare_fold` 的 `seed` 控制截面打乱顺序；模型初始化的种子由 B 显式设置。

`scale_decision_record` 填写本轮实际决定。按当前安排可明确记录“本轮直接云端训练，额外人工尺度审阅暂缓；使用固定 N1”。该记录不等于云端尺度检查通过。必要的类型、形状、日期和有限性检查由代码保留。

## 数据和运行约定

- 行情表动态使用 `datasources["bar1m"]`；截面使用 `cpt_jyc_2026_instruments`，目标直接使用 `cpt_jyc_2026_vwap.vwap_return`。
- 云端价格和 amount 保持元单位，`source="cloud"`；委托笔数保持原始 int32 或更宽类型。
- 输入固定为 25 个原始字段及 observed；`x` 为 float32 `[B,L,25]`，两个 mask 均以 True 表示有效。
- N1 只拟合训练决策窗口引用的唯一原始行。验证和推理调用 transform，按既有状态运行。
- C 提供真实股票映射、官方网格和标签支持表。当前窗口实现要求决策端点在网格中；不符合时由 A/C 明确时间约定后适配。
- 数据准备示例会持有传入分区。B 应按内存可容纳的时间分区组织读入和 epoch，统一使用本折已经拟合的状态。
- 推理不读取目标表，不执行训练或重新拟合；加载后的模型使用 eval。

## 环境与交付状态

核心实现此前已在 Windows／Python 3.12.10／PyTorch 2.8.0 CPU 上验证；本交接包另做文件完整性与新桥接示例的合成检查。尚未在真实 DAI、Linux 或 CUDA 环境运行。

包内提供 Qlib 固定源码，Linux/CUDA 依赖需要在目标兼容环境中准备。依赖准备可以联网的环境与比赛实际运行环境按平台要求安排；正式训练、数据处理和推理不执行依赖下载。模型包恢复会严格比较 Torch、Qlib、NumPy、pandas、Arrow 的完整版本。

训练完成后，`save_bundle` 保存 `model.json`、`preprocessor.json`、`manifest.json`；它支持包内固定模型类型。B 如果修改模型结构，需同步扩展创建和保存／加载入口。优化器、调度器和随机状态属于 B 另行保存的续训 checkpoint。
