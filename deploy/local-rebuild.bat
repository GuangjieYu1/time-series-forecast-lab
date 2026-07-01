@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "PYTHON_BIN=%REPO_ROOT%\backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_BIN%" (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.11 "%SCRIPT_DIR%local_rebuild.py"
    goto :after_run
  )
  set "PYTHON_BIN=python"
)

"%PYTHON_BIN%" "%SCRIPT_DIR%local_rebuild.py"
:after_run
if errorlevel 1 (
  echo.
  echo 本地重建失败，请检查 deploy\logs 或终端输出。
  pause
  exit /b 1
)

echo.
echo 本地重建已触发，日志在 deploy\logs 目录。
pause
