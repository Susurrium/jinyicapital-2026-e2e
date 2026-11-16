# 项目归档状态

来源归档日期：2026 年 11 月 16 日。本目录来源于集成提交 `101ad3c8716c550d7c3ae6f4fb2e4282a246b5a0`。整个公开归档的目录与验证范围见 [归档索引](../../ARCHIVE.md)。

## 已实现内容

- 数据：raw25 字段、独立观测掩码、当日分钟窗口、冻结 N0/N1/N2、官方截面与标签接入。
- 模型：A 的九种固定候选，B-GRU、B-Transformer、B-TCN 和 B-SelectiveSSM。
- 训练：联合优化、时间折及标签跨界检查、早停、最佳和最新 checkpoint、epoch 边界恢复、FP32/BF16/FP16 训练。
- 推理：冻结预处理、股票分批和日期分区、完整应预测集合与逐时点覆盖审核。
- 损失：`ptop.objectives.RegressionObjective` 默认采用训练标签尺度下的 Huber，可选截面排序；`jyc_e2e.losses.PredictionObjective` 提供可配置 MSE/Huber 与时点归约。
- 保存：固定候选模型包 v3，参数化及携带源码模型包 v4，均记录内置 Qlib 组件版本及精确依赖。

## 配置与环境

日常运行从源码使用所需 Qlib 组件，无需安装外部 `pyqlib`。直接依赖固定为 NumPy 2.2.6、pandas 2.2.3、PyArrow 20.0.0 和 PyTorch 2.8.0；推荐 Python 3.12。模型恢复核对实际 Torch build。

`configs/b_train_cli_diagnostic.json` 是诊断 CLI 配置，使用真实行情和人工目标；其中数据路径属于原验证环境。`configs/b_diagnostic_cpu.json` 用于诊断实验矩阵。`configs/b_official_template.json` 是正式实验模板，必要合同输入保留空值。

正式训练仍需完整采样集合、股票映射、分钟网格、可见性、LabelSpec、目标支持区间和授权日期。现有部分数据导出不构成这些合同全部完成的证据。训练和实验模块依赖 Unix `resource`，Windows 运行需另行处理平台兼容性。

## 验证状态

| 范围 | 保存的证据 |
| --- | --- |
| 内置组件与原版 Qlib 对照 | 本地最终 XML 为 44 项通过 |
| Linux 固定及参数化模型包 | 本地最终专项 XML 为 13 项通过 |
| 独立 Linux CPU 完整测试 | 验证文档记载 281 项通过、16 项 CUDA 跳过 |
| 较早 CPU/CUDA 及真实行情诊断 | 环境、提交、测试数量及原始日志位置见 [B 验证记录](b_verification.md) |

归档核验检查文件完整性、源码快照、文档和恢复工具。本次补齐资料未重新运行模型测试，未访问原验证服务器。历史成功和失败记录均保存在 [原始资料快照](../../local-archive/reports/archive-20261116/)。

## 未完成事项

正式收益标签的样本外实验、官方最终评价、唯一提交 Notebook、完整平台资源验收和成功提交记录，尚无本地可核对的完成证据。诊断训练结果仅支持工程流程检查。

[第一阶段损失说明](stage_one_losses.md)描述现有接口；[目标与评价规划](objective_training_plan.md)中的连续时点、组合权重、换手约束、压力评估等内容仍属于研究安排，具体实现范围以代码和验证记录为准。
