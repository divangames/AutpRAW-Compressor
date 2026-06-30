@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "DROP=%~dp0..\droplets"
if not exist "%DROP%" mkdir "%DROP%"
if not exist "%DROP%\Main" mkdir "%DROP%\Main"
if not exist "%DROP%\Old" mkdir "%DROP%\Old"

for %%F in ("%DROP%\01_drop.exe" "%DROP%\02-03-04-08_drop.exe" "%DROP%\05-06-07_drop.exe") do (
    if exist "%%~F" if not exist "%DROP%\Main\%%~nxF" move /Y "%%~F" "%DROP%\Main\" >nul
)

echo.
echo Структура droplets:
echo   Main\  — основной проход (01_drop, 02-03-04-08, 05-06-07)
echo   Old\   — старый проход (old.exe)
echo.
if not exist "%DROP%\Old\old.exe" echo [ ] Положите old.exe в droplets\Old\
if exist "%DROP%\Main\01_drop.exe" (echo [ok] Main) else (echo [ ] Нет дроплетов в Main)
pause
