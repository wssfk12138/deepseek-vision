<#
.SYNOPSIS
DOCX 视觉渲染检查（Windows 便捷入口）：LibreOffice 后台渲染 + 视觉模型质检
.EXAMPLE
scripts\render_check.ps1 --docx "C:\文档.docx" --check-pages 1,2,5
#>
$ErrorActionPreference = 'Stop'
$venvPy = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    throw '未找到 .venv，请先运行 scripts\setup.ps1 完成环境安装。'
}
& $venvPy (Join-Path $PSScriptRoot 'render_check.py') @args
exit $LASTEXITCODE
