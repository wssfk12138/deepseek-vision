<#
.SYNOPSIS
扫描版 PDF 批量 OCR 转文本（Windows 便捷入口）
.EXAMPLE
scripts\batch_ocr.ps1 "C:\资料\扫描书.pdf" --out "C:\资料\OCR结果"
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'batch_ocr.py') @args
exit $LASTEXITCODE
