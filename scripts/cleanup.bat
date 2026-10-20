@echo off
REM Cleanup script for Auto Deal Searcher - Windows
REM Removes debug files, cache, outputs, runs, and temporary files

echo ============================================
echo Auto Deal Searcher - Cleanup
echo ============================================
echo.

set "PROJECT_ROOT=%~dp0.."

cd /d "%PROJECT_ROOT%"

echo.
echo [1/6] Cleaning Python cache files...
if exist "__pycache__" (
    rmdir /s /q "__pycache__" 2>nul
    echo   Removed __pycache__/
)
for /r %%d in (__pycache__) do (
    rmdir /s /q "%%d" 2>nul
)
for /r %%d in (\.pytest_cache) do (
    rmdir /s /q "%%d" 2>nul
)
for /r %%d in (\.mypy_cache) do (
    rmdir /s /q "%%d" 2>nul
)
for /r %%d in (\.ruff_cache) do (
    rmdir /s /q "%%d" 2>nul
)
echo   Done.

echo.
echo [2/6] Cleaning test artifacts...
if exist ".coverage" del /q ".coverage" 2>nul && echo   Removed .coverage
if exist ".pytest_cache" rmdir /s /q ".pytest_cache" 2>nul && echo   Removed .pytest_cache/
if exist "htmlcov" rmdir /s /q "htmlcov" 2>nul && echo   Removed htmlcov/
if exist ".coverage.*" del /q ".coverage.*" 2>nul
echo   Done.

echo.
echo [3/6] Cleaning output directories...
if exist "results" (
    rmdir /s /q "results" 2>nul
    echo   Removed results/
)
if exist "data" (
    echo   Preserving data/ (contains deals.db and sessions)
    echo   Use 'cleanup.bat --deep' to also remove data/
)

echo.
echo [4/6] Cleaning browser profiles...
if exist "browser_profile" (
    rmdir /s /q "browser_profile" 2>nul
    echo   Removed browser_profile/
)
if exist "browser_profile_brave" (
    rmdir /s /q "browser_profile_brave" 2>nul
    echo   Removed browser_profile_brave/
)

echo.
echo [5/6] Cleaning temporary files...
if exist "tmp" rmdir /s /q "tmp" 2>nul && echo   Removed tmp/
for %%f in (*.tmp *.log *.tmp.py *.bak) do del /q "%%f" 2>nul
for %%f in (*.tmp *.log *.tmp.py *.bak) do if exist "%%f" del /q "%%f" 2>nul

echo.
echo [6/6] Cleaning editor/IDE artifacts...
if exist ".vscode" rmdir /s /q ".vscode" 2>nul && echo   Removed .vscode/
if exist ".idea" rmdir /s /q ".idea" 2>nul && echo   Removed .idea/
for %%f in (*.swp *.swo *~) do del /q "%%f" 2>nul

echo.
echo ============================================
echo Cleanup complete!
echo ============================================
echo.
echo Note: The following were preserved:
echo   - config.yaml, .env (your configuration)
echo   - data/deals.db (deal database)
echo   - data/sessions/ (login sessions)
echo   - config.yaml, .env.example
echo.
echo To also remove database and sessions, run: cleanup.bat --deep
echo.

if "%1"=="--deep" (
    echo.
    echo [DEEP CLEAN] Removing database and sessions...
    if exist "data" rmdir /s /q "data" 2>nul && echo   Removed data/
    echo.
    echo Deep clean complete!
)

endlocal