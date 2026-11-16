param([string]$Python = '3.12')

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
New-Item -ItemType Directory -Path 'work/python-temp', 'work/uv-cache' -Force | Out-Null
$env:UV_CACHE_DIR = Join-Path $taskRoot 'work/uv-cache'
$env:TEMP = Join-Path $taskRoot 'work/python-temp'
$env:TMP = $env:TEMP
uv sync --locked --extra test --python $Python --no-python-downloads
if ($LASTEXITCODE -ne 0) { throw '依赖环境安装失败' }
& (Join-Path $taskRoot '.venv/Scripts/python.exe') -m pytest --junitxml=work/validation.xml -q
if ($LASTEXITCODE -ne 0) { throw '项目测试失败' }
