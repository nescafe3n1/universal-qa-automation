@echo off
setlocal
if "%~1"=="" (
    echo.
    echo =========================================================================
    echo  NES-DEV QA TEST GENERATOR ^& RUNNER
    echo =========================================================================
    echo  Usage:
    echo    run-playwright ^<URL^> [options]
    echo.
    echo  Examples:
    echo    run-playwright https://example.com
    echo    run-playwright https://example.com --headed
    echo    run-playwright https://example.com --no-run
    echo =========================================================================
    echo.
    exit /b 1
)

python "%~dp0run_playwright.py" %*
endlocal
