<#
.SYNOPSIS
古籍影印区域检测（Windows 便捷入口）
.EXAMPLE
scripts\detect_ancient.ps1 --pdf "C:\扫描书.pdf" --pages "11-13,20-22" --out "C:\ancient"
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'detect_ancient.py') @args
exit $LASTEXITCODE
