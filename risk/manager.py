"""
风控模块：仓位管理 + 止损 + 每日限额
"""
import logging
from datetime import datetime, date
from typing import Dict
from config.settings import RISK

logger = logging.getLogger(__name__)


class RiskManager:
    """风控管理器"""

    def __init__(self):
        self.daily_pnl: float = 0.0           # 今日盈亏（元）
        self.daily_trade_count: int = 0        # 今日交易次数
        self.trade_date: date = date.today()
        self.is_halted: bool = False           # 是否触发熔断（停止交易）
        self.halt_reason: str = ""

        # 今日交易记录
        self.trades: list = []

    def _reset_if_new_day(self):
        today = date.today()
        if today != self.trade_date:
            self.daily_pnl = 0.0
            self.daily_trade_count = 0
            self.trade_date = today
            self.is_halted = False
            self.halt_reason = ""
            self.trades = []
            logger.info(f"新交易日 {today}，风控数据已重置")

    def can_trade(self, code: str, action: str, shares: int, price: float) -> tuple[bool, str]:
        """
        检查是否允许交易
        返回: (允许, 原因)
        """
        self._reset_if_new_day()

        # 1. 熔断检查
        if self.is_halted:
            return False, f"风控熔断: {self.halt_reason}"

        # 2. 每日亏损上限
        if self.daily_pnl <= -abs(RISK["max_daily_loss_pct"]) * 100000:  # 假设10万本金
            self._halt(f"当日亏损已达上限 {self.daily_pnl:.0f}元")
            return False, self.halt_reason

        # 3. 每日最大交易次数（做T一天最多10次）
        if self.daily_trade_count >= 10:
            return False, f"今日交易次数已达上限({self.daily_trade_count}次)"

        return True, "OK"

    def record_trade(self, code: str, action: str, shares: int, price: float, pnl: float = 0):
        """记录交易"""
        self._reset_if_new_day()
        self.daily_trade_count += 1
        self.daily_pnl += pnl
        trade = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "code": code,
            "action": action,
            "shares": shares,
            "price": price,
            "pnl": pnl,
        }
        self.trades.append(trade)
        logger.info(f"交易记录: {action} {code} {shares}股@{price} PnL={pnl:.1f}")

        # 实时检查亏损
        if self.daily_pnl < -5000:  # 单日亏损超5000元触发熔断
            self._halt(f"当日亏损{self.daily_pnl:.0f}元，超过安全阈值")

    def _halt(self, reason: str):
        self.is_halted = True
        self.halt_reason = reason
        logger.critical(f"🚨 风控熔断！{reason}")

    def get_summary(self) -> dict:
        """返回今日风控摘要"""
        return {
            "date": str(self.trade_date),
            "daily_pnl": round(self.daily_pnl, 2),
            "trade_count": self.daily_trade_count,
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "trades": self.trades,
        }
