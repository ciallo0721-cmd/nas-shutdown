@echo off
chcp 936 >nul
taskkill /F /IM cloudflared.exe >nul 2>&1
timeout /t 2 /nobreak >nul
cd /d "%~dp0"
start "" cloudflared.exe tunnel run --protocol http2 mininas
echo.
echo cloudflared restarted (http2). Window can be closed.
pause
