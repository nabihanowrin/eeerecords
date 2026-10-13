@echo off
cd /d "%~dp0"
echo.
echo   Starting the FINAL project at http://localhost:8080 . KEEP THIS WINDOW OPEN.
echo   The website will open in your browser in a few seconds.
echo   To stop: close this window.
echo.
start "" /min powershell -NoProfile -Command "Start-Sleep 3; Start-Process http://localhost:8080/landing.html"
where py >nul 2>nul
if %errorlevel%==0 (py server.py) else (python server.py)
echo.
echo   The server stopped. If you see an error above, take a screenshot.
pause
