@echo off
rem Push code to GitHub and GitVerse (releases and updates — GitHub only).
setlocal EnableExtensions

cd /d "%~dp0"
set "GIT_SAFE=-c safe.directory=%CD%"
set "BRANCH=master"

if not exist ".git" (
    echo Not a git repository.
    pause
    exit /b 1
)

echo Pushing %BRANCH% to GitHub...
git %GIT_SAFE% push -u github %BRANCH%
if errorlevel 1 (
    echo GitHub push failed.
    pause
    exit /b 1
)

echo.
echo Pushing %BRANCH% to GitVerse...
git %GIT_SAFE% push -u gitverse %BRANCH%
if errorlevel 1 (
    echo GitVerse push failed.
    pause
    exit /b 1
)

echo.
echo Both remotes are up to date.
pause
exit /b 0
