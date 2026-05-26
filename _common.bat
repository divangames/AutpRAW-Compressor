@echo off
rem Shared helpers for project .bat launchers (no setlocal here).
rem Usage:
rem   call "%~dp0_common.bat"          - resolve PYTHON_EXE
rem   call "%~dp0_common.bat" deps    - resolve + install requirements.txt if needed

set "PYTHON_EXE="
where python >nul 2>&1 && (
    set "PYTHON_EXE=python"
    goto :python_ok
)
where py >nul 2>&1 && (
    set "PYTHON_EXE=py -3"
    goto :python_ok
)

echo.
echo [ERROR] Python 3 not found in PATH.
echo Install from https://www.python.org/downloads/
echo Or: winget install Python.Python.3.12
exit /b 1

:python_ok
if /I not "%~1"=="deps" exit /b 0

"%PYTHON_EXE%" -c "import PIL, numpy" >nul 2>&1
if not errorlevel 1 exit /b 0

echo.
echo Installing runtime dependencies (Pillow, numpy)...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
exit /b %errorlevel%
