# 🤖 AutoTrader — 纯视觉全自动交易系统

> 基于屏幕截图 + OCR + 模拟操作，无需券商API，适配同花顺客户端

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    AutoTrader 核心调度                    │
│                    scheduler.py (主循环)                  │
└──────┬──────────┬──────────┬──────────┬─────────────────┘
       │          │          │          │
  ┌────▼────┐ ┌───▼───┐ ┌───▼────┐ ┌───▼────┐
  │  数据层  │ │策略引擎│ │ 视觉层 │ │ 风控层 │
  │  data/  │ │strategy│ │vision/ │ │ risk/  │
  └────┬────┘ └───┬───┘ └───┬────┘ └───┬────┘
       │          │          │          │
  行情数据     信号生成    截图+OCR    仓位管理
  akshare     技术指标   模拟点击    止盈止损
```

## 模块说明

| 模块 | 文件 | 功能 |
|------|------|------|
| 数据层 | `data/market.py` | akshare实时行情、历史K线 |
| 策略引擎 | `strategy/engine.py` | 技术指标计算、买卖信号生成 |
| 策略定义 | `strategy/strategies.py` | 可配置的策略规则 |
| 视觉层 | `vision/trader.py` | 截图识别、模拟键鼠操作同花顺 |
| 风控层 | `risk/manager.py` | 仓位管理、止盈止损、每日限额 |
| 主调度 | `core/scheduler.py` | 交易时间控制、主循环 |
| 配置 | `config/settings.py` | 所有参数集中配置 |

## 运行环境

- **Mac本机**：Python策略引擎 + 数据层（macOS）
- **Windows虚拟机**：同花顺客户端（Parallels/VMware）
- **通信方式**：通过共享文件夹传递交易指令

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置参数
vim config/settings.py

# 启动系统
python core/scheduler.py
```

## 策略配置（云图控股 002539 做T）

在 `config/settings.py` 中配置：
- 底仓：15300股 @ 10.731（不动）
- 做T仓位：2400股（自动买卖）
- 策略逻辑：由你定义后在 `strategy/strategies.py` 实现
