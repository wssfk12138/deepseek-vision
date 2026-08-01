<#
.SYNOPSIS
deepseek-vision 插件安装脚本（Windows）
安装官方 64 位 uv 与 mcp-vision，并生成 .env 配置文件。
#>
$ErrorActionPreference = 'Stop'

$pluginRoot = Split-Path -Parent $PSScriptRoot
$uvRoot = Join-Path $env:USERPROFILE '.local\bin'
$uvExe = Join-Path $uvRoot 'uv.exe'

Write-Host '=== deepseek-vision 安装脚本 ===' -ForegroundColor Cyan

# 1. 检查 / 安装 uv
if (-not (Test-Path -LiteralPath $uvExe)) {
    Write-Host '[1/5] 未检测到官方 uv，正在安装（优先官方安装器，失败则直接下载二进制）...' -ForegroundColor Yellow
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Host '官方安装器执行失败，改用二进制包...' -ForegroundColor Yellow
    }
    if (-not (Test-Path -LiteralPath $uvExe)) {
        $uvZip = Join-Path $env:TEMP 'uv-x86_64-pc-windows-msvc.zip'
        Invoke-WebRequest `
            -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' `
            -OutFile $uvZip
        Expand-Archive -LiteralPath $uvZip -DestinationPath $uvRoot -Force
    }
} else {
    Write-Host '[1/5] 已检测到官方 uv。' -ForegroundColor Green
}

# 确保 uv 所在目录在 PATH 中（Codex 需要能找到 uvx）
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$uvRoot*") {
    [Environment]::SetEnvironmentVariable('Path', "$uvRoot;$userPath", 'User')
    Write-Host '已将 ~\.local\bin 加入用户 PATH（新开的终端 / Codex 会话生效）。' -ForegroundColor Green
}
$env:PATH = "$uvRoot;$env:PATH"

# 2. 预装 mcp-vision（Python >= 3.11）
#    使用 uv 管理的 64 位 Python 3.12，避免系统 Python 位宽导致依赖编译失败；
#    同时锁定 mcp<2，兼容 mcp-vision 当前版本的 FastMCP 导入路径。
Write-Host '[2/5] 准备 Python 3.12 并安装 mcp-vision（首次运行可能需下载）...' -ForegroundColor Yellow
Get-Process -Name 'mcp-vision' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
& $uvExe python install 3.12
& $uvExe tool install --force --python 3.12 mcp-vision --with 'mcp[cli]<2'
if ($LASTEXITCODE -ne 0) { throw 'mcp-vision 安装失败，请检查上方错误信息。' }

# 3. 批量 OCR 虚拟环境（PDF 渲染 + API 调用）
Write-Host '[3/5] 准备批量 OCR 环境（pypdfium2 / httpx / pillow）...' -ForegroundColor Yellow
$venvPython = Join-Path $pluginRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $uvExe venv (Join-Path $pluginRoot '.venv') --python 3.12
    if ($LASTEXITCODE -ne 0) { throw '批量 OCR 虚拟环境创建失败。' }
}
& $uvExe pip install --python (Join-Path $pluginRoot '.venv\Scripts\python.exe') pypdfium2 httpx pillow python-dotenv
if ($LASTEXITCODE -ne 0) { throw '批量 OCR 环境安装失败，请检查上方错误信息。' }

# 4. 生成 .env
$envFile = Join-Path $pluginRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $pluginRoot 'assets\env.example') -Destination $envFile
    Write-Host '[4/5] 已生成 .env，请打开它并填入视觉 API Key。' -ForegroundColor Green
} else {
    Write-Host '[4/5] .env 已存在，跳过创建。' -ForegroundColor Green
}

# 5. 冒烟测试
Write-Host '[5/5] 运行冒烟测试...' -ForegroundColor Yellow
python (Join-Path $PSScriptRoot 'smoke_test.py')
if ($LASTEXITCODE -ne 0) { throw '冒烟测试未通过，请检查视觉服务配置。' }

Write-Host ''
Write-Host '下一步：' -ForegroundColor Cyan
Write-Host "  1. 编辑 $envFile，至少填入 SILICONFLOW_API_KEY（或改用其他 Provider）"
Write-Host '  2. 在 Codex 中重新加载插件或重启会话'
Write-Host '  3. 再次运行本脚本可复验；也可单独运行 python scripts\smoke_test.py'
