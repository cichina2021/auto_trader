# auto_trader.exe 打包指南

## 快速开始（Windows）

### 方法一：直接双击运行（推荐）

1. 将 `dist/auto_trader/auto_trader.exe` 复制到任何位置
2. 双击 `auto_trader.exe`
3. 打开浏览器访问 http://localhost:8080/status 查看监控面板

### 方法二：命令行运行

```bash
cd dist\auto_trader
auto_trader.exe
```

## 打包步骤（在 Windows 上执行）

### 前提条件
- Windows 10/11
- Python 3.10+ (https://www.python.org/downloads/)
- 安装 Python 时勾选 "Add Python to PATH"

### 打包命令

```batch
# 1. 安装依赖
pip install akshare pandas numpy requests pyinstaller

# 2. 进入packaging目录
cd packaging

# 3. 运行打包脚本
build.bat
```

或手动执行：
```bash
pyinstaller auto_trader.spec --clean
```

打包完成后，EXE 在 `dist/auto_trader/auto_trader.exe`

## 模式切换

编辑 `main.py` 顶部的配置区：

```python
MODE = "mock"   # ← 模拟账户，不实际下单
# MODE = "live"  # ← 实盘，需要先启动 ths_trades WEB 服务
```

## 配置文件

| 参数 | 说明 | 默认值 |
|------|------|--------|
| MODE | "mock"模拟 / "live"实盘 | mock |
| AUTO_SCAN | True=扫全池108只 | True |
| THS_TRADES_HOST | ths_trades WEB API地址 | http://127.0.0.1:6003 |
| BASE_POSITION | 底仓股数 | 15,300 |
| T_POSITION | 做T仓位股数 | 1,200 |
| COST_PRICE | 成本价 | 10.731 |
| buy_drop_threshold | 触发买入的跌幅 | -0.5% |
| sell_rise_threshold | 触发卖出的涨幅 | +0.5% |
| confidence_min | 最低置信度 | 65% |

## Parallels 虚拟机使用

1. 将 `auto_trader.exe` 复制到虚拟机
2. 安装 Python 依赖（或使用打包后的 EXE）
3. 同花顺模拟账户登录
4. 启动 ths_trades 服务（或用模拟模式）
5. 运行 auto_trader.exe

## ths_trades 实盘支持

ths_trades 提供了 WEB API 接口，启动后在 Windows 后台运行：

```
ths_trades.exe --port 6003
```

auto_trader 会自动将信号发送到这个接口，由 ths_trades 完成实际下单。

## 监控面板

运行后访问：
- http://localhost:8080/status — 查看所有扫描结果
- POST /scan — API查询单只股票（body: `{"code":"002539"}`）

## 常见问题

**Q: 打包后缺少 akshare 模块？**
A: `pyinstaller auto_trader.spec` 会自动收集所有依赖，确保网络正常

**Q: 启动报错 "No module named 'tkinter'"？**
A: main.py 中已移除 tkinter，使用纯命令行输出

**Q: 如何停止程序？**
A: 按 Ctrl+C 或关闭命令行窗口

**Q: 能否在 Mac 上打包 Windows EXE？**
A: 可以用 `pip install pyinstaller` + Wine，但跨平台交叉打包较复杂，建议在 Windows 虚拟机中执行 build.bat
