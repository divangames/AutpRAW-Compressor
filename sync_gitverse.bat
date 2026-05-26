@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "REMOTE=gitverse"
set "BRANCH=master"
set "REPO_URL=https://gitverse.ru/delbraun/AutoRAWCompressor.git"
set "REPO_WEB=https://gitverse.ru/delbraun/AutoRAWCompressor"
rem Fix "dubious ownership" when folder was created under another Windows user
set "GIT_SAFE=-c safe.directory=%CD%"

if not exist ".git" (
    echo Not a git repository. Run from project root:
    echo   git init
    echo   git add .
    echo   git commit -m "Initial commit"
    echo Then run sync_gitverse.bat again.
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
echo Pushing %BRANCH% to GitVerse (%REMOTE%)...
git %GIT_SAFE% push -u %REMOTE% %BRANCH%
if errorlevel 1 (
    echo.
    echo Push failed. Create empty repo on GitVerse first:
    echo   https://gitverse.ru/new
    echo Name: AutoRAWCompressor, without README / .gitignore
    echo Repo: %REPO_WEB%
    echo.
    pause
    exit /b 1
)

echo.
echo GitVerse is up to date: %REPO_WEB%
pause
exit /b 0
