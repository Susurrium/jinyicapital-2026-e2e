# 工程验证范围

完整项目具备联合训练、严格时间切分、epoch 边界恢复、混合精度、最佳 checkpoint、JSON 模型包和冻结推理入口。验证代码位于 [tests/](../tests/) 与 [validation/](../validation/)。

历史内置组件集成记录描述独立 Linux CPU 环境完成 281 项测试，16 项 CUDA 检查跳过。历史固定提交 Qlib 对照结果为 44 项通过，逐项结果见 [qlib-reference-tests.xml](qlib-reference-tests.xml)。这些记录对应其原始版本、配置和环境。

测试覆盖模型初始化、前向与梯度、标准化和窗口等价、完整训练、checkpoint 恢复、模型包校验、新进程携带源码恢复，以及股票分批和覆盖检查。

本地保存的真实数据工程检查、资源测量和相关日志见 [完整归档](../../ARCHIVE.md)。这些记录不表示正式收益预测效果、官方评分复现、平台资源验收或成功提交已经完成。

训练与实验模块使用 Unix `resource`，完整训练建议在已准备固定依赖的 Linux 环境执行。实际 DAI、标签合同、官方评价和唯一 Notebook 需在平台完成验证。
