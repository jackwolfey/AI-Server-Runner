@echo off
setlocal
cd /d "%~dp0"

echo ==============================================
echo  AI Server Runner - PyInstaller build (onefile)
echo ==============================================
echo.

REM ---- 1. Check PyInstaller, install if missing ----
python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [i] PyInstaller not found, installing...
    python -m pip install pyinstaller
    if errorlevel 1 goto :fail
)

REM ---- 2. Check UPX (optional, for smaller exe) ----
where upx >nul 2>nul
if errorlevel 1 (
    echo [i] UPX not found, skip compression.
    echo     To reduce exe size further: install UPX and add its
    echo     folder to PATH, then run this script again.
) else (
    echo [i] UPX found, binaries will be compressed.
)

REM ---- 3. Build with spec config ----
echo [i] Building, please wait (first build is slow)...
python -m PyInstaller --clean --noconfirm "ai_server_runner.spec"
if errorlevel 1 goto :fail

echo.
echo [OK] Build finished: dist\AI Server Runner.exe
echo      Single-file exe, can be copied anywhere and run directly.
pause
exit /b 0

:fail
echo.
echo [!] Build failed, check the errors above.
pause
exit /b 1
