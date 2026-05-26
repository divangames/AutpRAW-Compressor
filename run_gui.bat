@echo off
setlocal EnableExtensions

cd /d "%~dp0"

call "%~dp0_common.bat" deps
if errorlevel 1 (
    echo.
    echo Run setup.bat first, or install Python 3.12+.
    pause
    exit /b 1
)

if "%~1"=="" (
    "%PYTHON_EXE%" src\autoraw_gui.py
) else (
    "%PYTHON_EXE%" src\autoraw_gui.py "%~1"
)

if errorlevel 1 (
    echo.
    echo GUI exited with an error.
    pause
    exit /b 1
)

exit /b 0
