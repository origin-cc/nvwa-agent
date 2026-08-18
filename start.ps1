<#
========================================================
  NvwaAgent 一键启动脚本（v0.1-alpha）
  - 后端：FastAPI（端口 8000，依赖 backend/.deps，conda nvwa 环境）
  - 前端：Vite dev server（端口 5173）
  - 端口已被占用时自动跳过对应服务；后端就绪后自动打开浏览器
  - 关停：直接关闭弹出的两个命令行窗口即可
  用法：
    powershell -ExecutionPolicy Bypass -File .\start.ps1
    powershell -ExecutionPolicy Bypass -File .\start.ps1 -SkipInstall   # 跳过 npm install
========================================================
#>
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$Root        = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$BackendPort  = 8000
$FrontendPort = 5173

function Test-PortListen([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Find-Python {
    $candidates = @(
        'python',
        (Join-Path $env:USERPROFILE 'miniconda3\envs\nvwa\python.exe'),
        'D:\Downloan\workdownloan\miniconda3\envs\nvwa\python.exe'
    )
    foreach ($c in $candidates) {
        if (Get-Command $c -ErrorAction SilentlyContinue) { return $c }
    }
    throw '未找到 Python（nvwa conda 环境），请先 "conda activate nvwa" 后重试，或在脚本 Find-Python 中补充 python 路径'
}

# ---------------- [1/3] 前端依赖 ----------------
Write-Host ''
Write-Host '[1/3] 检查前端依赖' -ForegroundColor Cyan
if (Test-Path (Join-Path $FrontendDir 'node_modules')) {
    Write-Host '  node_modules 已存在，跳过安装' -ForegroundColor Green
}
elseif ($SkipInstall) {
    Write-Host '  -SkipInstall 已指定，跳过 npm install（注意：node_modules 不存在将无法启动前端）' -ForegroundColor Yellow
}
else {
    Write-Host '  安装前端依赖 npm install ...' -ForegroundColor Cyan
    Push-Location $FrontendDir
    npm install
    $ok = $LASTEXITCODE
    Pop-Location
    if ($ok -ne 0) { throw 'npm install 失败，请检查前端依赖（node_modules 或网络）' }
    Write-Host '  npm install 完成' -ForegroundColor Green
}

# ---------------- [2/3] 后端 ----------------
Write-Host ''
Write-Host '[2/3] 启动后端' -ForegroundColor Cyan
if (Test-PortListen $BackendPort) {
    Write-Host "  端口 $BackendPort 已被占用，跳过后端启动（如为本项目旧进程可直接复用）" -ForegroundColor Yellow
}
else {
    $python = Find-Python
    Write-Host "  使用 Python: $python" -ForegroundColor Gray
    $backendScript = "`$env:PYTHONPATH='$BackendDir\.deps'; " +
                     "cd '$BackendDir'; " +
                     "& '$python' -m uvicorn nvwa_agent.app:create_app --factory --host 127.0.0.1 --port $BackendPort"
    Start-Process powershell -ArgumentList @('-NoExit', '-Command', $backendScript) -WorkingDirectory $BackendDir
    Write-Host "  后端启动中（新窗口），等待端口 $BackendPort 就绪 ..." -ForegroundColor Gray

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/v1/system/config" -UseBasicParsing -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        }
        catch { }
    }
    if (-not $ready) { throw '后端 60 秒内未就绪，请查看后端窗口日志' }
    Write-Host '  后端已就绪' -ForegroundColor Green
}

# ---------------- [3/3] 前端 ----------------
Write-Host ''
Write-Host '[3/3] 启动前端' -ForegroundColor Cyan
if (Test-PortListen $FrontendPort) {
    Write-Host "  端口 $FrontendPort 已被占用，跳过前端启动" -ForegroundColor Yellow
}
else {
    if (-not (Test-Path (Join-Path $FrontendDir 'node_modules'))) {
        throw 'frontend/node_modules 不存在，请先安装依赖（不带 -SkipInstall 重跑）'
    }
    $frontendScript = "cd '$FrontendDir'; npm run dev"
    Start-Process powershell -ArgumentList @('-NoExit', '-Command', $frontendScript) -WorkingDirectory $FrontendDir
    Write-Host '  前端启动中（新窗口）...' -ForegroundColor Gray
}

# ---------------- 打开浏览器 ----------------
Write-Host ''
Write-Host '打开浏览器 http://localhost:5173 ...' -ForegroundColor Cyan
Start-Sleep -Seconds 3
Start-Process "http://localhost:$FrontendPort"
Write-Host ''
Write-Host 'NvwaAgent 已启动！关停方式：关闭弹出的后端/前端命令行窗口。' -ForegroundColor Green
