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

echo Installing runtime dependencies...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed

echo.
echo Optional: build tools (PyInstaller)...
"%PYTHON_EXE%" -m pip install -r "%~dp0requirements-build.txt"
if errorlevel 1 goto failed

echo.
echo Setup complete. Use run_gui.bat or build.bat build
goto done

:failed
echo.
echo Setup failed.
pause
exit /b 1

:done
pause
exit /b 0
