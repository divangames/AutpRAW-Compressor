@echo off
setlocal EnableExtensions

cd /d "%~dp0"

call "%~dp0_common.bat" deps
if errorlevel 1 (
    echo Run setup.bat or install Python 3.12+.
    pause
    exit /b 1
)

if "%~1"=="" goto menu

if /I "%~1"=="build" goto build
if /I "%~1"=="clean" goto clean
if /I "%~1"=="run" goto run
if /I "%~1"=="help" goto help

echo Unknown option: %~1
goto help

:menu
echo.
if defined APP_VERSION (echo AutoRAW Compressor %APP_VERSION% - build menu) else (echo AutoRAW Compressor - build menu)
echo   1 - Build dist\AutoRAWCompressor
echo   2 - Clean build artifacts
echo   3 - Run GUI from dist
echo   4 - Help
echo   0 - Exit
echo.
set /p CHOICE=Select [1-4, 0]: 

if "%CHOICE%"=="1" goto build
if "%CHOICE%"=="2" goto clean
if "%CHOICE%"=="3" goto run
if "%CHOICE%"=="4" goto help
if "%CHOICE%"=="0" exit /b 0
echo Invalid choice.
pause
exit /b 1

:build
echo.
echo Building...
%PYTHON_EXE% build\build_dist.py
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Done: dist\AutoRAWCompressor
pause
exit /b 0

:clean
echo.
%PYTHON_EXE% build\build_dist.py --clean-only
pause
exit /b 0

:run
if not exist "dist\AutoRAWCompressor\AutoRAW-GUI.exe" (
    echo dist\AutoRAWCompressor\AutoRAW-GUI.exe not found. Run build first.
    pause
    exit /b 1
)
start "" "dist\AutoRAWCompressor\AutoRAW-GUI.exe"
exit /b 0

:help
echo.
echo Usage: build.bat [build^|clean^|run^|help]
echo.
echo   build  - compile to dist\AutoRAWCompressor
echo   clean  - remove dist and build cache
echo   run    - start GUI from dist
echo.
pause
exit /b 0
