# B/C 云端联合训练交接：职责与接口

本包交付 A 已实现的数据、窗口、预处理与编码组件，并提供完整 R1 参照模型供 B 直接接入训练。当前任务转向云端原始 1 分钟数据；本地数据处理不属于本次交接的前置工作。云端依赖安装和桥接示例见交接包入口说明及 `examples/cloud_bridge.py`。

首次联合训练使用 **R1 + N1 + 当日 120 个交易分钟 + MSE**。该配置是确定的训练起点，尚无云端监督训练成绩。历史组件测试与本次交接包检查的范围，应以随包验证记录为准；不能据此填写“真实 DAI、Linux/GPU、完整云端训练已验证”。

## A 已交付的组件

| 模块 | 可直接使用的内容 |
| --- | --- |
| `ptop.data`、`ptop.schema` | 云端原始字段规范化、固定 25 字段顺序、观测掩码、股票映射与唯一键处理 |
| `ptop.official` | 官方截面、动态 `bar1m`、官方 `vwap_return` 的查询与连接 |
| `ptop.windows` | 当日惰性窗口、完整决策截面批次、训练窗口引用原始行并集 |
| `ptop.preprocessing` | N0/N1/N2 拟合、冻结、变换及 JSON 状态 |
| `ptop.encoders` | R0/R1 输入、统一与分组 MLP、P1/P5 分块、DeepLOB 输入编码 |
| `ptop.models` | R0/R1 完整参照、研究分支主干与输出头；R1 已包含 GRU、注意力和收益输出 |
| `ptop.targets` | `LabelSpec`、显式目标支持区间连接、时间折与标签跨界筛除 |
| `ptop.output`、`ptop.bundle` | 三列输出与逐时点覆盖检查、固定候选 JSON 模型包保存与恢复 |

B 可用 `create_model("R1")` 获取完整模型，直接将 `model.parameters()` 交给优化器。若沿用本次首轮配置，无需重复实现 R1 主干或重新组装 A 的 encoder。

## 云端接入必须提供的值

以下值决定函数输入和训练范围。跳过额外数据诊断后，仍需填入实际值才能调用现有接口。

| 输入 | 格式与来源 | 交接责任 |
| --- | --- | --- |
| `datasources` | 映射中必须包含 `bar1m`；训练由调用方传入获准表名，平台推理使用实际传入映射 | C 提供平台接入方式，B 传递 |
| `instrument_map` | 一对一 `dict[int, str]`，键是 `instrument_id`，值是正式 `instrument` | C 确认来源与覆盖范围，A 接口负责使用 |
| 官方采样集合 | `cpt_jyc_2026_instruments` 的 `date, instrument`；作为完整应预测集合 | C 确认实际采样与历史成员含义 |
| `trading_grid` | 显式、排序、唯一、精确到分钟的 `pd.DatetimeIndex`，时间按北京时间解释 | C 提供正式分钟网格及边界依据 |
| 可见性 | 逐行 `available_at`，或已确认的 `bar_end_is_available=True` | C 明确 Bar 结束时间与可用时间的关系 |
| 数据区间 | 授权的训练、验证、历史读取和输出起止时间，分别保存 | B/C 共同确定 |
| `LabelSpec` | 非空字符串字段 `version, source, target_definition, residualization, boundary_policy` | C 提供真实定义和版本 |
| 目标支持表 | `sample_id, target_valid, target_start, target_end, label_spec_version` | C 根据真实标签合同准备 |
| 合同版本 | `source, sampling, universe, visibility, label, training_scope` 六个非空字符串 | C 提供，B 保存到模型包 |

`instrument_map` 需要覆盖本次应预测集合及所读取行情。当前映射随模型包静态保存，遇到未知 ID、未知代码或映射冲突会抛出 `ContractError`。C 需要确认评测期新成员如何从授权来源映射；现有接口不会为新股票临时猜测 ID。

`WindowDataset` 要求每个 `decision_time` 都位于显式 `trading_grid`。网格覆盖当日已获准使用的完整历史交易分钟，午休不增加槽位，真实交易分钟缺失记录仍保留槽位。当前窗口按日建立，最多取当日最近 120 个已结束且可见的交易分钟；开盘不足时在左侧填充。仅把 `history_start` 调早不会开启跨日窗口。

`official_targets` 直接接入 `cpt_jyc_2026_vwap.vwap_return`，保留官方数值。它不会根据字段名称推断目标公式或 `target_end`，也不会自行使用 `decision_time + 30 分钟`。有限标签缺少显式支持区间会报错；有效区间必须满足 `target_start >= decision_time`、`target_end > target_start`，且不跨夜。午休、尾盘及残差化按 C 提供的合同填写。

## 数据与张量合同

云端 `source="cloud"` 路径使用元单位价格和 `amount`，不除以 100。成交量、盘口数量和笔数保留各自原始单位。六个委托笔数字段在源数据及中间存储中保留 `int32` 或更宽的无损表示，禁止窄化为 `int16`；规范数值层统一转换为 `float64`。云端第 4、5 档和 `pre_close` 不进入本次固定 25 字段。

字段顺序统一取 `ptop.schema.FEATURES`：

1. `open, high, low, close`。
2. `volume, amount, deal_number`。
3. 按档位 1、2、3 排列，每档先 `bid_price` 再 `ask_price`。
4. 按相同档位顺序排列 `bid_volume, ask_volume`。
5. 按相同档位顺序排列 `bid_num_orders, ask_num_orders`。

规范层 `CanonicalData.values` 的索引是 `MultiIndex(datetime, instrument)`；这里 `instrument` 层保存整数 `instrument_id`，字符串代码另存于映射和元数据。规范原始缺失值为 `NaN`，`observed` 为独立布尔表。预处理完成后缺失位置填零并转为 `float32`，原始观测标志保持不变。

| 对象 | 类型与形状 | 调用语义 |
| --- | --- | --- |
| `WindowBatch.x` | NumPy `float32 [batch,L,25]` | 进入模型前转换为 torch tensor |
| `WindowBatch.observed` | NumPy `bool [batch,L,25]` | `True` 表示该字段有效且当时可见 |
| `WindowBatch.step_valid` | NumPy `bool [batch,L]` | `True` 表示真实历史交易时间槽 |
| `WindowBatch.predictable` | NumPy `bool [batch]` | 模型使用的字段中至少有一个有效原始观测 |
| `WindowBatch.metadata` | DataFrame | 包含 `sample_id, decision_id, instrument_id, decision_time, instrument` 和不可预测原因 |
| `WindowBatch.bar_times`、`row_positions` | `[batch,L]` | 原始时间与源行位置；无源行位置使用 `-1` |
| `encoder(x, observed, step_valid)` | `(tokens, token_valid)` | R1 为 `float32 [batch,L,64]` 与 `bool [batch,L]` |
| `model(x, observed, step_valid)` | `float32 [batch]` | 每个输入样本对应一个收益预测值，顺序保持一致 |

送入模型的三个张量必须在同一设备上；`x` 必须是 `float32`，两个 mask 必须为 `torch.bool`。输入始终保持 25 字段，包括使用字段子集的模型。结构填充只能位于左侧，`observed=True` 必须对应 `step_valid=True`。真实零数值的观测标志为真；真实缺失分钟的时间槽保留为真，字段观测可以全为假。

全空窗口必须在模型调用前按 `predictable` 分流，记录 `sample_id` 与原因。字段子集模型创建窗口时传入 `fields=model.encoder.fields`，确保 `predictable` 按实际使用字段计算。无法预测样本不生成固定分数，也不从完整应预测集合中删除。

## 实际 API 调用表

`examples/cloud_bridge.py` 已将以下核心调用连在一起。B/C 可从这四个入口调用，并保留原模块接口供调整训练组织方式。

| 桥接入口 | 必要输入与返回 | 接手方式 |
| --- | --- | --- |
| `fetch_cloud_training(query, datasources, *, start_date, end_date, history_start, instrument_map, support, label_spec, bar_end_is_available)` | 返回 `(raw, expected, targets)` | 传入真实 `dai.query` 和 C 的合同数据 |
| `prepare_fold(raw, expected, targets, *, label_spec, trading_grid, fold, scale_review, window_length=120, fields=FEATURES, seed=17, num_workers=0)` | 返回 `PreparedFold` | 内部拟合并冻结 N1，建立完整训练/验证截面及跨界排除记录 |
| `supervised_step(model, optimizer, batch, targets, *, device)` | 返回含 `loss, count, sample_ids, scores, skipped` 的字典 | 有 optimizer 时执行一次 MSE 更新和梯度按值裁剪；`optimizer=None` 时计算验证结果 |
| `predict_cloud(query, datasources, model, processor, *, start_date, end_date, history_start, instrument_map, trading_grid, bar_end_is_available, device, window_length=120, fields=None)` | 返回 `(output, exclusions, coverage)` | `fields=None` 使用 `model.encoder.fields`，由 C 的 Notebook 调用 |

`PreparedFold` 提供 `processor, train_loader, validation_loader, train_targets, validation_targets, split_audit`。B 的 epoch 循环用对应 loader 和 targets 调用 `supervised_step`，汇总时按 `count` 加权；无有效监督样本的批次返回 `loss=None, count=0`，同时给出 `skipped`，不计为一次参数更新。调用前由 B/C 执行 `model.to(device)`。

`prepare_fold` 当前处理内存可容纳的数据，拟合、诊断、窗口索引和转换会持有多份表。B 需按云端资源组织实际读取范围与训练数据分区，不能把五年长表直接视为可一次性装入的输入。分区训练必须共用该折训练记录拟合的同一个处理器；不能在每个分区重新拟合并混用尺度。

| 调用 | 返回值或用途 | 必须保持的行为 |
| --- | --- | --- |
| `fetch_inference_inputs(query, datasources, start_date=..., end_date=..., history_start=..., instrument_map=..., bar_end_is_available=...)` | `(raw, expected)` | `query` 注入平台 `dai.query`；只读取截面与行情 |
| `expected_from_sections(sections, instrument_map)` | 完整 `expected` DataFrame | 从截面产生稳定 ID；不按行情是否存在删减成员 |
| `normalize_bars(frame, source="cloud", instrument_map=..., bar_end_is_available=...)` | `CanonicalData` | 用于调用方已自行读取的云端行情；可携带逐行 `available_at` |
| `fetch_label_values(query, start_date=..., end_date=...)` | `date, instrument, vwap_return` 表 | 仅供训练及评价路径调用 |
| `official_targets(expected, labels, support, spec)` | 六列目标表 | 通过 `sample_id` 连接到窗口元数据，保留 `target_valid` |
| `WindowDataset(raw, expected, trading_grid, length=120, fields=model.encoder.fields)` | 惰性窗口对象 | `raw` 需已携带可见性元数据，否则显式传入确认过的 `bar_end_is_available` |
| `fit_row_union(train_windows, fit_start=..., fit_end=...)` | 唯一原始行 `MultiIndex` | `train_windows` 只含训练日期的完整决策集合 |
| `FrozenPreprocessor("N1").fit(raw.values, raw.observed, referenced_rows=..., fit_start=..., fit_end=..., by_column=...)` | 拟合后的处理器 | 首尾日期均为包含整天的午夜日期；每折创建新实例 |
| `processor.freeze(scale_review=...)` | 冻结后的处理器 | 保存真实审阅或明确跳过审阅的记录标识；见下文 |
| `processor.transform(raw.values, raw.observed)` | `float32` DataFrame | 只使用已有冻结状态；保留原 `observed` 组织后续 `CanonicalData` |
| `DecisionBatchSampler(dataset, shuffle=True, seed=...)` | 完整决策截面索引批次 | 也可提供独立 CPU `generator`，不能与 `seed` 同时提供 |
| `DataLoader(dataset, batch_sampler=..., collate_fn=collate_windows)` | `WindowBatch` | 不再同时指定 `batch_size`、`shuffle`、`drop_last` |
| `dataset.get_batch(indices)` | `WindowBatch` | 可直接按索引读取批次；不缓存训练中的编码结果 |
| `create_model("R1")` | 完整 `R1Model` | 两层 GRU、隐藏宽度 64、dropout=0，A/B 参数共同注册 |
| `TimeFold(name, train_start, validation_start, validation_end).split(samples)` | 训练与验证样本表 | 输入带 `predictable, target_valid, target_end`；同时剔除标签跨界样本 |
| `save_bundle(path, model, processor, model_name="R1", window_length=120, contracts=..., seed=..., training_record=..., instrument_map=...)` | 写入 JSON 模型包 | `path` 必须尚不存在；运行记录必须非空 |
| `load_bundle(path)` | `(model, processor, manifest)` | 恢复全部状态并执行 `model.eval()`；调用方再选择设备 |
| `audit_output(output, expected_dates, start_date=..., end_date=...)` | 逐时点覆盖报告 | `expected_dates = expected.rename(columns={"decision_time": "date"})`，保持完整成员 |

`processor.fit` 的输入必须是原始规范 `float64` 数据和原始 mask，不能再次传入已填零的标准化数据。调用 `transform` 后可把返回值、原 `observed`、原元数据和映射组成新的 `CanonicalData`，交给训练或推理窗口。

预处理拟合时，先按训练日期选择完整决策集合，再取得窗口引用的原始行并集。此集合不按标签数值、`target_valid` 或监督样本数量筛选。监督训练阶段再连接标签并筛选损失样本。`TimeFold.split` 已包含标签有效性筛选，不能直接将其结果当成预处理拟合集合。

### 本次跳过额外尺度审阅的记录方式

用户已明确本次先进入云端训练，暂不追加数据与尺度验证。现有 `fit` 内部会生成训练诊断并执行数值检查，`freeze` 仍要求一个非空 `scale_review` 字符串。桥接示例应使用明确的跳过记录，例如 `user-request-2026-10-11:cloud-scale-review-skipped`，并在 `training_record` 中登记 `scale_review_status="skipped_by_user_request"` 与该原因。

这里的标识表示“按用户要求跳过额外人工尺度审阅”，不表示已审阅或通过云端尺度验收。不得填写不存在的报告编号、已通过字样或使用合成结果证明云端尺度已验证。现有缺字段、无有效拟合观测、非有限数值等运行时错误检查继续生效。

## B 接手后需要完成的工作

1. **接通实际训练入口。** 调用桥接示例取得云端批次与目标，以 `create_model("R1")` 构建模型。学习率、epoch、早停和种子写入配置；原方案起点为 Adam、学习率 `1e-3`、最多 200 epochs、验证损失连续 20 epochs 未改善时早停、梯度按值裁剪到 `[-3,3]`。
2. **完成时间切分和每折拟合。** 与 C 确认授权日期，按完整交易日划分训练与验证，使用真实 `target_end` 防止标签跨界。每折独立拟合 N1，验证与推理仅调用 `transform`。记录 `fit_start/end`、引用行指纹和该折日期。
3. **实现联合参数更新。** 优化器接收 `model.parameters()`，覆盖 encoder、GRU、注意力和预测头。保留可微计算，不分离或缓存学习后的 token。记录有限 loss、梯度及实际更新次数。
4. **按完整截面组织训练。** 使用 `DecisionBatchSampler`，保留尾截面；监督 loss 只取 `predictable & target_valid` 且标签未越界的样本。MSE 若需分块，应按有效样本总数准确加权；验证损失汇总也按有效样本数计权。截面排序目标的分组方式由 C 给出。
5. **保存训练结果和恢复信息。** 使用 `save_bundle` 保存推理所需状态，训练日志保存配置、epoch、有效样本数、验证指标、设备和运行时间。需要断点续训时另行保存 optimizer、scheduler、训练进度及 Python/NumPy/PyTorch CPU/CUDA、采样器 generator 的随机状态；当前 JSON 模型包不包含这些续训状态。
6. **交付给 C。** 提供最终选定权重目录、完整训练脚本、云端实际依赖清单、训练记录和预处理冻结状态。实际云端训练与平台资源情况由运行结果填写。

当前 `save_bundle` 只接受固定候选名与对应模块结构。若 B 更换主干、隐藏宽度或模块配置，需要同时扩展 `create_model` 与保存/加载协议并检查恢复行为；不能把新结构继续标记为已有的 `R1`。

## C 接手后需要完成的工作

1. **落实数据合同。** 提供上表中的授权日期、真实股票映射、正式分钟网格、截面口径、可见性声明、`LabelSpec` 与目标支持表。对官方模板的演示日期和采样删减不作授权范围推断。
2. **确定目标与评价。** 首轮按原值 `vwap_return` 使用 MSE；确认其量纲、残差化状态和边界语义。评价应覆盖 IC、IC_IR、多空夏普、压力场景和换手，写明所用实现、版本、参数和缺失处理。自定义指标只按其实际定义命名，官方评估模块的真实接入与结果由 C 在平台完成。
3. **完成提交 Notebook。** 最终提交保留一个 Notebook，入口为 `main(datasources, start_date, end_date)`。入口加载固定 JSON 权重与 N1 状态，使用传入的 `datasources["bar1m"]`；历史读取范围从授权规则和传入区间计算，不硬编码为本次训练日期。
4. **组织纯推理输出。** 推理路径不读取目标表，不调用 `fit` 或更新权重。返回按顺序恰好三列 `date, instrument, score`，分数越大表示预测未来收益越高。输出键来自完整官方应预测集合，限制在本次传入区间。
5. **保留覆盖统计。** 全空样本记录原因，输出与完整截面连接后调用 `audit_output`；逐时点缺失率不超过 40%，不能整时点无输出，键唯一且分数有限。标签缺失不决定纯推理时是否生成分数。
6. **整理最终提交材料。** 包含固定模型包、训练源码、Notebook、依赖及第三方来源/许可、随机种子与合同版本、研究和复现说明。记录实际平台返回的运行状态与提交结果。

## 模型包与依赖边界

固定模型包包含 `model.json`、`preprocessor.json` 和 `manifest.json`。它保存模型参数及 buffers、N1 中心/尺度、字段顺序、窗口长度、种子、股票映射、训练记录、六项合同版本、文件 SHA-256 和依赖版本。

`load_bundle` 严格比较 `torch, pyqlib, numpy, pandas, pyarrow` 的版本字符串；训练与推理必须使用同一组版本，PyTorch 的 CPU/CUDA 后缀也会参与比较。Qlib 源码固定到 `54355232463878d2eebb91fe0ee5fa7fa1f5976c`，源码版本、包版本与来源文件保持对应，具体准备方式见云端依赖说明。

当前包中保存的静态合同值应是可追溯的真实版本或来源标识。`training_record` 应覆盖实际配置、日期范围、设备、运行结果及本次跳过审阅的状态，不能通过填写非空占位内容宣称云端训练已完成。
