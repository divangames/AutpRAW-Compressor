@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if exist "%~dp0..\_common.bat" (
    call "%~dp0..\_common.bat" deps
    if errorlevel 1 (
        echo.
        echo Run setup.bat in parent folder, or install Python 3.12+.
        pause
        exit /b 1
    )
) else (
    set "PYTHON_EXE="
    where python >nul 2>&1 && set "PYTHON_EXE=python"
    if not defined PYTHON_EXE where py >nul 2>&1 && set "PYTHON_EXE=py -3"
    if not defined PYTHON_EXE (
        echo Python 3 not found in PATH.
        pause
        exit /b 1
    )
)

if "%~1"=="" (
    "%PYTHON_EXE%" "%~dp0autoaction_gui.py"
) else (
    "%PYTHON_EXE%" "%~dp0autoaction_gui.py" "%~1"
)

if errorlevel 1 (
    echo.
    echo AutoAction exited with an error.
    pause
    exit /b 1
)

exit /b 0
