@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   MiniNAS-FTP starting... (port 21)
echo   First time: pip install pyftpdlib
echo ============================================
python ftp_server.py
pause
