@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MERCEDES SNIPER - PHAT HANH BAN CAP NHAT LEN GITHUB RELEASES
echo ====================================================================
echo     MERCEDES SNIPER - DONG GOI ^& PHAT HANH CAP NHAT QUA GITHUB
echo ====================================================================
echo.
set /p REL_TAG="Nhap phien ban moi (vi du v1.0.1): "
if "%REL_TAG%"=="" (
    echo [!] Ban chua nhap phien ban!
    pause
    exit /b 1
)
set /p REL_NOTES="Nhap ghi chu cap nhat: "
python publish_release.py --tag "%REL_TAG%" --notes "%REL_NOTES%" --sync-desktop
echo.
pause
