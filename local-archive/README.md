# PtoP 归档工作区

归档日期：2026 年 11 月 16 日。完整目录、Git 快照、验证证据和未完成事项见 [归档说明](ARCHIVE.md)。

| 内容 | 入口 |
| --- | --- |
| 集成代码与训练、恢复、推理 | [实际 Git 仓库](work/repo-publication/README.md) |
| 当前集成状态 | [仓库归档记录](work/repo-publication/docs/archive_status.md) |
| 历史交付与本次完整源码、Git 历史备份 | [deliverables/](deliverables/) |
| 本次归档清单与验证资料 | [reports/archive-20261116/](reports/archive-20261116/) |

`work/repo-publication/` 是需要保留的实际仓库。根目录以下使用说明适用于 A 的独立模块快照及其 v2 模型包。

## A 模块使用说明

依据 [A 成员方案](docs/A成员数据与输入编码方案.md)实现 Python 包 `ptop`。当前提供 A 的数据、预处理、窗口、输入编码，以及用于接口联调和源码等价验证的完整参照模型。真实训练与平台提交依赖的合同缺口见 [开发验证记录](docs/开发验证记录.md)。

本地 1 分钟全包验收及真实短区间预处理检查记录见[真实数据检查记录](docs/本地1分钟数据验收与预处理检查.md)。当前继续使用云端数据，本地数据问题暂停处理。内置组件及无 Qlib 环境的代码验收见[验证记录](docs/内置Qlib组件验证.md)。

## 安装与验证

当前验证环境为 Windows x64、Python 3.12.10、PyTorch 2.8.0 CPU。需要已安装 Python 3.12 和 `uv`。在项目根目录执行：

```powershell
.\tools\setup.ps1
.venv\Scripts\python.exe tools\smoke.py --output work\synthetic-check
```

`setup.ps1` 按 `uv.lock` 安装依赖并运行测试。第二条命令的输出目录必须尚不存在。它使用独立合成数据，验证单位转换、冻结预处理、惰性窗口、A/B 联合梯度、逐时点覆盖，以及独立进程重载；结果写入该目录的 `report.json`。这些结果只验证实现，不代表比赛预测效果。

Qlib 组件以 Python 源码保存在 `src/ptop/_vendor/qlib/`，无需安装 `pyqlib` 或编译 Qlib。依赖安装在开发准备阶段完成；处理数据和模型运行不会下载依赖。Linux、CUDA 和实际平台环境尚未完成运行验收。

## 模块与接口

| 模块 | 接口和职责 |
| --- | --- |
| `ptop.schema` | 固定 25 字段、价格组、盘口子集及来源版本 |
| `ptop.data` | `normalize_bars`、`read_feather_bars`、`concat_partitions`；本地／云端规范化、观测掩码和映射 |
| `ptop.official` | `expected_from_sections`、`fetch_inference_inputs`、`fetch_label_values`、`official_targets`；接入模板指定的数据表 |
| `ptop.windows` | `WindowDataset`、`fit_row_union`、`DecisionBatchSampler`、`collate_windows`；Qlib 当日窗口及完整截面批次 |
| `ptop.preprocessing` | `FrozenPreprocessor`；N0/N1/N2、训练唯一原始行拟合、诊断、冻结、JSON 状态 |
| `ptop.encoders` | 原始拼接、ALSTM、统一／分组 Net、P1/P5 patch、DeepLOB |
| `ptop.models` | R0/R1、同字段盘口对照、研究分支 GRU／注意力及 DeepLOB LSTM |
| `ptop.targets` | 显式标签合同、目标支持区间验证、按完整日切分与跨界清除 |
| `ptop.output` | `audit_output`；列、键、数值、正式区间及逐时点覆盖检查 |
| `ptop.bundle` | `create_model`、`save_bundle`、`load_bundle`；固定候选配置及纯 JSON 模型包 |
| `ptop.local_archive` | 流式全包审计、来源指纹、异常定位，原始文件保持不变 |
| `ptop.local_preflight` | 无股票代码映射的本地真实数值、窗口和模型检查 |
| `ptop.preprocessing_audit` | N0/N1 诊断拟合、实际激活及价格分辨率检查；禁止正式冻结 |

原始规范数据为 float64 DataFrame，索引是 `(datetime, instrument)`，其中 `instrument` 层保存整数 `instrument_id`；对外字符串代码单独保存在映射与元数据中。缺失数值为 NaN，`observed` 独立保存。只在处理完成后填零并转换 float32。

```python
raw = normalize_bars(frame, source="local", instrument_map=mapping,
                     bar_end_is_available=visibility_confirmed)
windows = WindowDataset(raw, expected, trading_grid, length=120)
rows = fit_row_union(windows, fit_start=train_start, fit_end=train_end)
processor = FrozenPreprocessor("N1").fit(
    raw.values, raw.observed, referenced_rows=rows,
    fit_start=train_start, fit_end=train_end,
)
diagnostics = processor.diagnostics(raw.values, raw.observed)
# 完成实际尺度审阅后，使用对应记录标识冻结。
processor.freeze(scale_review=review_record)
values = processor.transform(raw.values, raw.observed)
```

`fit_row_union` 必须接收训练决策集合的窗口；统计记录不按标签有效性筛选。`fit_start`、`fit_end` 均为完整日历日期，包含首尾当天。不同折创建独立处理器。窗口使用显式分钟网格，午休不生成虚构槽位；默认不跨日。所有重叠窗口按需展开。

交给 B 的张量为 `x: float32[B,L,25]`、`observed: bool[B,L,25]`、`step_valid: bool[B,L]`。调用 `dataset.get_batch(indices)` 后，先用 `batch.predictable` 分流全空样本。字段子集模型构造窗口时传入 `fields=model.encoder.fields`。外部 mask 的 True 表示有效，编码器返回 `(tokens, token_valid)`，完整模型返回一维分数。

PyTorch `DataLoader` 使用 `batch_sampler=DecisionBatchSampler(dataset)` 与 `collate_fn=collate_windows`，每批保留一个完整决策截面。训练需要打乱截面时显式传入 `shuffle=True, seed=17` 或独立 CPU generator。Windows 启动 worker 的调用代码放在 `if __name__ == "__main__":` 中。

固定模型名称为 `R0`、`R1`、`R1-Book`、`Net64`、`Net192`、`GroupedNet`、`Patch1`、`Patch5`、`DeepLOB`。所有学习参数联合训练，禁止缓存训练中的 token。正式监督训练与平台 Notebook 由 B/C 在已确认合同基础上接入。

## 模型包与来源

模型包包含 `model.json`、`preprocessor.json`、`manifest.json`，记录全部参数与 BN buffers、字段、模型规格、窗口、依赖、内置组件版本、合同版本、股票映射、种子和运行记录。当前包格式为 v2，与 v1 包不兼容。恢复时校验文件哈希、配置、张量形状与类型，执行 `eval()`；推理只变换预处理数据。

Qlib 固定提交为 `54355232463878d2eebb91fe0ee5fa7fa1f5976c`。内置源码及适配内容见[组件来源](src/ptop/_vendor/qlib/SOURCE.md)，许可随源码和安装包提供。与原版的专项对照测试位于 `validation/test_qlib_equivalence.py`，只有这项验证需要原版 Qlib。用户提供的两个官方模板保持原样。
