@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: opencode CLI is required but not installed on this system
:: Install it when you have network: npm install -g opencode-ai
:: Then this batch file will loop opencode for autonomous self-improvement.

echo ============================================================
echo  self_loop.bat — Autonomous OpenCode Improvement Loop
echo ============================================================
echo.
echo  Requires: opencode CLI installed globally
echo  Install:  npm install -g opencode-ai
echo.
echo  Once installed, this batch file will:
echo    1. Run: opencode run "analyze codebase, fix bugs/improvements, commit"
echo    2. Loop back to step 1 automatically
echo.
echo  Make sure you have:
echo    - A configured API provider (opencode auth login)
echo    - GitHub credentials for pushing commits
echo.
echo  To use after installing opencode:
echo    1. Remove this pause line and the 'exit'
echo    2. Run: self_loop.bat
echo.
pause
exit /b 1

:loop
echo ===== Self-Improvement Loop =====
opencode run ^
"Scan the entire codebase in chess_engine/ for bugs, edge cases, performance bottlenecks, or missing features. Fix any issues you find and commit changes using 'python commit.py' with a clear message. If no improvements are needed, still commit any pending changes. Then continue the loop."

if %errorlevel% neq 0 (
    echo Error occurred, waiting 30s before retry...
    timeout /t 30 /nobreak >nul
)
echo Restarting loop...
timeout /t 5 /nobreak >nul
goto loop
