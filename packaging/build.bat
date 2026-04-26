@echo off
chcp 65001 >nul
echo ╔═══════════════════════════════════════════════════════╗
echo ║        auto_trader.exe 打包脚本 (Windows)           ║
echo ╚═══════════════════════════════════════════════════════╝
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo   下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] 检查依赖...
python -c "import akshare; import pandas; import numpy; import requests; print('  所有依赖OK')" 2>nul
if errorlevel 1 (
    echo [安装依赖] pip install akshare pandas numpy requests pyinstaller
    pip install akshare pandas numpy requests pyinstaller
)

echo [2/4] 清理旧构建...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del /q *.spec 2>nul

echo [3/4] 复制文件到打包目录...
:: 在当前目录（packaging）执行时，需要找到父目录的main.py和stock_pool.json
set ROOT=%~dp0..
copy "%ROOT%\main.py" "." >nul 2>&1
copy "%ROOT%\stock_pool.json" "." >nul 2>&1
:: 复制模块目录（即使bundled in main.py，也为PyInstaller收集数据）
xcopy /e /i /y "%ROOT%\data" "data" >nul 2>&1
xcopy /e /i /y "%ROOT%\strategy" "strategy" >nul 2>&1
xcopy /e /i /y "%ROOT%\vision" "vision" >nul 2>&1
xcopy /e /i /y "%ROOT%\config" "config" >nul 2>&1
xcopy /e /i /y "%ROOT%\risk" "risk" >nul 2>&1
xcopy /e /i /y "%ROOT%\core" "core" >nul 2>&1

echo [4/4] 开始打包（PyInstaller）...
echo   打包需要3-8分钟，请耐心等待...
echo.

:: 生成 version_info.txt（Windows需要）
echo 0,0,0,0 > version_info.txt

:: 打包命令（无窗口模式）
pyinstaller auto_trader.spec --clean

if errorlevel 1 (
    echo.
    echo [错误] 打包失败！尝试备选命令...
    pyinstaller --onefile --windowed --name auto_trader --add-data "stock_pool.json;." --hidden-import=akshare --hidden-import=pandas --hidden-import=numpy --hidden-import=requests main.py
)

echo.
if exist "dist\auto_trader" (
    echo ══════════════════════════════════════════════
    echo  打包成功！EXE文件位于:
    echo  dist\auto_trader\auto_trader.exe
    echo ══════════════════════════════════════════════
    echo.
    echo 使用方法:
    echo   双击 auto_trader.exe 直接运行
    echo   http://localhost:8080/status 查看监控面板
    echo.
    echo 切换模式（编辑main.py）:
    echo   MODE = "mock"  ^<- 模拟账户（不实际下单）
    echo   MODE = "live"  ^<- 实盘（需要ths_trades服务）
) else (
    echo [失败] 未找到dist目录，请查看上方错误信息
)

echo.
pause
