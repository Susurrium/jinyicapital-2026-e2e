# 来源与许可

Qlib 固定提交：`54355232463878d2eebb91fe0ee5fa7fa1f5976c`。包内 `qlib-54355232463878d2eebb91fe0ee5fa7fa1f5976c.zip` 收录该提交完整的 `qlib/` 源码目录及构建元数据、README、LICENSE。每个源文件均与上游归档逐字节核对；上游归档的 SHA-256 与原工程 `uv.lock` 一致。上游归档、构建源码包的独立哈希及逐文件哈希见 `source-provenance.json`，MIT 许可见 `QLIB-LICENSE`。

直接复用 Qlib 的 GRUModel、ALSTMModel、Net、RobustZScoreNorm、ZScoreNorm、Fillna、StaticDataLoader、DataHandlerLP 和 TSDataSampler。源码归档没有 Git 元数据，构建版本显式设为 `0.0.0+git.<commit>`；该值是项目构建标识。

DeepLOB 按 [论文](https://arxiv.org/html/1808.03668)算法与团队声明的三档规格独立组织 PyTorch 标准算子。包括数值／观测双通道、三档空间卷积、same padding、Inception、时间共享 Dropout、LSTM 和收益回归。没有复制作者仓库代码。

联合线性 patch 参考 [PatchTST 论文](https://arxiv.org/html/2211.14730)的通道混合分块实验及作者提交 `204c21efe0b39603ad6e2ca640ef5896646ab1a9` 的投影形式，使用 `unfold` 和 `Linear` 独立实现；后接 GRU 和注意力。
