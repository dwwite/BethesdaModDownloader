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
  --onedir ^
  --windowed ^
  --name BethesdaModDownloader ^
  "%SCRIPT_DIR%bethesda_mod_downloader.py"

if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

if not exist "%SCRIPT_DIR%dist\BethesdaModDownloader\downloads" mkdir "%SCRIPT_DIR%dist\BethesdaModDownloader\downloads"
copy /Y "%SCRIPT_DIR%bethesda_mod_downloader_README.md" "%SCRIPT_DIR%dist\BethesdaModDownloader\README.md" >nul
(
  echo @echo off
  echo setlocal
  echo start "" "%%~dp0BethesdaModDownloader.exe"
) > "%SCRIPT_DIR%dist\BethesdaModDownloader\Launch Dwwite Downloader.bat"

echo.
echo App folder built at:
echo   %SCRIPT_DIR%dist\BethesdaModDownloader
pause
