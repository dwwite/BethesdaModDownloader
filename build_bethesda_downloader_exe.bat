@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  set "PYTHON_CMD=python"
)

call %PYTHON_CMD% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name BethesdaModDownloader ^
  "%SCRIPT_DIR%bethesda_mod_downloader.py"

if errorlevel 1 (
  echo Build failed.
  if not defined CI if not defined NO_PAUSE pause
  exit /b 1
)

echo.
echo Single-file app built at:
echo   %SCRIPT_DIR%dist\BethesdaModDownloader.exe
if not defined CI if not defined NO_PAUSE pause
