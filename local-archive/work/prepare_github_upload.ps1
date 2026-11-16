$ErrorActionPreference = 'Stop'
$taskRoot = 'E:\PtoP'
$taskSource = Join-Path $taskRoot 'work\repo-publication'
$taskUpload = Join-Path $taskRoot 'work\github-upload'
if (Test-Path -LiteralPath $taskUpload) { throw '上传暂存目录已存在，拒绝覆盖' }
New-Item -ItemType Directory -Path (Join-Path $taskUpload 'project'), (Join-Path $taskUpload 'my-part') | Out-Null

$taskFiles = & git -C $taskSource -c core.quotepath=false ls-files
if ($LASTEXITCODE -ne 0) { throw '读取集成仓库文件清单失败' }
foreach ($taskRelative in $taskFiles) {
    if ($taskRelative -in @('.gitignore','.gitattributes','docs/b_data_reference.md','docs/b_local_experiments.md','docs/b_verification.md')) { continue }
    $taskDestination = Join-Path $taskUpload ('project\' + $taskRelative)
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskSource $taskRelative) -Destination $taskDestination
}

$taskMyPart = Join-Path $taskUpload 'my-part'
foreach ($taskDirectory in @('src','tests','tools','validation','handoff','vendor')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot $taskDirectory) -Destination (Join-Path $taskMyPart $taskDirectory) -Recurse
}
foreach ($taskFilename in @('pyproject.toml','uv.lock','Transformer_modelsave_train.py','Transformer_modelsave_predict.py','进益资本杯_端到端赛道说明.md')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot $taskFilename) -Destination (Join-Path $taskMyPart $taskFilename)
}
New-Item -ItemType Directory -Path (Join-Path $taskMyPart 'docs'),(Join-Path $taskMyPart 'reports'),(Join-Path $taskMyPart 'deliverables') | Out-Null
foreach ($taskFilename in @('A成员数据与输入编码方案.md','比赛规则与流程.md')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot ('docs\' + $taskFilename)) -Destination (Join-Path $taskMyPart ('docs\' + $taskFilename))
}
foreach ($taskFilename in @('test-results.xml','synthetic-validation.json')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot ('reports\' + $taskFilename)) -Destination (Join-Path $taskMyPart ('reports\' + $taskFilename))
}
Copy-Item -LiteralPath (Join-Path $taskRoot 'reports\archive-20261116\root-work\no-qlib-tests.xml') -Destination (Join-Path $taskMyPart 'reports\no-qlib-tests.xml')
Copy-Item -LiteralPath (Join-Path $taskRoot 'reports\archive-20261116\integrated-work\pr-reference-final.xml') -Destination (Join-Path $taskUpload 'project\docs\qlib-reference-tests.xml')
foreach ($taskFilename in @('ptop-A-to-BC-20261011.zip','ptop-A-to-BC-20261011.sha256','ptop-A-to-BC-20261011.check.json','ptop-source-20261014.zip')) {
    Copy-Item -LiteralPath (Join-Path $taskRoot ('deliverables\' + $taskFilename)) -Destination (Join-Path $taskMyPart ('deliverables\' + $taskFilename))
}
Get-ChildItem -LiteralPath $taskUpload -File -Recurse | Measure-Object -Property Length -Sum | Select-Object Count,Sum | ConvertTo-Json
