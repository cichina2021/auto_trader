"""
先进做T策略库 — 融合多种主流量化策略
每个策略返回 Signal 或 None
大哥可直接修改参数使用
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional, List
from strategy.indicators import MA, EMA, MACD, KDJ, BOLL, RSI, VOLUME_RATIO


@dataclass
class Signal:
    """交易信号"""
    action: str           # 'BUY' / 'SELL' / 'HOLD'
    price: Optional[float]
    shares: int
    reason: str
    strategy: str         # 来源策略名
    confidence: float = 0.0   # 0~1


# ============================================================
# 云图控股(002539)做T策略 — 综合评分制
# ============================================================

class T_Trade_002539:
    """
    云图控股做T策略 v2.0 — 综合评分制

    【买入评分项】(多周期共振，任意3项触发买入)
    - 当日跌幅 ≥ DROP_THRESHOLD
    - 60分钟MACD即将/已经金叉
    - 日线KDJ超卖(K<25)
    - 价格跌破布林下轨
    - 60分钟价格站上MA5均线
    - 量比 > 1.8

    【卖出评分项】(任意1项触发卖出)
    - 浮盈 ≥ TAKE_PROFIT_PCT
    - 浮亏 ≤ STOP_LOSS_PCT（止损）
    - 60分钟MACD死叉
    - 日线KDJ超买(K>80)且有浮盈
    - 价格触及布林上轨
    """

    T_SHARES = 2400               # 做T仓位
    DROP_THRESHOLD = -1.2         # 跌幅阈值（%）
    TAKE_PROFIT_PCT = 1.5         # 止盈（%）
    STOP_LOSS_PCT = -2.0          # 止损（%）
    MIN_BUY_GAP_MIN = 25         # 两次买入最小间隔（分钟）

    def __init__(self):
        self.last_buy_price: Optional[float] = None
        self.last_buy_time: Optional[str] = None
        self.pending_t_shares_held: int = 2400  # 假设初始空仓

    def evaluate(self, quote: dict, klines_daily: list, klines_60m: list,
                 klines_15m: list, t_shares_held: int) -> Optional[Signal]:
        price = quote["price"]
        change_pct = quote["change_pct"]
        self.pending_t_shares_held = t_shares_held

        if t_shares_held == 0:
            return self._check_buy(price, change_pct, klines_daily, klines_60m, klines_15m)
        else:
            return self._check_sell(price, change_pct, klines_daily, klines_60m, klines_15m)

    def _check_buy(self, price, change_pct, kd, k60, k15) -> Optional[Signal]:
        score = 0
        reasons = []

        # 1. 跌幅触发
        if change_pct <= self.DROP_THRESHOLD:
            score += 1
            reasons.append(f"跌幅{change_pct:.1f}%")

        # 2. MACD 60分钟
        if k60:
            macd = MACD(k60)
            if macd["cross"] == "golden":
                score += 2
                reasons.append("60M MACD金叉")
            elif macd["histogram"] and macd["histogram"] > 0:
                score += 1
                reasons.append("60M MACD红柱")

        # 3. KDJ超卖
        if kd:
            kdj = KDJ(kd)
            if kdj["k"] and kdj["k"] < 25:
                score += 1
                reasons.append(f"日线KDJ超卖K={kdj['k']:.0f}")
            elif kdj["k"] and kdj["k"] < 40:
                score += 0.5
                reasons.append(f"日线KDJ偏低K={kdj['k']:.0f}")

        # 4. 布林下轨
        if kd:
            boll = BOLL(kd)
            if boll["position"] == "below_lower":
                score += 2
                reasons.append("跌破布林下轨")
            elif boll["position"] == "mid_lower":
                score += 1
                reasons.append("贴近布林下轨")

        # 5. 站上MA5
        if k60:
            ma5 = MA(k60, 5)
            if ma5 and price >= ma5:
                score += 1
                reasons.append("价格≥MA5")

        # 6. 量比
        if kd:
            vr = VOLUME_RATIO(kd)
            if vr and vr > 1.8:
                score += 1
                reasons.append(f"量比{vr:.1f}")

        if score >= 3:
            self.last_buy_price = price
            self.last_buy_time = datetime.now().strftime("%H:%M")
            return Signal(
                action="BUY", price=price, shares=self.T_SHARES,
                reason="+".join(reasons), strategy="002539做T综合评分",
                confidence=min(score / 6, 1.0)
            )
        return None

    def _check_sell(self, price, change_pct, kd, k60, k15) -> Optional[Signal]:
        if not self.last_buy_price:
            return None

        profit_pct = (price - self.last_buy_price) / self.last_buy_price * 100
        reasons = []

        # 止损
        if profit_pct <= self.STOP_LOSS_PCT:
            return Signal(
                action="SELL", price=price, shares=self.pending_t_shares_held,
                reason=f"止损 {profit_pct:.1f}%", strategy="002539做T综合评分", confidence=1.0
            )

        # 止盈
        if profit_pct >= self.TAKE_PROFIT_PCT:
            return Signal(
                action="SELL", price=price, shares=self.pending_t_shares_held,
                reason=f"止盈 +{profit_pct:.1f}%", strategy="002539做T综合评分", confidence=1.0
            )

        # MACD死叉
        if k60:
            macd = MACD(k60)
            if macd["cross"] == "dead" and profit_pct > 0.3:
                return Signal(
                    action="SELL", price=price, shares=self.pending_t_shares_held,
                    reason=f"MACD死叉+浮盈{profit_pct:.1f}%", strategy="002539做T综合评分", confidence=0.85
                )

        # KDJ超买
        if kd and profit_pct > 0.5:
            kdj = KDJ(kd)
            if kdj["k"] and kdj["k"] > 80:
                return Signal(
                    action="SELL", price=price, shares=self.pending_t_shares_held,
                    reason=f"KDJ超买K={kdj['k']:.0f}", strategy="002539做T综合评分", confidence=0.75
                )

        # 触及布林上轨
        if kd:
            boll = BOLL(kd)
            if boll["position"] == "above_upper" and profit_pct > 0.5:
                return Signal(
                    action="SELL", price=price, shares=self.pending_t_shares_held,
                    reason=f"触及布林上轨+浮盈{profit_pct:.1f}%", strategy="002539做T综合评分", confidence=0.7
                )

        return None


# ============================================================
# 策略2：半仓滚动做T（经典基础策略）
# ============================================================

class HalfPositionSwing:
    """
    半仓滚动做T — 经典策略

    原理：
    - 保留50%资金作为机动
    - 日内低点买入半仓 → 高点卖出原仓（先买后卖）
    - 或日内高点卖出半仓 → 低点买回（先卖后买）

    适合：有一定盘感的投资者，震荡行情效果最好
    """

    T_SHARES = 2400           # 每次操作数量（半仓=1200股）
    DROP_THRESHOLD = -1.0     # 触发买入的跌幅
    RISE_THRESHOLD = 1.0      # 触发卖出的涨幅
    MAX_DAILY_ROUNDS = 3     # 每天最多滚动次数

    def __init__(self):
        self.rounds_today = 0
        self.last_trade_time = None

    def evaluate(self, quote: dict, klines_60m: list, klines_15m: list,
                 position_held: int) -> Optional[Signal]:
        """
        position_held: 当前持有的做T仓位
        """
        price = quote["price"]
        change_pct = quote["change_pct"]

        if position_held == 0:
            # 空仓，考虑先买后卖（买半仓）
            return self._buy_arm(price, change_pct, klines_60m, klines_15m)
        else:
            # 有仓，考虑先卖后买（卖半仓）
            return self._sell_arm(price, change_pct, klines_60m, klines_15m, position_held)

    def _buy_arm(self, price, change_pct, k60, k15) -> Optional[Signal]:
        if self.rounds_today >= self.MAX_DAILY_ROUNDS:
            return None

        score = 0
        reasons = []

        if change_pct <= self.DROP_THRESHOLD:
            score += 2
            reasons.append(f"跌幅{change_pct:.1f}%")

        if k60:
            macd = MACD(k60)
            if macd["cross"] == "golden":
                score += 2
                reasons.append("MACD金叉")

        if k15:
            boll = BOLL(k15, period=20, std_dev=2)
            if boll["position"] == "below_lower":
                score += 2
                reasons.append("15M跌破布林下轨")
            elif boll["position"] == "mid_lower":
                score += 1
                reasons.append("15M贴近布林下轨")

        if k15:
            vr = VOLUME_RATIO(k15)
            if vr and vr > 1.5:
                score += 1
                reasons.append(f"15M量比{vr:.1f}")

        if score >= 3:
            self.rounds_today += 1
            return Signal(
                action="BUY", price=price, shares=self.T_SHARES,
                reason="+".join(reasons), strategy="半仓滚动做T", confidence=min(score/5, 1.0)
            )
        return None

    def _sell_arm(self, price, change_pct, k60, k15, position_held) -> Optional[Signal]:
        # 先卖后买逻辑：有底仓的情况下，高点卖出半仓
        if change_pct >= self.RISE_THRESHOLD or (k60 and MACD(k60)["cross"] == "dead"):
            return Signal(
                action="SELL", price=price, shares=min(self.T_SHARES, position_held),
                reason=f"半仓高抛 涨幅{change_pct:.1f}%", strategy="半仓滚动做T", confidence=0.8
            )
        return None


# ============================================================
# 策略3：日内网格策略（最经典最主流）
# ============================================================

class GridTactics:
    """
    日内网格做T — 经典量化策略

    原理：
    - 设定价格区间和网格间距
    - 价格下跌到网格线 → 买入1格
    - 价格上升到网格线 → 卖出1格
    - 自动低买高卖，无需预测方向

    参数：
    - grid_pct: 网格间距（%），默认0.5%一格
    - max_grids: 最大网格层数（控制仓位上限）
    - base_price: 基准价格（开盘价或昨日收盘价）
    """

    T_SHARES = 2400
    GRID_PCT = 0.5            # 每格0.5%间距
    MAX_GRIDS = 5             # 最多5格（满仓）
    BASE_PRICE = None         # 自动用开盘价

    def __init__(self):
        self.grid_levels: List[float] = []
        self.current_grid: int = 0

    def evaluate(self, quote: dict, position_held: int) -> Optional[Signal]:
        price = quote["price"]

        # 初始化网格（用开盘价）
        if self.BASE_PRICE is None:
            self.BASE_PRICE = quote.get("open", price)

        # 构建网格（上下各MAX_GRIDS格）
        if not self.grid_levels:
            self.grid_levels = [
                self.BASE_PRICE * (1 - self.GRID_PCT / 100 * i)
                for i in range(-self.MAX_GRIDS, self.MAX_GRIDS + 1)
            ]
            self.grid_levels.sort()

        # 找当前价格最近的网格
        nearest_idx = min(range(len(self.grid_levels)),
                          key=lambda i: abs(self.grid_levels[i] - price))

        shares_per_grid = self.T_SHARES // (self.MAX_GRIDS * 2)

        # 价格下跌到下方网格 → 买入
        if price <= self.grid_levels[nearest_idx] and position_held < self.T_SHARES * self.MAX_GRIDS:
            return Signal(
                action="BUY", price=price, shares=shares_per_grid,
                reason=f"网格买入 格{nearest_idx - self.MAX_GRIDS} @{price:.3f}",
                strategy="日内网格", confidence=0.9
            )

        # 价格上涨到上方网格 → 卖出
        if nearest_idx > self.current_grid and position_held > 0:
            self.current_grid = nearest_idx
            return Signal(
                action="SELL", price=price, shares=min(shares_per_grid, position_held),
                reason=f"网格卖出 格{nearest_idx - self.MAX_GRIDS} @{price:.3f}",
                strategy="日内网格", confidence=0.9
            )

        return None


# ============================================================
# 策略4：分时均价偏离策略（日内T+0精华）
# ============================================================

class AvgPriceDeviation:
    """
    分时均价偏离策略

    原理：
    - 计算分时均价线（WAP = 成交额/成交量）
    - 价格偏离均价超过阈值时，回归概率大
    - 价格在均价下方且跌幅足够 → 买入
    - 价格在均线上方且涨幅足够 → 卖出

    核心参数：
    - deviation_threshold: 偏离阈值（%），偏离超过此值触发操作
    - volume_threshold: 量能阈值
    """

    T_SHARES = 2400
    DEVIATION_THRESHOLD = 0.8   # 偏离均价0.8%以上
    VOLUME_RATIO = 1.5          # 量比要求
    STOP_LOSS_PCT = -1.5        # 止损
    TAKE_PROFIT_PCT = 1.2      # 止盈

    def __init__(self):
        self.last_buy_price = None

    def _calc_wap(self, klines: list) -> Optional[float]:
        """计算加权平均价格（分时均价）"""
        if not klines or len(klines) < 5:
            return None
        total_amount = sum(k.get("amount", 0) for k in klines)
        total_volume = sum(k.get("volume", 0) for k in klines)
        if total_volume == 0:
            return None
        return total_amount / total_volume

    def evaluate(self, quote: dict, klines_min: list, position_held: int) -> Optional[Signal]:
        price = quote["price"]
        change_pct = quote["change_pct"]

        if len(klines_min) < 10:
            return None

        wap = self._calc_wap(klines_min)
        if not wap:
            return None

        deviation_pct = (price - wap) / wap * 100

        if position_held == 0:
            # 空仓：价格低于均价且偏离足够
            if deviation_pct <= -self.DEVIATION_THRESHOLD:
                vr = VOLUME_RATIO(klines_min) if klines_min else 1
                if vr >= self.VOLUME_RATIO:
                    self.last_buy_price = price
                    return Signal(
                        action="BUY", price=price, shares=self.T_SHARES,
                        reason=f"偏离均价{deviation_pct:.2f}% 量比{vr:.1f}",
                        strategy="均价偏离", confidence=min(abs(deviation_pct) / 2, 1.0)
                    )
        else:
            # 持仓：价格高于均价或止盈止损
            if not self.last_buy_price:
                return None

            profit_pct = (price - self.last_buy_price) / self.last_buy_price * 100

            if profit_pct <= self.STOP_LOSS_PCT:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason=f"均价偏离止损 {profit_pct:.1f}%", strategy="均价偏离", confidence=1.0
                )
            if profit_pct >= self.TAKE_PROFIT_PCT:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason=f"均价偏离止盈 +{profit_pct:.1f}%", strategy="均价偏离", confidence=1.0
                )
            if deviation_pct >= self.DEVIATION_THRESHOLD and profit_pct > 0.2:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason=f"回归均价+{deviation_pct:.2f}% +{profit_pct:.1f}%",
                    strategy="均价偏离", confidence=0.85
                )

        return None


# ============================================================
# 策略5：多周期MACD共振（机构级策略）
# ============================================================

class MultiPeriodMACD:
    """
    多周期MACD共振策略

    原理：
    - 同时观察日线、60分钟、15分钟三个周期的MACD
    - 多个周期同时出现金叉/死叉 → 信号更强
    - 日线决定方向（顺势），小周期决定精确买卖点

    评分：
    - 日线MACD金叉 +2分
    - 60分钟MACD金叉 +1.5分
    - 15分钟MACD金叉 +1分
    - 总分≥3分触发操作
    """

    T_SHARES = 2400
    TAKE_PROFIT_PCT = 2.0
    STOP_LOSS_PCT = -1.5

    def __init__(self):
        self.last_buy_price = None

    def _macd_cross_score(self, klines: list, period_name: str) -> float:
        if not klines or len(klines) < 35:
            return 0
        macd = MACD(klines)
        if macd["cross"] == "golden":
            return {"日线": 2.0, "60分钟": 1.5, "15分钟": 1.0, "5分钟": 0.5}.get(period_name, 0)
        return 0

    def _macd_dead_score(self, klines: list, period_name: str) -> float:
        if not klines or len(klines) < 35:
            return 0
        macd = MACD(klines)
        if macd["cross"] == "dead":
            return {"日线": 2.0, "60分钟": 1.5, "15分钟": 1.0, "5分钟": 0.5}.get(period_name, 0)
        return 0

    def evaluate(self, quote: dict,
                 klines_daily: list, klines_60m: list, klines_15m: list,
                 position_held: int) -> Optional[Signal]:

        price = quote["price"]

        if position_held == 0:
            # 买入：多周期共振金叉
            score = 0
            reasons = []
            score += self._macd_cross_score(klines_daily, "日线")
            if score >= 2: reasons.append("日线MACD金叉")
            score += self._macd_cross_score(klines_60m, "60分钟")
            if self._macd_cross_score(klines_60m, "60分钟") >= 1.5: reasons.append("60M MACD金叉")
            score += self._macd_cross_score(klines_15m, "15分钟")
            if self._macd_cross_score(klines_15m, "15分钟") >= 1: reasons.append("15M MACD金叉")

            if score >= 3.5:
                self.last_buy_price = price
                return Signal(
                    action="BUY", price=price, shares=self.T_SHARES,
                    reason="+".join(reasons), strategy="多周期MACD共振", confidence=min(score / 4.5, 1.0)
                )
        else:
            # 卖出：多周期共振死叉
            if not self.last_buy_price:
                return None

            profit_pct = (price - self.last_buy_price) / self.last_buy_price * 100

            if profit_pct <= self.STOP_LOSS_PCT:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason=f"止损 {profit_pct:.1f}%", strategy="多周期MACD共振", confidence=1.0
                )
            if profit_pct >= self.TAKE_PROFIT_PCT:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason=f"止盈 +{profit_pct:.1f}%", strategy="多周期MACD共振", confidence=1.0
                )

            score = 0
            reasons = []
            score += self._macd_dead_score(klines_60m, "60分钟")
            if self._macd_dead_score(klines_60m, "60分钟") >= 1.5: reasons.append("60M MACD死叉")
            score += self._macd_dead_score(klines_15m, "15分钟")
            if self._macd_dead_score(klines_15m, "15分钟") >= 1: reasons.append("15M MACD死叉")

            if score >= 2.5 and profit_pct > 0.3:
                return Signal(
                    action="SELL", price=price, shares=position_held,
                    reason="+".join(reasons) + f"+{profit_pct:.1f}%", strategy="多周期MACD共振",
                    confidence=min(score / 3.5, 1.0)
                )

        return None


from datetime import datetime
