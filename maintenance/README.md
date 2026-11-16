# 归档维护记录

日期：2026 年 11 月 16 日。

上传脚本、发布回执与检查中间文件保存在 `ptop-publication-support-20261116.zip`，逐文件 SHA-256 及清理范围见 `preservation.json`；实际删除记录见 `cleanup.json`。

`branch-cleanup.json` 记录远端分支及归档标签。已删除的旧开发分支可以通过对应标签访问：

| 原分支 | 保留标签 |
| --- | --- |
| `codex/a-input-modules-84d8cc8` | `archive/branches/2026-11-16/a-input-modules` |
| `composition_module` | `archive/branches/2026-11-16/composition-module` |

保留完整归档分支、原 `main` 和 `codex/embed-qlib-source`。后者关联上游 [PR #4](https://github.com/starrrkittty/jinyicapital-2026-e2e/pull/4)，当前仍未合并。本地保留个人源码、集成源码、发布工作区、原始数据与历史备份；外部 WSL worktree 保留原位置。

`workspace-README.md` 与 `workspace-ARCHIVE.md` 是清理后本地工作区入口说明。`local-archive/` 中的历史快照保持原样。
