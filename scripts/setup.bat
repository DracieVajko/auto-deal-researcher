@echo off
REM Auto Deal Searcher - first-run setup for Windows.
REM
REM   scripts\setup.bat            interactive setup
REM   scripts\setup.bat --check    just verify what is in place
REM
REM Safe to re-run: every step is skipped when it is already done.
REM Everything that needs quoting lives in scripts\_setup_helper.py.

setlocal EnableDelayedExpansion
cd /d "%~dp0.."

echo.
echo Auto Deal Searcher - setup
echo ==========================

set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo   xx  Python not found. Install Python 3.11-3.13 from python.org
    exit /b 1
  )
  set "PY=py -3"
)

set "HELPER=scripts\_setup_helper.py"
set "CHECK_ONLY=0"
if /i "%~1"=="--check" set "CHECK_ONLY=1"

REM ---- Python -------------------------------------------------------------
echo ==^> Python
%PY% %HELPER% python-version

REM ---- Virtualenv ---------------------------------------------------------
if "%CHECK_ONLY%"=="0" (
  if exist ".venv\Scripts\activate.bat" (
    echo   ok  virtualenv already present
  ) else (
    echo ==^> Creating virtualenv
    %PY% -m venv .venv
    if exist ".venv\Scripts\activate.bat" ( echo   ok  created .venv ) else ( echo   !!  venv failed; using the current interpreter )
  )
)
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

REM ---- Dependencies -------------------------------------------------------
if "%CHECK_ONLY%"=="0" (
  echo ==^> Installing dependencies
  %PY% -m pip install --upgrade pip >nul 2>&1
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 ( echo   xx  pip install failed & exit /b 1 )
  echo   ok  requirements installed

  echo ==^> Installing Playwright browsers
  %PY% -m playwright install chromium >nul 2>&1
  if errorlevel 1 ( echo   !!  playwright install failed; run it manually ) else ( echo   ok  chromium installed )
)

REM ---- Config files -------------------------------------------------------
if not exist "config.yaml" (
  copy /y "config.example.yaml" "config.yaml" >nul
  echo   ok  config.yaml created from the example
) else (
  echo   ok  config.yaml already present
)
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo   ok  .env created - add your API keys inside it
) else (
  echo   ok  .env already present
)

REM ---- Browser choice -----------------------------------------------------
if "%CHECK_ONLY%"=="0" (
  echo ==^> Browsers
  %PY% %HELPER% list-browsers
  echo.
  set "BCHOICE="
  set /p "BCHOICE=Which one? (id such as brave/chrome/msedge, Enter for auto-detect): "
  if not "!BCHOICE!"=="" ( %PY% %HELPER% set-browser "!BCHOICE!" ) else ( echo   ok  left on auto-detect )
)

REM ---- Verify -------------------------------------------------------------
echo ==^> Verifying
%PY% -m src.cli config-check
%PY% %HELPER% login-status
%PY% %HELPER% doctor-hint

echo.
echo   ok  setup finished
echo.
echo   Next:
echo     scripts\login.bat               log in to sites that need it
echo     python -m src.cli doctor         check the sites work
echo     python -m src.cli run --prompt "dji drone under 350"
echo.
endlocal