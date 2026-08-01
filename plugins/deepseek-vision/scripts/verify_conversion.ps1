<#
.SYNOPSIS
DOCX 转换校验（Windows 便捷入口）
.EXAMPLE
scripts\verify_conversion.ps1 --pdf "C:\原稿.pdf" --ocr-dir "C:\OCR结果" --docx "C:\转换.docx"
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'verify_conversion.py') @args
exit $LASTEXITCODE
