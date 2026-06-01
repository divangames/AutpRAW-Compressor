@echo off

setlocal EnableExtensions



cd /d "%~dp0"



call "%~dp0_common.bat" deps

if errorlevel 1 (

    echo Run setup.bat or install Python 3.12+.

    pause

    exit /b 1

)



if not "%~1"=="" goto cli



:menu

echo.

if defined APP_VERSION (echo AutoRAW Compressor %APP_VERSION% - build menu) else (echo AutoRAW Compressor - build menu)

echo   1 - Build dist\AutoRAWCompressor

echo   2 - Build MSIX package

echo   3 - Clean build artifacts

echo   4 - Run GUI from dist

echo   5 - Help

echo   0 - Exit

echo.

set "CHOICE="

set /p CHOICE=Select [1-5, 0]: 



if "%CHOICE%"=="0" exit /b 0

if "%CHOICE%"=="1" call :do_build & goto menu

if "%CHOICE%"=="2" call :do_msix & goto menu

if "%CHOICE%"=="3" call :do_clean & goto menu

if "%CHOICE%"=="4" call :do_run & goto menu

if "%CHOICE%"=="5" call :do_help & goto menu

echo Invalid choice.

goto menu



:cli

if /I "%~1"=="build" call :do_build & exit /b %errorlevel%

if /I "%~1"=="msix" call :do_msix & exit /b %errorlevel%

if /I "%~1"=="msi" call :do_msix & exit /b %errorlevel%

if /I "%~1"=="clean" call :do_clean & exit /b %errorlevel%

if /I "%~1"=="run" call :do_run & exit /b %errorlevel%

if /I "%~1"=="help" call :do_help & exit /b 0

echo Unknown option: %~1

call :do_help

exit /b 1



:do_build

echo.

echo Building portable dist...

%PYTHON_EXE% build\build_dist.py

if errorlevel 1 (

    echo Build failed.

    exit /b 1

)

echo.

echo Done: dist\AutoRAWCompressor

exit /b 0



:do_msix

echo.

echo Building MSIX package...

%PYTHON_EXE% build\build_msix.py --rebuild-dist

if errorlevel 1 (

    echo MSIX build failed.

    echo Install Windows SDK: winget install Microsoft.WindowsSDK.10.0.22621

    exit /b 1

)

echo.

echo Done: dist\AutoRAWCompressor-*.msix

echo        dist\AutoRAWCompressor-*-CHANGELOG.txt

exit /b 0



:do_clean

echo.

%PYTHON_EXE% build\build_dist.py --clean-only

if exist "dist\AutoRAWCompressor-*.msix" del /q "dist\AutoRAWCompressor-*.msix" 2>nul

if exist "dist\AutoRAWCompressor-*.msi" del /q "dist\AutoRAWCompressor-*.msi" 2>nul

if exist "dist\AutoRAWCompressor-*-CHANGELOG.txt" del /q "dist\AutoRAWCompressor-*-CHANGELOG.txt" 2>nul

if exist "build\msix\work" rmdir /s /q "build\msix\work" 2>nul

echo Clean complete.

exit /b 0



:do_run

if not exist "dist\AutoRAWCompressor\AutoRAW-GUI.exe" (

    echo dist\AutoRAWCompressor\AutoRAW-GUI.exe not found. Run build first.

    exit /b 1

)

start "" "dist\AutoRAWCompressor\AutoRAW-GUI.exe"

echo GUI started.

exit /b 0



:do_help

echo.

echo Usage: build.bat [build^|msix^|clean^|run^|help]

echo.

echo   build  - compile portable dist to dist\AutoRAWCompressor

echo   msix   - build MSIX package into dist\

echo   clean  - remove dist and build cache

echo   run    - start GUI from dist

echo.

echo MSIX requires Windows 10/11 SDK (MakeAppx + SignTool):

echo   winget install Microsoft.WindowsSDK.10.0.22621

echo.

echo First install on PC: run build\msix\install_cert.bat as Administrator,

echo then double-click the .msix file.

echo.

exit /b 0


