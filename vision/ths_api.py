"""
视觉交易层 v2 — 三层执行方案

Layer 1: ths_trades WEB API（同花顺WEB下单接口，最优先）
  → Tornado服务 + pywinauto，监听 localhost:6003
  → 成功率最高，速度最快（~3秒/单）
  → 直接通过HTTP调用，无需模拟键鼠

Layer 2: jqtrader（同花顺pywinauto自动化）
  → pip install jqktrader，直接import使用
  → 自动识别验证码，稳定性好

Layer 3: 模拟键鼠（最后备用）
  → pyautogui + OCR，适合特殊场景

使用方式：
  Mac侧 → 发送HTTP请求到Windows虚拟机 → ths_trades执行
"""
import json
import time
import logging
import requests
from pathlib import Path
from typing import Optional
from config.settings import VISION

logger = logging.getLogger(__name__)


# ============================================================
# Layer 1: ths_trades WEB API 执行器
# ============================================================

class ThsWebTrader:
    """
    ths_trades WEB API 客户端
    对接 Windows虚拟机 上的 ths_trades 服务 (http://127.0.0.1:6003)

    特点：
    - WEB API方式，比键鼠模拟稳定
    - 支持队列下单，自动排队
    - 支持查询持仓/成交/委托
    - 单笔约3秒

    部署步骤：
    1. 在Windows虚拟机中下载ths_trades: git clone https://github.com/sdasdfasd64565/ths_trades
    2. pip install -r requirements.txt && pip install pywinauto
    3. 修改 applications/API_Config.py 中的 exe_path 为同花顺xiadan.exe路径
    4. 登录同花顺模拟账户
    5. python app.py 启动服务（保持运行）
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 6003):
        self.base_url = f"http://{host}:{port}"
        self._is_connected = False

    def is_service_alive(self) -> bool:
        """检查ths_trades服务是否在线"""
        try:
            r = requests.get(f"{self.base_url}/api/ping", timeout=3)
            return r.status_code == 200
        except:
            return False

    def send_order(self, strategy_no: str, code: str, name: str,
                   shares: int, operate: str) -> dict:
        """
        发送交易指令（市价单）

        参数：
            strategy_no: 策略编号
            code: 股票代码（如 '513030'）
            name: 股票名称（如 '德国30'）
            shares: 数量
            operate: 'buy' / 'sell'

        返回：API响应
        """
        payload = [{
            "strategy_no": strategy_no,
            "code": code,
            "name": name,
            "ct_amount": shares,
            "operate": operate,
        }]

        try:
            r = requests.post(
                f"{self.base_url}/api/queue",
                json=payload,
                timeout=30,
                headers={"Content-Type": "application/json"}
            )
            result = r.json()
            logger.info(f"ths_trades下单: {operate.upper()} {code} {shares}股 → {result}")
            return result
        except Exception as e:
            logger.error(f"ths_trades下单失败: {e}")
            return {"success": False, "error": str(e)}

    def send_limit_order(self, strategy_no: str, code: str, name: str,
                         shares: int, price: float, operate: str) -> dict:
        """发送限价单（如果ths_trades支持）"""
        # ths_trades基础版仅支持市价单，限价单需在同花顺界面预设
        return self.send_order(strategy_no, code, name, shares, operate)

    def get_position(self, strategy_no: str = "AUTO") -> dict:
        """查询持仓"""
        try:
            r = requests.post(
                f"{self.base_url}/api/search",
                json={"strategy_no": strategy_no, "operate": "get_position"},
                timeout=10
            )
            return r.json()
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return {}

    def get_today_trades(self, strategy_no: str = "AUTO") -> dict:
        """查询当日成交"""
        try:
            r = requests.post(
                f"{self.base_url}/api/search",
                json={"strategy_no": strategy_no, "operate": "get_today_trades"},
                timeout=10
            )
            return r.json()
        except Exception as e:
            logger.error(f"查询成交失败: {e}")
            return {}

    def get_today_entrusts(self, strategy_no: str = "AUTO") -> dict:
        """查询当日委托（推荐）"""
        try:
            r = requests.post(
                f"{self.base_url}/api/search",
                json={"strategy_no": strategy_no, "operate": "get_today_entrusts"},
                timeout=10
            )
            return r.json()
        except Exception as e:
            logger.error(f"查询委托失败: {e}")
            return {}

    def get_balance(self, strategy_no: str = "AUTO") -> dict:
        """查询资金余额"""
        try:
            r = requests.post(
                f"{self.base_url}/api/search",
                json={"strategy_no": strategy_no, "operate": "get_balance"},
                timeout=10
            )
            return r.json()
        except Exception as e:
            logger.error(f"查询余额失败: {e}")
            return {}


# ============================================================
# Layer 2: jqtrader 执行器（pip安装版）
# ============================================================

class JqkTrader:
    """
    jqtrader 同花顺自动化交易

    使用方式：
    1. Windows虚拟机 pip install jqktrader
    2. pip install pywinauto
    3. pip install pytesseract（需安装Tesseract OCR）
    4. 登录同花顺模拟账户
    5. from vision.ths_api import JqkTrader 使用

    备选方案，ths_trades WEB API无法使用时
    """

    _instance = None

    def __init__(self, exe_path: str = None, tesseract_path: str = None):
        self.exe_path = exe_path or r"C:\同花顺软件\同花顺\xiadan.exe"
        self.tesseract_path = tesseract_path or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        self._connected = False

    def connect(self) -> bool:
        """连接同花顺客户端"""
        try:
            import jqktrader
            self._trader = jqktrader.use()
            self._trader.connect(
                exe_path=self.exe_path,
                tesseract_cmd=self.tesseract_path
            )
            self._connected = True
            logger.info("jqktrader 连接成功")
            return True
        except ImportError:
            logger.error("jqktrader未安装，请运行: pip install jqktrader")
            return False
        except Exception as e:
            logger.error(f"jqktrader连接失败: {e}")
            return False

    def buy(self, code: str, price: float, shares: int) -> dict:
        """买入"""
        if not self._connected:
            self.connect()
        try:
            result = self._trader.buy(code, price, shares)
            logger.info(f"jqktrader买入: {code} {shares}股 @{price}")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"jqktrader买入失败: {e}")
            return {"success": False, "error": str(e)}

    def sell(self, code: str, price: float, shares: int) -> dict:
        """卖出"""
        if not self._connected:
            self.connect()
        try:
            result = self._trader.sell(code, price, shares)
            logger.info(f"jqktrader卖出: {code} {shares}股 @{price}")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"jqktrader卖出失败: {e}")
            return {"success": False, "error": str(e)}

    def position(self) -> list:
        """查询持仓"""
        if not self._connected:
            self.connect()
        try:
            return self._trader.position or []
        except Exception as e:
            logger.error(f"jqktrader查询持仓失败: {e}")
            return []


# ============================================================
# Layer 3: 文件信号方式（Mac-Windows跨平台）
# ============================================================

class FileSignalTrader:
    """
    通过共享文件夹传递交易信号（跨平台方案）

    Mac侧写入JSON → Windows虚拟机读取并执行
    """

    def __init__(self):
        self.signal_dir = Path(VISION["signal_dir"])
        self.signal_dir.mkdir(parents=True, exist_ok=True)
        self._processed = set()

    def publish(self, code: str, name: str, action: str,
                shares: int, price: float, reason: str, strategy: str) -> str:
        """发布交易信号到文件"""
        from datetime import datetime
        signal_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{code}_{action}"

        signal = {
            "id": signal_id,
            "code": code,
            "name": name,
            "action": action.upper(),
            "shares": shares,
            "price": price,
            "reason": reason,
            "strategy": strategy,
            "timestamp": datetime.now().isoformat(),
            "mode": "mock",           # mock=模拟账户, live=实盘
            "status": "pending",
        }

        path = self.signal_dir / f"{signal_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)

        logger.info(f"📤 信号已发布: {action.upper()} {code}({name}) {shares}股 @{price} | {reason}")
        return signal_id

    def wait_result(self, signal_id: str, timeout: int = 120) -> dict:
        """等待执行结果（120秒超时，同花顺模拟账户约3-5秒/单）"""
        path = self.signal_dir / f"{signal_id}.json"
        start = time.time()

        while time.time() - start < timeout:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    signal = json.load(f)
                if signal["status"] in ("done", "failed", "confirmed"):
                    return signal
            except FileNotFoundError:
                pass
            time.sleep(2)

        return {"status": "timeout", "id": signal_id}

    def get_result_sync(self, code: str, name: str, action: str,
                        shares: int, price: float, reason: str,
                        strategy: str, timeout: int = 120) -> dict:
        """发布并等待结果（一步到位）"""
        signal_id = self.publish(code, name, action, shares, price, reason, strategy)
        return self.wait_result(signal_id, timeout)


# ============================================================
# 统一执行器：自动选择最佳方案
# ============================================================

class UnifiedTrader:
    """
    统一执行器，自动选择可用方案

    优先级：ths_trades WEB API > jqtrader > 文件信号
    """

    def __init__(self):
        self.ths_web = ThsWebTrader()
        self.jqk = None   # 延迟初始化
        self.file_signal = FileSignalTrader()
        self._active = None

    def execute(self, code: str, name: str, action: str,
                shares: int, price: float, reason: str,
                strategy: str, mode: str = "mock") -> dict:
        """
        执行交易，自动选择最佳方案
        mode: 'mock'=模拟账户（默认），'live'=实盘
        """

        # 1. 优先尝试ths_trades WEB API
        if self.ths_web.is_service_alive():
            logger.info("使用 ths_trades WEB API 执行")
            self._active = "ths_web"
            result = self.ths_web.send_order(
                strategy_no="auto_trader",
                code=code,
                name=name,
                shares=shares,
                operate=action.lower()
            )
            return {"success": True, "method": "ths_web", "result": result}

        # 2. 降级：尝试jqktrader
        logger.info("ths_trades不可用，降级到 jqktrader")
        if self.jqk is None:
            self.jqk = JqkTrader()
        try:
            self._active = "jqktrader"
            if action.upper() == "BUY":
                result = self.jqk.buy(code, price, shares)
            else:
                result = self.jqk.sell(code, price, shares)
            return {"success": True, "method": "jqktrader", "result": result}
        except Exception as e:
            logger.warning(f"jqktrader也失败: {e}，降级到文件信号")

        # 3. 最后：文件信号方式
        logger.info("使用 文件信号 方式执行")
        self._active = "file_signal"
        result = self.file_signal.get_result_sync(
            code, name, action, shares, price, reason, strategy
        )
        return {"success": result.get("status") != "timeout",
                "method": "file_signal", "result": result}

    def get_position(self) -> dict:
        """查询持仓"""
        if self._active == "ths_web":
            return self.ths_web.get_position()
        elif self._active == "jqktrader" and self.jqk:
            return {"positions": self.jqk.position()}
        return {}
