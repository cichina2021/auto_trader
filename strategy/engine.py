"""
策略引擎 v2 — 综合调度多个做T策略
策略优先级: 做T综合评分 > 多周期MACD > 半仓滚动 > 日内网格 > 均价偏离
"""
import logging
from typing import List, Optional
from data.market import market
from strategy.strategies import (
    T_Trade_002539, HalfPositionSwing, GridTactics,
    AvgPriceDeviation, MultiPeriodMACD, Signal
)
from config.settings import POSITIONS, STOCK_POOL_FILE

logger = logging.getLogger(__name__)


class StrategyEngine:
    """策略引擎 v2"""

    def __init__(self):
        # 初始化所有策略
        self.strategies = {
            "002539_综合评分": T_Trade_002539(),
            "002539_半仓滚动": HalfPositionSwing(),
            "002539_日内网格": GridTactics(),
            "002539_均价偏离": AvgPriceDeviation(),
            "002539_多周期MACD": MultiPeriodMACD(),
        }

        # 当前仓位状态
        self.t_shares_held = POSITIONS["002539"]["t_shares_held"]

        # 活跃策略（默认全开，可按需关闭）
        self.active_strategies = list(self.strategies.keys())

        logger.info(f"策略引擎 v2 启动，活跃策略: {self.active_strategies}")
        logger.info(f"当前做T持仓: {self.t_shares_held}股")

    def evaluate_all(self) -> List[Signal]:
        """
        评估所有策略，返回优先级最高的信号
        """
        signals = []

        # 获取行情数据
        quote = market.get_realtime_quote("002539")
        if not quote:
            logger.warning("获取002539行情失败")
            return []

        klines_daily = market.get_kline("002539", period="daily", limit=60)
        klines_60m = market.get_kline("002539", period="60", limit=40)
        klines_15m = market.get_kline("002539", period="15", limit=60)
        klines_5m = market.get_kline("002539", period="5", limit=60)

        logger.info(
            f"[002539] 价格={quote['price']} 涨幅={quote['change_pct']}% | "
            f"日线={len(klines_daily) if klines_daily else 0}条 "
            f"60M={len(klines_60m) if klines_60m else 0}条 "
            f"15M={len(klines_15m) if klines_15m else 0}条"
        )

        # 遍历各策略收集信号
        for name, strategy in self.strategies.items():
            if name not in self.active_strategies:
                continue

            try:
                sig = self._evaluate_strategy(
                    strategy, name, quote,
                    klines_daily, klines_60m, klines_15m, klines_5m
                )
                if sig:
                    signals.append(sig)
                    logger.info(f"  [{name}] 信号: {sig.action} {sig.shares}股 原因: {sig.reason} 置信度: {sig.confidence:.0%}")
            except Exception as e:
                logger.error(f"  [{name}] 评估异常: {e}")

        # 按置信度排序
        signals.sort(key=lambda s: s.confidence, reverse=True)

        # 合并同方向信号（可选）
        if len(signals) > 1:
            signals = self._merge_signals(signals)

        return signals

    def _evaluate_strategy(self, strategy, name: str, quote: dict,
                           kd, k60, k15, k5) -> Optional[Signal]:
        """调度单个策略"""
        if isinstance(strategy, T_Trade_002539):
            return strategy.evaluate(quote, kd, k60, k15, self.t_shares_held)
        elif isinstance(strategy, HalfPositionSwing):
            return strategy.evaluate(quote, k60, k15, self.t_shares_held)
        elif isinstance(strategy, GridTactics):
            return strategy.evaluate(quote, self.t_shares_held)
        elif isinstance(strategy, AvgPriceDeviation):
            return strategy.evaluate(quote, k15 or k5 or [], self.t_shares_held)
        elif isinstance(strategy, MultiPeriodMACD):
            return strategy.evaluate(quote, kd, k60, k15, self.t_shares_held)
        return None

    def _merge_signals(self, signals: List[Signal]) -> List[Signal]:
        """合并同方向信号"""
        if not signals:
            return []
        best = signals[0]
        logger.info(f"  最优信号: [{best.strategy}] {best.action} {best.shares}股 @{best.price} 置信度: {best.confidence:.0%}")
        return [best]

    def update_position(self, code: str, action: str, shares: int, price: float):
        """交易执行后更新仓位"""
        if code == "002539":
            if action == "BUY":
                self.t_shares_held += shares
                logger.info(f"[002539] 买入{shares}股@{price}，做T持仓={self.t_shares_held}")
            elif action == "SELL":
                self.t_shares_held -= shares
                logger.info(f"[002539] 卖出{shares}股@{price}，做T持仓={self.t_shares_held}")

    def set_strategy_active(self, name: str, active: bool):
        """开关策略"""
        if active and name not in self.active_strategies:
            self.active_strategies.append(name)
            logger.info(f"策略 {name} 已启用")
        elif not active and name in self.active_strategies:
            self.active_strategies.remove(name)
            logger.info(f"策略 {name} 已禁用")
