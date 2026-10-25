@echo off
rem kdp-studio: double-click to start the local web interface (opens the browser when ready).
cd /d "%~dp0"
python -c "import kdp_studio" 2>nul
if errorlevel 1 (
  echo kdp-studio chua duoc cai. Mo PowerShell trong thu muc nay va chay:  Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1
  pause
  exit /b 1
)
echo Dang khoi dong kdp-studio tai http://127.0.0.1:8765 ... (dong cua so nay de tat)
python -X utf8 -m kdp_studio ui --port 8765
pause
