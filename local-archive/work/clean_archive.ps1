param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskRepository = Join-Path $taskRoot 'work\repo-publication'
$taskReport = Join-Path $taskRoot 'reports\archive-20261116'
$taskInventory = Get-Content -Raw -LiteralPath (Join-Path $taskReport 'inventory-before.json') | ConvertFrom-Json
$taskRelativePaths = @('work\deps', 'work\uv-cache', 'work\venv-no-qlib',
    'work\handoff-staging', 'work\handoff-unpacked', 'work\python-temp',
    'work\repo-publication\work\linux-cache', 'work\repo-publication\work\linux-python',
    'work\repo-publication\work\linux-tools', 'work\repo-publication\work\linux-venv',
    'work\repo-publication\work\package-check', 'work\repo-publication\work\package-installed',
    'work\repo-publication\build')

foreach ($taskParent in @((Join-Path $taskRoot 'work'), (Join-Path $taskRepository 'work'))) {
    $taskRelativePaths += Get-ChildItem -LiteralPath $taskParent -Directory |
        Where-Object { $_.Name -like 'pytest-*' } |
        ForEach-Object { [IO.Path]::GetRelativePath($taskRoot, $_.FullName) }
}

# 只枚举源码和检查入口，避免扫描保留的原始数据与开发环境。
foreach ($taskSourceRoot in @('src','tests','tools','validation','handoff',
    'work\repo-publication\src','work\repo-publication\tests',
    'work\repo-publication\examples','work\repo-publication\validation')) {
    $taskRelativePaths += Get-ChildItem -LiteralPath (Join-Path $taskRoot $taskSourceRoot) -Directory -Recurse |
        Where-Object { $_.Name -eq '__pycache__' -or $_.Name -like '*.egg-info' } |
        ForEach-Object { [IO.Path]::GetRelativePath($taskRoot, $_.FullName) }
}

$taskTargets = @($taskRelativePaths | Sort-Object -Unique | ForEach-Object {
    $taskAbsolute = [IO.Path]::GetFullPath((Join-Path $taskRoot $_))
    if (-not $taskAbsolute.StartsWith($taskRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "清理路径越出工作区：$taskAbsolute"
    }
    if ($taskAbsolute -eq $taskRepository -or $taskAbsolute -eq (Join-Path $taskRoot 'work')) {
        throw "禁止清理实际仓库或整个 work 目录：$taskAbsolute"
    }
    if (Test-Path -LiteralPath $taskAbsolute) {
        $taskItem = Get-Item -Force -LiteralPath $taskAbsolute
        if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "清理目标本身是重解析点：$taskAbsolute"
        }
        if (Test-Path -LiteralPath (Join-Path $taskAbsolute '.git')) {
            throw "清理目标内包含仓库：$taskAbsolute"
        }
        [pscustomobject]@{ Path = $taskAbsolute; Relative = [IO.Path]::GetRelativePath($taskRoot, $taskAbsolute).Replace('\','/') }
    }
})

if (-not $Apply) {
    $taskTargets | Select-Object Relative | Format-Table -AutoSize
    exit 0
}

if (Test-Path -LiteralPath (Join-Path $taskReport 'cleanup.json')) {
    throw '清理日志已存在，禁止重复覆盖'
}
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'deliverables\ptop-git-before-archive-20261116.bundle'))) {
    throw '缺少整理前 Git 历史备份'
}

$taskLog = [Collections.Generic.List[object]]::new()
$taskBytes = 0L
foreach ($taskTarget in $taskTargets) {
    $taskMeasured = @($taskInventory | Where-Object { $_.path -eq $taskTarget.Relative })
    $taskEntry = [ordered]@{ path = $taskTarget.Relative; status = 'pending'; logical_bytes = $null }
    if ($taskMeasured.Count -eq 1) {
        $taskEntry.logical_bytes = $taskMeasured[0].bytes
    }
    try {
        # Remove-Item 使用当前 PowerShell 原生删除语义，不跨 shell，也不跟随链接目标。
        Remove-Item -LiteralPath $taskTarget.Path -Recurse -Force
        if (Test-Path -LiteralPath $taskTarget.Path) {
            throw "清理目标仍存在：$($taskTarget.Path)"
        }
        $taskEntry.status = 'removed'
        if ($null -ne $taskEntry.logical_bytes) { $taskBytes += $taskEntry.logical_bytes }
        Write-Output "已清理 $($taskTarget.Relative)"
    } catch {
        $taskEntry.status = 'failed'
        $taskEntry.error = $_.Exception.Message
        throw
    } finally {
        $taskLog.Add($taskEntry)
        [ordered]@{ date = '2026-11-16'; measured_logical_bytes_removed = $taskBytes; entries = $taskLog } |
            ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskReport 'cleanup.json') -Encoding utf8
    }
}
