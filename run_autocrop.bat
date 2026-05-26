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

set "INPUT_DIR=test"
set "REFERENCE_DIR=reference\Sneakers"
set "OUTPUT_DIR=output"

if defined APP_VERSION (echo AutoRAW Compressor %APP_VERSION%) else (echo AutoRAW Compressor)
echo Input:     %INPUT_DIR%
echo Reference: %REFERENCE_DIR%
echo Output:    %OUTPUT_DIR%
echo.

"%PYTHON_EXE%" src\autoraw_crop.py --input "%INPUT_DIR%" --reference "%REFERENCE_DIR%" --output "%OUTPUT_DIR%"

echo.
if errorlevel 1 (
    echo Finished with errors.
    pause
    exit /b 1
)

echo Finished successfully.
pause
exit /b 0
