@echo off
setlocal
python "%~dp0bethesda_mod_downloader.py" --gui
if errorlevel 1 (
  echo.
  echo If Python is not on PATH, run:
  echo   python "%~dp0bethesda_mod_downloader.py" --gui
  pause
)
