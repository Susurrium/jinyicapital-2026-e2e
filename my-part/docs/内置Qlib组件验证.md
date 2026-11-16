# 内置 Qlib 组件与验证

组件来自 Microsoft Qlib 固定提交 `54355232463878d2eebb91fe0ee5fa7fa1f5976c`。模型、标准化、填空、采样和索引工具位于 `src/ptop/_vendor/qlib/`，MIT 许可及具体适配见该目录的 `LICENSE` 和 `SOURCE.md`。

常规使用和测试无需安装外部 Qlib。专项对照位于 `validation/test_qlib_equivalence.py`，需要原版固定提交。历史独立环境 218 项测试结果见 [no-qlib-tests.xml](../reports/no-qlib-tests.xml)，完整集成最终原版对照记录见 [44 项专项记录](../../project/docs/qlib-reference-tests.xml)。

本目录保存 v2 模型包协议；完整集成项目保存 v3/v4 协议。历史源码包 `deliverables/ptop-source-20261014.zip` 对应其打包时版本，当前集成实现见 [project/](../../project/README.md)。
