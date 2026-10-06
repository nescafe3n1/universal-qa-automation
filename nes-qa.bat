@echo off
rem Nes-Dev QA - double-click, or run:  nes-qa.bat [https://site-to-test.com] [options]
rem   no URL given  -> shows the logo screen and asks for the website, then whether the site needs a login
rem   --ask         -> asks every question (mode, folder, login, write tests, form submits)
setlocal
chcp 65001 >nul
title Nes-Dev QA
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python was not found. Install Python 3 from https://www.python.org/downloads/
    echo  and tick "Add python.exe to PATH" in the installer, then start this again.
    echo.
    pause
    exit /b 1
)

python -c "import playwright, pytest, pytest_playwright" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  First-time setup is needed. Run these two commands once, then start this again:
    echo      pip install -r requirements.txt
    echo      playwright install chromium
    echo.
    pause
    exit /b 1
)

python -m qa_generator.launcher %*
set "code=%errorlevel%"

rem Opened by double-clicking? Keep the window open so the result can be read.
rem (Scripts can set NESQA_NOPAUSE=1 to skip this.)
if not defined NESQA_NOPAUSE echo %cmdcmdline% | find /i "/c" >nul && pause
endlocal & exit /b %code%
