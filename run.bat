@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv || goto :error
  call ".venv\Scripts\python.exe" -m pip install --upgrade pip
  call ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
call ".venv\Scripts\python.exe" -m mailmerge_app.desktop
goto :eof
:error
echo.
echo MailDesk could not start. Install Python 3.11 or later and try again.
pause
exit /b 1
