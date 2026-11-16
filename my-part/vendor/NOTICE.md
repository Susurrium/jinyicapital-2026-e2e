# 第三方来源与打包

Qlib 使用 Microsoft 仓库提交 `54355232463878d2eebb91fe0ee5fa7fa1f5976c`。`GRUModel`、`ALSTMModel`、`Net`、`RobustZScoreNorm`、`ZScoreNorm`、`Fillna`、`TSDataSampler` 及索引工具以源码保存在 `src/ptop/_vendor/qlib/`。MIT 许可与来源说明分别为该目录的 `LICENSE`、`SOURCE.md`；随源码和安装包保留。当前依赖由根目录 `uv.lock` 管理。

DeepLOB 使用 [论文](https://arxiv.org/html/1808.03668)算法描述与方案声明的三档规格，由 PyTorch 标准算子独立实现。未复制作者仓库代码。包含两通道观测输入、三档空间卷积、same padding、Inception、时间共享 Dropout、LSTM 与收益回归适配；初始化与 Keras 门映射按方案声明。测试不代表跨 TensorFlow 环境逐位复现。

联合线性 patch 参考 [PatchTST 论文](https://arxiv.org/html/2211.14730)通道混合消融及作者提交 `204c21efe0b39603ad6e2ca640ef5896646ab1a9` 的线性投影形式，使用 PyTorch `unfold` 和 `Linear` 独立组织。当前分支接 GRU 与注意力，未包含 PatchTST 的 Transformer 主干。
