@echo off
chcp 65001 >nul
cd /d "%~dp0"

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
