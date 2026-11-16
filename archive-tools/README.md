# 完整资料恢复

本仓库的 `project/` 和 `my-part/` 是两个使用入口。`local-archive/` 保留原工作区的普通文件，大型文件保存在同一仓库的 [完整归档 Release](https://github.com/Susurrium/jinyicapital-2026-e2e/releases/tag/full-archive-2026-11-16)。

下载此归档分支后，在仓库根目录执行：

```powershell
python archive-tools/restore.py --archive-root . --output restored-project
```

脚本需要 Python 3.12，使用标准库。输出目录必须尚不存在。脚本复制普通文件，按清单顺序下载和拼接大文件，并核对每个分片及最终文件的 SHA-256。下载使用公开的 GitHub Release 地址，需要可访问 GitHub。

恢复后，`restored-project/` 与原工作区资料目录结构一致，其中 `src/` 为个人模块，`work/repo-publication/` 为完整集成源码。Python 环境、Git 元数据及 Git 历史 bundle 不包含在归档中。

检查已有恢复目录时执行：

```powershell
python archive-tools/restore.py --archive-root . --verify restored-project
```

`FULL_ARCHIVE_MANIFEST.json` 记录每个原始文件及存放位置。单个大文件的附件按照 `assets` 数组的顺序拼接，恢复后再检查整文件指纹。历史文档中的本机绝对路径需要依据恢复位置调整。
