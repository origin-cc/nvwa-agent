@echo off
rem NvwaAgent 一键启动入口（双击运行）
rem 首次运行可先加参数：start.bat -SkipInstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
