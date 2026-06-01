@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "Delbraun.pfx" (
    echo Delbraun.pfx not found. Run build.bat msix first to generate the certificate.
    pause
    exit /b 1
)

echo Installing publisher certificate for AutoRAW MSIX...
echo Run this script as Administrator if installation fails.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pwd = ConvertTo-SecureString -String 'AutoRAW-MSIX' -Force -AsPlainText; ^
   Import-PfxCertificate -FilePath '%~dp0Delbraun.pfx' -Password $pwd -CertStoreLocation Cert:\LocalMachine\TrustedPeople"

if errorlevel 1 (
    echo.
    echo Failed. Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo.
echo Certificate installed. You can now install dist\AutoRAWCompressor-*.msix
pause
