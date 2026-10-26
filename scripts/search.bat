@echo off
REM Prompt-only deal search - Windows launcher.
cd /d "%~dp0.."

set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Install Python 3.11+ or run scripts\setup.bat first.
    exit /b 1
  )
  set "PY=py -3"
)

%PY% -m src.cli ask
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
