<#
.SYNOPSIS
一键打包插件用于分享：自动剔除 .env（API 密钥）、.venv、images（剪贴板图片）等敏感/本地内容。
.EXAMPLE
scripts\package_share.ps1
scripts\package_share.ps1 -Out "C:\Users\Me\Desktop\deepseek-vision.zip" -Version 1.1.0
#>
param(
    [string]$Out = "",
    [string]$Version = "1.1.0"
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot
$tempBase = [System.IO.Path]::GetFullPath($env:TEMP)
$staging = Join-Path $tempBase ('dsv-share-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
    # 1. 复制插件文件，排除敏感/本地内容
    Get-ChildItem -LiteralPath $pluginRoot -Force |
        Where-Object { $_.Name -notin @('.env', '.venv', 'images', '__pycache__') } |
        Copy-Item -Destination $staging -Recurse -Force

    # 2. 清理可能的残留备份/缓存
    Get-ChildItem -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.orig\.|\.bak$' -or $_.Name -eq '__pycache__' } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    # 3. 将版本号规范为发布版本（去掉本地 cachebuster）
    $manifestPath = Join-Path $staging '.codex-plugin\plugin.json'
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $manifest.version = $Version
    $json = $manifest | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($manifestPath, $json, (New-Object System.Text.UTF8Encoding($false)))

    # 4. 生成压缩包
    if (-not $Out) {
        $Out = Join-Path (Split-Path -Parent $pluginRoot) "deepseek-vision-shareable-v$Version.zip"
    }
    $outFull = [System.IO.Path]::GetFullPath($Out)
    $outDir = Split-Path -Parent $outFull
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    if (Test-Path -LiteralPath $outFull) {
        Remove-Item -LiteralPath $outFull -Force
    }
    Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $outFull

    # 5. 校验压缩包中不含敏感文件
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($outFull)
    try {
        $entries = @($zip.Entries | ForEach-Object { $_.FullName })
    } finally {
        $zip.Dispose()
    }
    $leaks = $entries | Where-Object { $_ -match '\.env$|\.venv/|images/' }
    if ($leaks) {
        throw "压缩包包含敏感内容，已中止: $($leaks -join ', ')"
    }

    Write-Host "分享包已生成: $outFull" -ForegroundColor Green
    Write-Host "包含文件数: $($entries.Count)，敏感内容: 无"
    Write-Host ""
    Write-Host "接收方安装步骤："
    Write-Host "  1. 解压到 %USERPROFILE%\plugins\deepseek-vision"
    Write-Host "  2. 运行 scripts\setup.ps1（自动装依赖并生成 .env）"
    Write-Host "  3. 在 .env 填入自己的 SILICONFLOW_API_KEY"
    Write-Host "  4. 重启 Codex 后从个人市场安装 deepseek-vision"
} finally {
    # 仅删除 $tempBase 下自己创建的临时目录
    $resolved = [System.IO.Path]::GetFullPath($staging)
    if ($resolved.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolved)) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
