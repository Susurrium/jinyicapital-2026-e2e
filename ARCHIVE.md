# 归档索引

归档日期：2026 年 11 月 16 日。

## 完整项目

`project/` 保存集成仓库 `101ad3c8716c550d7c3ae6f4fb2e4282a246b5a0` 的源码、测试、配置、研究与协作文档。A 的九种固定候选和 B 的四种可配置主干共用 raw25 输入，训练入口为 `python -m ptop.train`。固定候选模型包格式为 v3，参数化及携带源码模型包格式为 v4。

安装和运行应先进入 `project/`，具体说明见 [项目 README](project/README.md)。训练模块依赖 Unix `resource`；历史集成训练验收主要在 Linux 环境执行。

## A 成员个人部分

`my-part/` 保存独立 A 模块的全部源码、测试、工具、验证入口、依赖锁定文件、官方示范脚本、方案与规则文档、第三方来源和历史交接包。该独立模块使用 v2 模型包。

`my-part/handoff/` 为 2026-10-11 的交接源材料；其完整 ZIP 保存在 `my-part/deliverables/`。`ptop-source-20261014.zip` 为当时早期内置组件快照。当前完整集成代码以 `project/` 为准。

## 验证材料

- `my-part/reports/test-results.xml`：历史合成代码检查，154 项通过。
- `my-part/reports/no-qlib-tests.xml`：历史独立环境检查，218 项通过。
- `my-part/reports/synthetic-validation.json`：合成数据联合梯度、独立进程恢复及覆盖检查。
- `project/docs/qlib-reference-tests.xml`：历史固定提交 Qlib 对照，44 项通过。

历史记录对应其原始版本和环境。此次上传检查源码复制一致性、Python 语法、文件清单及归档完整性，并在 Windows CPU 环境运行个人模块的合成联合梯度、独立进程恢复和输出覆盖检查。结果见根目录 `UPLOAD_VERIFICATION.json`。金融预测效果、真实 DAI、正式标签合同、官方评分和平台提交均需独立验证。

## 文件范围

真实数据、非公开数据字典、标签与映射、受限统计和异常明细、真实数据分析报告、训练权重、凭据及运行环境保留在本地。Git 历史 bundle 和包含受限文档的历史整包也保留在本地。公开工程文档描述代码、接口和验证范围。

`UPLOAD_MANIFEST.json` 记录本次上传文件的字节数及 SHA-256，便于下载后检查；清单自身不参与自身指纹。
