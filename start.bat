@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONPATH=
set PYTHONIOENCODING=utf-8
if not exist tmp mkdir tmp
set TEMP=%~dp0tmp
set TMP=%~dp0tmp
if exist .venv\Scripts\python.exe goto deps
where py >nul 2>nul
if %errorlevel% equ 0 (py -3 -m venv .venv) else (python -m venv .venv)
if errorlevel 1 goto error
:deps
.venv\Scripts\python.exe -c "import fastapi,uvicorn,numpy,sklearn,httpx,multipart" >nul 2>nul
if %errorlevel% equ 0 goto run
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto error
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_local.ps1"
if errorlevel 1 goto error
exit /b 0
:error
echo 启动失败，请根据上方信息检查 Python 3.12+ 和网络连接。
pause
exit /b 1
