@echo off
rem ============================================================
rem  MiniNAS launcher v3 (verbose colored boot)
rem  log: [2026-09-06-17:24] ... [OK] / [WARNING] / [Err]
rem ============================================================
chcp 65001 >nul
cd /d %~dp0

rem --- enable ANSI (VT) via nlog when available ---
if exist nlog.py python -c "import nlog" >nul 2>&1

rem --- grab ESC char for ANSI colors ---
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "W=%ESC%[97m"
set "G=%ESC%[32m"
set "Y=%ESC%[33m"
set "R=%ESC%[31m"
set "C=%ESC%[0m"
set "D=%ESC%[90m"
set "CY=%ESC%[36m"

rem --- timestamp via python (locale-proof, matches nlog) ---
python -c "import datetime;print(datetime.datetime.now().strftime('%%Y-%%m-%%d-%%H:%%M'))" > "%TEMP%\nasts.txt"
set /p TS=<"%TEMP%\nasts.txt"
del "%TEMP%\nasts.txt" >nul 2>&1

echo %D%======================================================================%C%
echo %W%[%TS%]%C% %CY%MiniNAS boot loader v3%C% %G%[OK]%C%
echo %W%[%TS%]%C% working dir : %~dp0 %G%[OK]%C%

rem --- python check ---
echo %W%[%TS%]%C% checking python 3 ...
python --version >nul 2>&1
if errorlevel 1 goto nopy
echo %W%[%TS%]%C% python found : %G%[OK]%C%

rem --- dependency check ---
python -c "import waitress, flask" >nul 2>&1
if errorlevel 1 goto install
echo %W%[%TS%]%C% dependencies ok %G%[OK]%C%
goto run

:install
echo %W%[%TS%]%C% flask/waitress missing, installing... %Y%[WARNING]%C%
pip install waitress flask -q >nul
python -c "import waitress, flask" >nul 2>&1
if errorlevel 1 goto nodep
echo %W%[%TS%]%C% dependencies installed %G%[OK]%C%

:run
echo %W%[%TS%]%C% launching nas_server.py on port 80 ... %G%[OK]%C%
echo.
python nas_server.py
pause
exit /b 0

:nopy
echo %W%[%TS%]%C% python NOT found %R%[Err]%C%
echo.
echo   Please install Python 3 from python.org (tick Add to PATH)
pause
exit /b 1

:nodep
echo %W%[%TS%]%C% dependency install FAILED %R%[Err]%C%
echo.
echo   Try manually:  pip install flask waitress
pause
exit /b 1
