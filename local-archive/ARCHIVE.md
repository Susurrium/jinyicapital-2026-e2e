# PtoP 本地归档说明

归档日期：2026 年 11 月 16 日。此目录保存项目源码、历史交接包、真实数据及本地验收资料。项目停留在工程集成完成、正式数据合同和平台验收尚待完成的状态。

## 目录与版本

| 路径 | 保留内容 |
| --- | --- |
| `work/repo-publication/` | 实际 Git 仓库；A/B 集成代码、损失函数、训练、恢复与推理 |
| 根目录 `src/`、`tests/`、`tools/`、`validation/` | A 模块独立开发快照，使用根目录 `pyproject.toml` 和 `uv.lock` |
| `docs/` | A 方案、规则资料、本地数据审计和开发记录 |
| `handoff/` | 2026-10-11 交接材料，适用当日外部 Qlib 版本 |
| `deliverables/` | 历史交付包及本次 Git 历史备份、集成源码快照 |
| `reports/` | 原始审计报告及本次归档保全资料 |
| `data/` | 四个原始行情压缩包和官方导出，保留原文件 |
| `vendor/` | 历史 Qlib wheel、来源指纹及许可证 |
| `.venv/` | 根目录 Python 3.12 开发环境 |
| `work/local_archive/`、`work/local-preflight/`、`work/negative-cause/` | 异常明细、诊断统计和分析上下文 |

`work/` 包含实际仓库和独立验证证据。归档整个项目时必须包含该目录中保留的内容；根目录 `.gitignore` 中的 `/work/` 只控制 Git 忽略，不代表整个目录都可以删除。

根目录模型包格式为 v2；集成仓库固定候选使用 v3，参数化模型及携带源码使用 v4。各阶段的源码、依赖和模型包应配套使用。2026-10-11 的首轮配置为 Adam/MSE；集成训练默认采用 AdamW/Huber，具体配置以集成仓库代码为准。

## Git 保存方式

集成前的工作提交为 `6f365938bdad7d2f3154377bafb91bde6115bafc`。本次文档整理单独提交，归档分支为 `archive/2026-11-16`，最终状态以该分支及同名 tag 为准。

`deliverables/ptop-git-before-archive-20261116.bundle` 保存整理前的全部 refs，包括旧本地 main。该 main 已包含在集成分支的历史中。`deliverables/ptop-repository-20261116.bundle` 保存整理后的全部 refs；同名 ZIP 保存该 tag 对应的完整受版本控制文件。

远端跟踪引用保留本机已有状态，本次未访问 GitHub、推送、合并或删除远端分支。注册的外部 WSL worktree 保留原位置和状态，清理范围限制在 `E:/PtoP/` 内。Git bundle 可在新目录通过 `git clone <bundle路径> <新目录>` 恢复独立仓库，原有本地文件不参与该恢复操作。

## 数据和平台状态

- 1 分钟原始归档的历史审计覆盖 302,545,707 行、60 个月；8,084 个未知负委托笔数仍待来源解释或修正。本次未重写或重新扫描原始归档。
- 官方导出位于 `data/official/official_data_export_20261011_221817/`，包括 1,866 条股票映射、2023 年 8 月截面和标签，各 184,000 行。
- 截面中的 `302132.SZ` 缺少映射和 184 条标签；标签另有 `000852.SH` 的 184 条记录。标签存在 40 个缺失收益值，无无穷值；有效性及键集合应分别处理。
- 正式完整采样集合、分钟网格、可见性、标签支持区间、LabelSpec 和训练授权日期仍需确认。集成仓库的正式配置保留这些必要输入的空值。
- 集成训练模块直接依赖 `resource`；根目录 Windows 环境未提供该模块。Linux 验证记录见集成仓库文档。
- 本地没有完成正式样本外收益训练、官方最终评价、唯一提交 Notebook 或成功平台提交的可核对证据。

真实数据、异常上下文及受限派生文件保留在本地。集成源码 ZIP 与 Git bundle 的内容范围为已受版本控制的项目文件。

## 验证证据

`reports/archive-20261116/root-work/` 和 `integrated-work/` 逐文件保留原始 XML、JSON、交付回执与 PR 文本，包含早期失败记录。

| 证据 | 可核对结果 |
| --- | --- |
| `root-work/no-qlib-tests.xml` | 根目录 218 项通过 |
| `integrated-work/pr-reference-final.xml` | 原版 Qlib 专项对照 44 项通过 |
| `integrated-work/pr-linux-integrated-final.xml` | Linux 模型包专项 13 项通过 |
| 集成仓库 `docs/b_verification.md` | 文档记载完整 CPU 281 项通过、16 项 CUDA 跳过；完整日志在原验证环境 |

本次归档检查覆盖文件指纹、ZIP CRC、Git bundle、自包含 Git 历史完整性和文档链接。本次不重新执行模型测试或金融性能实验。

## 清理与核验资料

`reports/archive-20261116/inventory-before.json` 保存清理前目录统计；`cleanup.json` 逐项记录已删除的可再生产物及字节数。清理范围为依赖缓存、额外验证环境、pytest 临时目录、重复解包目录、构建目录和 Python 字节码。

原始行情、官方导出、源码、许可证、历史交付包、独立诊断资料、失败及成功验证记录均保留。`manifest.json` 记录保留资料的 SHA-256；原始大数据压缩包记录大小与修改时间，历史全量 SHA-256 仍见原审计报告。`verification.json` 记录本次最终检查结果。
