<#
.SYNOPSIS
国际音标二次核对（Windows 便捷入口）
.EXAMPLE
scripts\ipa_check.ps1 --pdf "C:\扫描书.pdf" --ocr-dir "C:\OCR结果" --out "C:\ipa报告"
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'ipa_check.py') @args
exit $LASTEXITCODE
