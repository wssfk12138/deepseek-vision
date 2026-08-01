<#
.SYNOPSIS
图片表格提取（Windows 便捷入口）
.EXAMPLE
scripts\table_extract.ps1 --pdf "C:\扫描书.pdf" --pages "5,26,56" --out "C:\tables"
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'table_extract.py') @args
exit $LASTEXITCODE
