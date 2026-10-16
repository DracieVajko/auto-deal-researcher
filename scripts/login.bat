@echo off
REM Log in, once, to every site that needs it.
REM
REM   scripts\login.bat              all sites that need a login
REM   scripts\login.bat facebook     just one
REM   scripts\login.bat --check      verify saved sessions
REM
REM A visible browser opens; you type your own credentials (including any
REM 2FA or mobile approval), then close the window. Cookies are saved to
REM data\sessions\ and reused by later runs. That folder is git-ignored.
REM These are real login credentials: never share them.

setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

set "PY=python"

if /i "%~1"=="--check" (
  %PY% scripts\login.py --all --check
  goto :done
)

if not "%~1"=="" (
  %PY% scripts\login.py --site %1
  goto :done
)

%PY% scripts\login.py --list
echo.
%PY% scripts\login.py --all
goto :done

:done
echo.
endlocal