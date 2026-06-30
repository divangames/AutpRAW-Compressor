@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "REMOTE=github"
set "BRANCH=master"
set "REPO_URL=https://github.com/divangames/AutpRAW-Compressor.git"
set "REPO_WEB=https://github.com/divangames/AutpRAW-Compressor"
rem Fix "dubious ownership" when folder was created under another Windows user
set "GIT_SAFE=-c safe.directory=%CD%"

if not exist ".git" (
    echo Not a git repository. Run from project root:
    echo   git init
    echo   git add .
    echo   git commit -m "Initial commit"
    echo Then run sync_github.bat again.
    pause
    exit /b 1
)

git %GIT_SAFE% remote get-url %REMOTE% >nul 2>&1
if errorlevel 1 (
    git %GIT_SAFE% remote add %REMOTE% "%REPO_URL%"
    echo Added remote %REMOTE% -^> %REPO_URL%
) else (
    git %GIT_SAFE% remote set-url %REMOTE% "%REPO_URL%"
    echo Remote %REMOTE% -^> %REPO_URL%
)

echo.
echo Pushing %BRANCH% to GitHub (%REMOTE%)...
git %GIT_SAFE% push -u %REMOTE% %BRANCH%
if errorlevel 1 (
    echo.
    echo Push failed. Check access to:
    echo   %REPO_WEB%
    echo.
    pause
    exit /b 1
)

echo.
echo GitHub is up to date: %REPO_WEB%
pause
exit /b 0
