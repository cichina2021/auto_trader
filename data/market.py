"""
多数据源行情层 — 三重保障自动切换
优先级: akshare → Ashare(新浪/腾讯) → 同花顺视觉OCR
"""
import time
import logging
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class MarketDataSource:
    """多数据源行情获取，自动降级"""

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = 8  # 缓存8秒
        self._active_source: str = "akshare"
        self._request_count = 0
        self._request_window_start = time.time()

    def get_realtime_quote(self, code: str) -> Optional[dict]:
        """获取实时行情，失败自动切换数据源"""
        # 检查缓存
        now = time.time()
        if code in self._cache:
            if now - self._cache_time.get(code, 0) < self._cache_ttl:
                return self._cache[code]

        # 限流：每分钟最多60次请求
        self._rate_limit()

        # 按优先级尝试
        sources = [
            ("akshare", self._akshare_quote),
            ("ashare",  self._ashare_quote),
            ("ths_ocr", self._ths_ocr_quote),
        ]

        for name, func in sources:
            try:
                quote = func(code)
                if quote and quote.get("price", 0) > 0:
                    self._active_source = name
                    self._cache[code] = quote
                    self._cache_time[code] = now
                    logger.debug(f"[{name}] 获取{code}成功: {quote['price']}")
                    return quote
            except Exception as e:
                logger.warning(f"[{name}] 获取{code}失败: {e}")

        logger.error(f"所有数据源均无法获取{code}行情")
        return None

    def _rate_limit(self):
        """限流：滑动窗口，每60秒最多60次"""
        self._request_count += 1
        elapsed = time.time() - self._request_window_start
        if elapsed >= 60:
            self._request_count = 1
            self._request_window_start = time.time()
        elif self._request_count > 55:
            sleep_time = 60 - elapsed
            if sleep_time > 0:
                logger.debug(f"触发限流，等待{sleep_time:.1f}秒")
                time.sleep(sleep_time)
                self._request_count = 1
                self._request_window_start = time.time()

    def _akshare_quote(self, code: str) -> Optional[dict]:
        """akshare 东方财富实时行情"""
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "code": code,
            "name": r.get('名称', ''),
            "price": float(r.get('最新价', 0)),
            "open": float(r.get('今开', 0)),
            "high": float(r.get('最高', 0)),
            "low": float(r.get('最低', 0)),
            "pre_close": float(r.get('昨收', 0)),
            "change_pct": float(r.get('涨跌幅', 0)),
            "volume": float(r.get('成交量', 0)),
            "amount": float(r.get('成交额', 0)),
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": "akshare",
        }

    def _ashare_quote(self, code: str) -> Optional[dict]:
        """Ashare 新浪/腾讯行情（无需token，免费）"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))

        try:
            # 尝试导入Ashare
            from data.ashare import get_price_simple
            df = get_price_simple(code, freq='1d', count=1)
            if df is not None and len(df) > 0:
                row = df.iloc[-1]
                change_pct = 0.0
                if 'close' in df.columns and len(df) > 1:
                    pre_close = df['close'].iloc[-2]
                    if pre_close > 0:
                        change_pct = (row['close'] - pre_close) / pre_close * 100

                return {
                    "code": code,
                    "name": self._code_to_name(code),
                    "price": float(row.get('close', 0)),
                    "open": float(row.get('open', 0)),
                    "high": float(row.get('high', 0)),
                    "low": float(row.get('low', 0)),
                    "pre_close": float(df['close'].iloc[-2]) if len(df) > 1 else float(row.get('close', 0)),
                    "change_pct": round(change_pct, 2),
                    "volume": float(row.get('volume', 0)),
                    "amount": float(row.get('amount', 0)),
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "source": "ashare",
                }
        except Exception as e:
            logger.debug(f"Ashare失败: {e}")
        return None

    def _ths_ocr_quote(self, code: str) -> Optional[dict]:
        """同花顺视觉OCR：从共享文件夹的截图读取行情（最后防线）"""
        # 读取同花顺行情区截图并OCR
        # 需要Windows侧定期截图并写入共享目录
        screenshot_dir = Path("/shared/screenshots")
        if not screenshot_dir.exists():
            return None

        # 查找最新的同花顺截图
        ths_screenshots = sorted(
            screenshot_dir.glob("ths_*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not ths_screenshots:
            return None

        # OCR识别
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(ths_screenshots[0])
            text = pytesseract.image_to_string(img, config='--psm 6')

            # 简单解析：找价格、涨跌幅等（需要根据实际截图格式定制）
            # 这里返回None，依赖ths_ocr_parser.py解析
            logger.debug(f"THS OCR截图识别结果: {text[:100]}")
        except Exception as e:
            logger.debug(f"THS OCR失败: {e}")
        return None

    def get_kline(self, code: str, period: str = "daily", limit: int = 60) -> Optional[list]:
        """获取K线数据（优先akshare，失败用Ashare）"""
        try:
            import akshare as ak
            if period == "daily":
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
                df = df.tail(limit)
                return df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount"
                })[["date", "open", "high", "low", "close", "volume", "amount"]].to_dict("records")
            else:
                freq_map = {"60": "60", "30": "30", "15": "15", "5": "5", "1": "1"}
                freq = freq_map.get(str(period), "5")
                df = ak.stock_zh_a_hist_min_em(symbol=code, period=freq, adjust="qfq")
                df = df.tail(limit)
                return df.rename(columns={
                    "时间": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount"
                })[["date", "open", "high", "low", "close", "volume", "amount"]].to_dict("records")
        except Exception as e:
            logger.warning(f"akshare K线失败，尝试Ashare: {e}")
            try:
                from data.ashare import get_price_simple
                freq_map = {"daily": "1d", "60": "60m", "30": "30m", "15": "15m", "5": "5m"}
                freq = freq_map.get(period, "1d")
                df = get_price_simple(code, freq=freq, count=limit)
                if df is not None:
                    return df.to_dict("records")
            except Exception as e2:
                logger.error(f"Ashare K线也失败: {e2}")
        return None

    def get_multiple_quotes(self, codes: List[str]) -> Dict[str, dict]:
        """批量获取行情"""
        result = {}
        for code in codes:
            q = self.get_realtime_quote(code)
            if q:
                result[code] = q
        return result

    @staticmethod
    def _code_to_name(code: str) -> str:
        """股票代码转名称（简单映射）"""
        names = {
            "002539": "云图控股", "000001": "平安银行", "600519": "贵州茅台",
            "000002": "万科A", "300750": "宁德时代",
        }
        return names.get(code, code)

    @staticmethod
    def is_trading_time() -> bool:
        """判断当前是否为交易时间"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.time()
        from datetime import time as dtime
        morning = dtime(9, 30) <= t <= dtime(11, 30)
        afternoon = dtime(13, 0) <= t <= dtime(14, 57)
        return morning or afternoon


# 全局单例
market = MarketDataSource()
