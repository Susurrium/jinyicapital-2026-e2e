# 进益资本杯 2026 端到端项目归档

归档日期：2026 年 11 月 16 日。仓库分为完整集成项目和 A 成员个人工作两部分。

| 目录 | 内容 | 入口 |
| --- | --- | --- |
| [project/](project/) | A/B/C 协作形成的完整集成代码：数据、模型、损失、训练、恢复与推理 | [项目说明](project/README.md) |
| [my-part/](my-part/) | A 成员的数据适配、预处理、窗口、输入编码、审计工具、参照模型及历史交接材料 | [个人部分说明](my-part/README.md) |
| [local-archive/](local-archive/) | 本地原始资料快照：完整文档、官方导出、数据分析、历史验证与辅助脚本 | [完整归档说明](ARCHIVE.md) |

两部分各自保留依赖声明、测试、配置和第三方许可。运行时进入对应目录安装依赖，避免两个同名 `ptop` 包互相覆盖。

完整项目来源于集成仓库提交 `101ad3c8716c550d7c3ae6f4fb2e4282a246b5a0`；个人部分来源于本地 A 模块归档。文件范围、完整性清单与验证说明见 [归档索引](ARCHIVE.md)。

本仓库保存源码、完整文档、股票映射、标签、数据分析和历史验证材料。大型行情与中间文件通过 [完整归档 Release](https://github.com/Susurrium/jinyicapital-2026-e2e/releases/tag/full-archive-2026-11-16) 提供。原始目录路径、SHA-256 和附件顺序见 `FULL_ARCHIVE_MANIFEST.json`，恢复方法见 [archive-tools/](archive-tools/README.md)。

赛事结束后，项目所有者确认举办方允许上传上述材料。本机 Python 环境、Git 元数据和 Git 历史 bundle 保留在本地。
