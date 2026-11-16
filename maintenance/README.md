# 归档维护记录

日期：2026 年 11 月 16 日。

上传脚本、发布回执与检查中间文件保存在 `ptop-publication-support-20261116.zip`，逐文件 SHA-256 及清理范围见 `preservation.json`；实际删除记录见 `cleanup.json`。

`branch-cleanup.json` 记录远端分支及归档标签。已删除的旧开发分支可以通过对应标签访问：

| 原分支 | 保留标签 |
| --- | --- |
| `codex/a-input-modules-84d8cc8` | `archive/branches/2026-11-16/a-input-modules` |
| `composition_module` | `archive/branches/2026-11-16/composition-module` |

当前完整归档入口为 `main`，沿用 `project/`、`my-part/` 和 `local-archive/` 目录。原 `main`、`codex/embed-qlib-source` 与完整归档分支的提交历史通过合并提交保留；完整归档分支合并后删除，其合并前状态保存在 `archive/branches/2026-11-16/full-project` 标签。

`codex/embed-qlib-source` 关联上游 [PR #4](https://github.com/starrrkittty/jinyicapital-2026-e2e/pull/4)，在该 PR 未合并期间保留。上游仓库保持原状态。本地保留个人源码、集成源码、发布工作区、原始数据与历史备份；外部 WSL worktree 保留原位置。

`branch-merge-before.json` 保存合并前的分支、源码核验及 Release 附件指纹。`branch-cleanup.json` 记录较早一次清理时的状态。完整数据 Release 及其标签继续对应原发布提交。

`workspace-README.md` 与 `workspace-ARCHIVE.md` 是清理后本地工作区入口说明。`local-archive/` 中的历史快照保持原样。
