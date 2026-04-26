# ============================================================
# AutoTrader 全局配置 v2
# ============================================================

from pathlib import Path

# ---- 持仓配置 ----
POSITIONS = {
    "002539": {
        "name": "云图控股",
        "base_shares": 15300,       # 底仓，不动
        "base_cost": 10.731,        # 底仓成本价
        "t_shares": 2400,           # 做T仓位，用于自动买卖
        "t_shares_held": 2400,      # 当前持有做T仓位（运行时动态更新）
    }
}

# ---- 自选股池 ----
STOCK_POOL_FILE = "/Users/dl/.qclaw/workspace/StockSel/data/my_stock_pool.txt"

# ---- 交易时间 ----
TRADE_START = "09:30"
TRADE_END = "14:57"               # 14:57停止，留3分钟缓冲
LUNCH_START = "11:30"
LUNCH_END = "13:00"

# ---- 主循环间隔（秒）----
LOOP_INTERVAL = 30                # 每30秒检查一次信号

# ---- 风控参数 ----
RISK = {
    "max_daily_loss_pct": 0.02,   # 单日最大亏损2%触发停止
    "max_daily_loss_abs": 5000,   # 单日最大亏损金额（元）
    "single_trade_max_pct": 0.15,  # 单次最大仓位占比
    "stop_loss_pct": 2.0,         # 单次止损2%
    "take_profit_pct": 1.5,       # 单次止盈1.5%
    "max_daily_trades": 10,        # 每日最大交易次数
}

# ---- 多数据源行情配置 ----
DATA_SOURCE_PRIORITY = ["akshare", "ashare", "ths_ocr"]
DATA_RATE_LIMIT = 60             # 每60秒最多请求次数

# ---- 视觉交易层配置 ----
VISION = {
    # 执行模式: mock=模拟账户, live=实盘
    "mode": "mock",

    # ths_trades WEB API（优先使用，需在Win虚拟机部署）
    # 安装: git clone https://github.com/sdasdfasd64565/ths_trades
    # 启动: python app.py（保持运行）
    "ths_web_host": "127.0.0.1",
    "ths_web_port": 6003,

    # 文件信号方式（跨平台备份）
    "signal_dir": "/Volumes/pclouds/Shared/trading_signals",  # Parallels共享文件夹

    # jqtrader路径（备用）
    "ths_exe_path": r"C:\同花顺软件\同花顺\xiadan.exe",
    "tesseract_cmd": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
}

# ---- 策略配置 ----
STRATEGIES = {
    "002539_综合评分": {"active": True,  "weight": 1.0},
    "002539_多周期MACD": {"active": True,  "weight": 0.9},
    "002539_半仓滚动": {"active": True,  "weight": 0.8},
    "002539_日内网格": {"active": False, "weight": 0.7},
    "002539_均价偏离": {"active": False, "weight": 0.6},
}

# ---- 日志配置 ----
LOG_DIR = Path("/Users/dl/WorkBuddy/20260425075457/auto_trader/logs")
LOG_LEVEL = "INFO"
