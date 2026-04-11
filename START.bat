@echo off
chcp 65001 > nul
echo Starting Grondheim v5.2...

:: 1. Start Beacon server
start "GRONDHEIM BEACON" cmd /k "cd /d %~dp0server && python beacon_v4.py"

:: Wait 3 sec
timeout /t 3

:: 2. Open Dashboard via Beacon (port 8001)
start "" "http://127.0.0.1:8001/dashboard/index.html"

:: 3. Open Iskra via Beacon (port 8001)
start "" "http://127.0.0.1:8001/player/index.html"

echo.
echo DO NOT use Live Server (port 5500) - it reloads Iskra!
echo.
echo All systems started on port 8001
pause
