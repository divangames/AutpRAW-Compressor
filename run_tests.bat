@echo off
setlocal EnableExtensions

cd /d "%~dp0"

call "%~dp0_common.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
echo Python: %PYTHON_EXE%
echo.

"%PYTHON_EXE%" -m pip install -r "%~dp0requirements-dev.txt"
if errorlevel 1 goto failed

echo.
"%PYTHON_EXE%" -m pytest tests -q
if errorlevel 1 goto failed

echo.
echo Tests passed.
goto done

:failed
echo.
echo Tests failed.
pause
exit /b 1

:done
pause
exit /b 0
