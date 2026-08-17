@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==============================================
echo   Dong goi Minit Authenticator thanh file EXE
echo ==============================================
echo.

REM --- 1. Tim Python -----------------------------------------------------
set "PY=py -3"
%PY% --version >nul 2>&1
if errorlevel 1 (
    set "PY=python"
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Cai tai https://www.python.org/downloads/
        pause
        exit /b 1
    )
)
echo [1/4] Python: & %PY% --version

REM --- 2. Cai thu vien can thiet -----------------------------------------
echo [2/4] Kiem tra thu vien (pyinstaller, zxing-cpp, pillow)...
%PY% -m PyInstaller --version >nul 2>&1
if errorlevel 1 goto install
%PY% -c "import zxingcpp, PIL" >nul 2>&1
if errorlevel 1 goto install
goto ready

:install
echo       Dang cai dat, cho mot chut...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai thu vien that bai.
    pause
    exit /b 1
)

:ready
REM --- 3. Kiem tra icon --------------------------------------------------
echo [3/4] Kiem tra icon...
if not exist "icon.ico" (
    echo [LOI] Khong tim thay icon.ico trong thu muc nay.
    pause
    exit /b 1
)

REM --- 4. Build ----------------------------------------------------------
echo [4/4] Dang build (mat 1-3 phut)...
%PY% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --clean ^
    --name "Minit Authenticator" ^
    --icon icon.ico ^
    --add-data "icon.ico;." ^
    --hidden-import zxingcpp ^
    --hidden-import PIL.ImageGrab ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module matplotlib ^
    --exclude-module pytest ^
    --exclude-module PyQt5 ^
    --exclude-module PySide2 ^
    main.py

if errorlevel 1 (
    echo.
    echo [LOI] Build that bai. Xem thong bao loi ben tren.
    pause
    exit /b 1
)

echo.
echo ==============================================
echo   XONG! File EXE nam tai:
echo   %CD%\dist\Minit Authenticator.exe
echo ==============================================
echo.
echo Copy file EXE nay di dau cung chay duoc, khong can cai Python.
echo.
pause
