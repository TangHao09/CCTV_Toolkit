# AV3A转码工具 - 一键打包脚本
# 用法: 在此目录打开 PowerShell 后执行  .\build.ps1
# 可选参数:
#   -FfmpegDir "D:\path\to\ffmpeg"   指定内置的 ffmpeg 目录
#   -PythonPath "C:\...\python.exe"  指定 Python 解释器（默认自动查找）

param(
    [string]$FfmpegDir = "C:\Users\13568\Downloads\ffmpeg-av3a",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

# ---- 查找 Python ----
$python = $null
$usePyLauncher = $false
if ($PythonPath -and (Test-Path $PythonPath)) {
    $python = $PythonPath
} else {
    foreach ($cand in @("python", "python3", "py")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($cand -eq "py") { $usePyLauncher = $true } else { $python = $cand }
            break
        }
    }
}
if (-not $python -and -not $usePyLauncher) {
    throw "找不到 Python，请安装 Python 3.10+（勾选 Add to PATH），或用 -PythonPath 指定 python.exe"
}
if ($usePyLauncher) { Write-Host "使用 Python: py -3" -ForegroundColor Cyan }
else { Write-Host "使用 Python: $python" -ForegroundColor Cyan }

function Invoke-Py {
    param([string[]]$PyArgs)
    if ($usePyLauncher) { & py -3 @PyArgs } else { & $python @PyArgs }
}

Write-Host "== 检查依赖 ==" -ForegroundColor Cyan
Invoke-Py @("-m", "pip", "install", "--quiet", "-r", "requirements.txt") 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip 安装失败（可能已安装或无网络），继续尝试打包..." -ForegroundColor Yellow
}

if (-not (Test-Path (Join-Path $FfmpegDir "ffmpeg.exe"))) {
    throw "ffmpeg 目录中找不到 ffmpeg.exe: $FfmpegDir（可用 -FfmpegDir 指定）"
}

Write-Host "== 收集内置文件 ==" -ForegroundColor Cyan
# 排除 ffplay.exe（工具用不到，可省约 22MB）
$adds = Get-ChildItem $FfmpegDir |
        Where-Object { $_.Name -ne "ffplay.exe" -and -not $_.PSIsContainer } |
        ForEach-Object { "--add-data", ($_.FullName + ";ffmpeg") }

Write-Host "== PyInstaller 打包 ==" -ForegroundColor Cyan
$pyArgs = @(
    "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
    "--runtime-tmpdir", ".",
    "--collect-all", "ttkbootstrap",
    "--name", "AV3A_Converter",
    "--clean"
) + $adds + @("av3a2aac-ac3.pyw")

Invoke-Py $pyArgs

if ($LASTEXITCODE -ne 0) { throw "打包失败" }

$exe = Join-Path $PSScriptRoot "dist\AV3A_Converter.exe"
Write-Host "== 完成: $exe ==" -ForegroundColor Green
Get-Item $exe | ForEach-Object { "大小: {0:N1} MB" -f ($_.Length / 1MB) }
