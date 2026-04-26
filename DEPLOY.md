# 🚀 AutoTrader v2 完整部署指南

## 架构总览

```
┌──────────────────────────────────────────────────────────┐
│              Mac本机（策略引擎 + 行情数据）                  │
│                                                          │
│  多数据源行情（akshare → Ashare → 同花顺OCR）              │
│          ↓                                               │
│  5种先进做T策略引擎（综合评分/多周期MACD/半仓滚动/日内网格/均价偏离）│
│          ↓                                               │
│  风控模块（止损/止盈/熔断/每日限额）                        │
│          ↓                                               │
│  统一执行层（ths_trades API / jqtrader / 文件信号）       │
└──────────────┐    ┌──────────────────────────────────────┘
               │    │ HTTP/文件信号
┌──────────────▼────▼──────────────────────────────────────┐
│              Windows虚拟机（Parallels）                      │
│                                                          │
│  ths_trades WEB API (python app.py) ← 推荐！             │
│  或 jqtrader / 模拟键鼠                                  │
│          ↓                                               │
│  同花顺客户端（模拟账户/实盘）                               │
└──────────────────────────────────────────────────────────┘
```

---

## 第一步：Mac本机安装依赖

```bash
cd /Users/dl/WorkBuddy/20260425075457/auto_trader
pip install -r requirements.txt
```

---

## 第二步：Windows虚拟机配置（同花顺模拟账户）

### 方案A：ths_trades WEB API（推荐，最稳定）

**1. 在Windows虚拟机克隆项目**
```bat
cd D:\
git clone https://github.com/sdasdfasd64565/ths_trades
cd ths_trades
```

**2. 安装Python依赖**
```bat
pip install -r requirements.txt
pip install pywinauto tornado requests
```

**3. 修改配置文件**
打开 `applications/API_Config.py`：
```python
cfg = {
    'exe_path': r'C:\同花顺软件\同花顺\xiadan.exe',  # 改成你的实际路径
    'sleepA': 0.2,
    'sleepB': 0.5,
    'sleepC': 1,
}
```

**4. 登录同花顺模拟账户**
- 打开同花顺 → 登录模拟账户
- 设置委托前确认为"否"
- 快速交易设置为"是"

**5. 启动ths_trades服务**
```bat
python app.py
```
> 保持此窗口运行，服务地址：http://127.0.0.1:6003

---

### 方案B：文件信号方式（跨平台通用）

**1. 配置Parallels共享文件夹**
- Parallels菜单 → 虚拟机设置 → 共享 → 添加Mac文件夹
- 例如：将 `/Users/dl/Shared` 共享到Windows
- Windows中访问路径：`Z:\`

**2. 修改Mac配置**
编辑 `config/settings.py`：
```python
VISION = {
    "signal_dir": "/Users/dl/Shared/trading_signals",
    "mode": "mock",
}
```

**3. 复制Windows执行器到虚拟机**
将 `vision/file_signal_executor_win.py` 复制到Windows虚拟机

**4. 安装Windows依赖**
```bat
pip install pyautogui pywinauto pillow pytesseract requests
```

**5. 安装Tesseract OCR**
- 下载：https://github.com/UB-Mannheim/tesseract/wiki
- 安装后修改 `file_signal_executor_win.py` 中的 `TESSERACT_CMD` 路径

**6. 启动执行器**
```bat
python file_signal_executor_win.py
```

---

## 第三步：运行模拟账户测试

**在Mac侧运行（模拟账户模式）**：
```bash
cd /Users/dl/WorkBuddy/20260425075457/auto_trader
python core/scheduler.py
```

> 模拟账户模式下，所有交易指令会标记为 `confirmed` 而不实际下单，用于验证策略逻辑。

**切换到实盘**：
修改 `config/settings.py`：
```python
VISION = {
    "mode": "live",  # 改为实盘
}
```

---

## 策略配置

编辑 `strategy/strategies.py` 或在 `config/settings.py` 中调整参数：

```python
STRATEGIES = {
    "002539_综合评分":  {"active": True,  "weight": 1.0},   # 主策略
    "002539_多周期MACD": {"active": True,  "weight": 0.9},   # 辅助
    "002539_半仓滚动":  {"active": False, "weight": 0.8},   # 关闭
    "002539_日内网格":  {"active": False, "weight": 0.7},
    "002539_均价偏离":  {"active": False, "weight": 0.6},
}
```

### 做T参数调优（002539）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| DROP_THRESHOLD | -1.2% | 跌超多少考虑买 |
| TAKE_PROFIT_PCT | 1.5% | 止盈目标 |
| STOP_LOSS_PCT | -2.0% | 止损线 |
| T_SHARES | 2400股 | 每次做T数量 |

---

## 文件结构

```
auto_trader/
├── core/
│   └── scheduler.py              # 主调度器 v2
├── data/
│   ├── market.py                # 多数据源行情（三重保障）
│   └── ashare.py                # Ashare开源行情API
├── strategy/
│   ├── indicators.py            # 技术指标库
│   ├── strategies.py            # 5种先进做T策略
│   └── engine.py                # 策略引擎 v2
├── vision/
│   ├── ths_api.py               # ths_trades WEB API客户端
│   └── file_signal_executor_win.py  # Windows执行器（复制到Win）
├── risk/
│   └── manager.py               # 风控模块
├── config/
│   └── settings.py              # 全局配置（改这里）
├── logs/                         # 交易日志
├── requirements.txt             # Mac依赖
└── DEPLOY.md                    # 本文件
```

---

## 数据源自动切换逻辑

```
请求行情
    ↓
① akshare（东方财富）→ 成功 → 缓存8秒
    ↓ 失败/被封
② Ashare（新浪+腾讯）→ 成功 → 缓存8秒
    ↓ 失败
③ 同花顺视觉OCR → 成功
    ↓ 全部失败
记录错误日志
```

**限流保护**：每60秒最多60次请求，超出自动休眠。

---

## 5种做T策略说明

| 策略 | 原理 | 适合场景 | 难度 |
|------|------|---------|------|
| 综合评分 | 多条件积分制 | 所有行情 | ⭐⭐ |
| 多周期MACD | 日线+60M+15M共振 | 趋势行情 | ⭐⭐⭐ |
| 半仓滚动 | 先买后卖/先卖后买 | 震荡行情 | ⭐⭐ |
| 日内网格 | 价格网格自动低买高卖 | 区间震荡 | ⭐⭐ |
| 均价偏离 | 价格偏离分时均价 | 日内T+0 | ⭐⭐⭐ |

---

## 常见问题

**Q: ths_trades服务无法启动？**
A: 检查同花顺xiadan.exe路径是否正确，确保已登录模拟账户

**Q: 文件信号方式信号没有被执行？**
A: 检查：1)共享文件夹路径是否正确 2)Windows执行器是否正在运行 3)parallels共享是否启用

**Q: 行情数据被封？**
A: 系统自动切换到Ashare备用源，无需手动干预

**Q: 想增加新的做T策略？**
A: 在 `strategy/strategies.py` 新建策略类，在 `strategy/engine.py` 中注册
