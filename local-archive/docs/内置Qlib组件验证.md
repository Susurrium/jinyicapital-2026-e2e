# 内置 Qlib 组件验证

本页记录 2026 年 10 月 14 日早期内置组件快照的验收。后续完整训练集成、模型包版本和归档证据见[归档说明](../ARCHIVE.md)。下表原始记录的副本同时保存在 `reports/archive-20261116/`。

2026-10-14 在 Windows x64、Python 3.12.10、PyTorch 2.8.0 CPU 上验证。所需组件位于 `src/ptop/_vendor/qlib/`，原始提交、适配范围、SHA-256 和 MIT 许可随源码保存。

| 验证 | 结果 | 记录 |
| --- | --- | --- |
| 与真实原版 Qlib 对照 | 43 项通过；先核对原始文件哈希，再核对方法计算语句、模型初始化/前向/梯度/BN 状态、N0/N1/N2 与原 DataHandlerLP 的结果、采样及填充 | `work/repo-publication/work/qlib-equivalence.xml` |
| 独立环境完整本地测试 | 218 项通过；已确认该环境不存在 `qlib` 模块和 `pyqlib` 分发包，含独立进程重载 | `work/no-qlib-tests.xml` |
| 仓库运行测试 | 15 项通过；同一无 Qlib 环境，覆盖云端接口合成数据及全部候选模型的训练、JSON 保存与恢复 | `work/repo-publication/work/no-qlib-tests.xml` |
| 实际安装包 | 构建并安装纯 Python wheel，确认从安装目录导入；9 个候选模型均完成保存、重载与预测一致性检查 | `work/embedded-package-report.json` |

当时交付源码包为 `deliverables/ptop-source-20261014.zip`，包含 30 个文本文件、58,938 字节；打包时与对应源文件逐一比较一致，ZIP CRC 校验通过。SHA-256 为 `224eeb97dc63fc2b001bf0715064c03b06bd1801baa58cc49cfb8a1bd74b919c`。当前完整集成源码保存为 `deliverables/ptop-repository-20261116.zip`。训练和推理仍需正常安装 NumPy、pandas、PyArrow、PyTorch，`dai` 使用平台客户端。

常规使用和测试不安装 Qlib；`validation/test_qlib_equivalence.py` 是显式运行的专项对照验证，仅它需要原版固定提交。

模型权重名称、形状、初始化、标准化统计及窗口语义保持原方案。模型包 v2 记录内置组件版本，不再记录外部 `pyqlib` 依赖，与 v1 包不兼容。预处理 JSON 的统计语义和指纹格式保持一致。

这些验证使用合成数据，不代表比赛预测效果。真实 DAI、Linux、CUDA 和平台隔离评测尚未运行。本地数据问题继续暂停处理。
