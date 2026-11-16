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

## 完整资料

`local-archive/` 按本地原始目录结构保存普通文件，包含原始 README 和归档说明、全部研究与数据文档、官方导出、真实数据统计和异常上下文、历史源码 ZIP、验证 XML、环境记录、PR 文本及辅助脚本。历史材料保持原文，状态与结论对应其原始日期和版本。

四个行情压缩包，以及 `work/local-data/first-member.feather` 和 `first-month.feather` 存于 [完整归档 Release](https://github.com/Susurrium/jinyicapital-2026-e2e/releases/tag/full-archive-2026-11-16)。大于 1 GiB 的文件按原始字节顺序分片；恢复时拼接并检查整文件 SHA-256。

赛事结束后，项目所有者确认举办方允许上传这些资料。排除范围为本机 Python 环境、Git 元数据、Git 历史 bundle、环境缓存及本次上传的暂存目录。

## 清单与恢复

- `FULL_ARCHIVE_MANIFEST.json`：原始项目资料逐文件路径、大小、SHA-256、仓库副本或 Release 附件的对应关系。
- `UPLOAD_MANIFEST.json`：当前归档分支所有文件的大小及 SHA-256，清单自身不参与自身指纹。
- `UPLOAD_VERIFICATION.json`：初次源码归档的验证记录。
- `FULL_UPLOAD_VERIFICATION.json`：补齐资料后的文件、原始快照和 Release 附件核验记录。

完整目录恢复命令及校验方式见 [恢复说明](archive-tools/README.md)。

## 维护记录

[maintenance/](maintenance/README.md) 保存上传后的工作区及分支清理记录，以及上传辅助脚本与核验记录的保全 ZIP。完整数据归档 Release 对应 `full-archive-2026-11-16` 标签；分支上的后续提交记录归档维护。
