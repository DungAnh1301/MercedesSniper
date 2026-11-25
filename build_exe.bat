@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   DONG GOI MERCEDES SNIPER MAX SPEED RA DESKTOP (.EXE)
echo ========================================================
set "FFMPEG_BIN=C:\ffmpeg\bin\ffmpeg.exe"
if exist "ffmpeg.exe" set "FFMPEG_BIN=ffmpeg.exe"
python -m PyInstaller --noconfirm --clean --windowed --onefile --icon "mercedes.ico" --name "MercedesSniper_MaxSpeed" --add-binary "%FFMPEG_BIN%;." --collect-all curl_cffi --hidden-import "core.worker_bridge" --hidden-import "core.turbo_downloader" --hidden-import "core.capcut_injector" --hidden-import "core.updater" --hidden-import "yt_dlp" --distpath "%USERPROFILE%\Desktop" app.py
echo.
echo [OK] Da xuat file: %USERPROFILE%\Desktop\MercedesSniper_MaxSpeed.exe
pause
