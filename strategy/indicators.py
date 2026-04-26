"""
技术指标计算库
所有指标基于K线数据列表计算
"""
import numpy as np
from typing import List, Optional


def _closes(klines: list) -> np.ndarray:
    return np.array([k["close"] for k in klines], dtype=float)

def _highs(klines: list) -> np.ndarray:
    return np.array([k["high"] for k in klines], dtype=float)

def _lows(klines: list) -> np.ndarray:
    return np.array([k["low"] for k in klines], dtype=float)

def _volumes(klines: list) -> np.ndarray:
    return np.array([k["volume"] for k in klines], dtype=float)


def MA(klines: list, period: int) -> Optional[float]:
    """简单移动平均"""
    closes = _closes(klines)
    if len(closes) < period:
        return None
    return float(np.mean(closes[-period:]))


def EMA(klines: list, period: int) -> Optional[float]:
    """指数移动平均"""
    closes = _closes(klines)
    if len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return float(ema)


def MACD(klines: list, fast=12, slow=26, signal=9) -> dict:
    """
    MACD指标
    返回: {macd, signal, histogram, cross}
    cross: 'golden'(金叉) / 'dead'(死叉) / None
    """
    closes = _closes(klines)
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "histogram": None, "cross": None}

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_sig = 2.0 / (signal + 1)

    ema_fast = closes[0]
    ema_slow = closes[0]
    dif_list = []

    for price in closes:
        ema_fast = price * k_fast + ema_fast * (1 - k_fast)
        ema_slow = price * k_slow + ema_slow * (1 - k_slow)
        dif_list.append(ema_fast - ema_slow)

    dea = dif_list[0]
    dea_list = []
    for dif in dif_list:
        dea = dif * k_sig + dea * (1 - k_sig)
        dea_list.append(dea)

    macd_val = dif_list[-1]
    dea_val = dea_list[-1]
    hist = (macd_val - dea_val) * 2

    # 判断金叉死叉（前一根 vs 当前根）
    cross = None
    if len(dif_list) >= 2:
        prev_diff = dif_list[-2] - dea_list[-2]
        curr_diff = dif_list[-1] - dea_list[-1]
        if prev_diff < 0 and curr_diff >= 0:
            cross = "golden"
        elif prev_diff > 0 and curr_diff <= 0:
            cross = "dead"

    return {
        "macd": round(macd_val, 4),
        "signal": round(dea_val, 4),
        "histogram": round(hist, 4),
        "cross": cross
    }


def KDJ(klines: list, n=9, m1=3, m2=3) -> dict:
    """
    KDJ指标
    返回: {k, d, j, signal}
    signal: 'overbought'(超买>80) / 'oversold'(超卖<20) / None
    """
    highs = _highs(klines)
    lows = _lows(klines)
    closes = _closes(klines)

    if len(closes) < n:
        return {"k": None, "d": None, "j": None, "signal": None}

    k_val = 50.0
    d_val = 50.0

    for i in range(n - 1, len(closes)):
        period_high = np.max(highs[max(0, i-n+1):i+1])
        period_low = np.min(lows[max(0, i-n+1):i+1])
        if period_high == period_low:
            rsv = 50.0
        else:
            rsv = (closes[i] - period_low) / (period_high - period_low) * 100
        k_val = (2/3) * k_val + (1/3) * rsv
        d_val = (2/3) * d_val + (1/3) * k_val

    j_val = 3 * k_val - 2 * d_val

    signal = None
    if k_val > 80 and d_val > 80:
        signal = "overbought"
    elif k_val < 20 and d_val < 20:
        signal = "oversold"

    return {
        "k": round(k_val, 2),
        "d": round(d_val, 2),
        "j": round(j_val, 2),
        "signal": signal
    }


def BOLL(klines: list, period=20, std_dev=2) -> dict:
    """
    布林带
    返回: {upper, mid, lower, position}
    position: 'above_upper'(超买) / 'below_lower'(超卖) / 'mid_upper' / 'mid_lower'
    """
    closes = _closes(klines)
    if len(closes) < period:
        return {"upper": None, "mid": None, "lower": None, "position": None}

    recent = closes[-period:]
    mid = float(np.mean(recent))
    std = float(np.std(recent, ddof=1))
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    price = closes[-1]

    if price > upper:
        position = "above_upper"
    elif price < lower:
        position = "below_lower"
    elif price > mid:
        position = "mid_upper"
    else:
        position = "mid_lower"

    return {
        "upper": round(upper, 3),
        "mid": round(mid, 3),
        "lower": round(lower, 3),
        "position": position
    }


def RSI(klines: list, period=14) -> Optional[float]:
    """相对强弱指数"""
    closes = _closes(klines)
    if len(closes) < period + 1:
        return None

    deltas = np.diff(closes[-(period+1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def VOLUME_RATIO(klines: list, period=5) -> Optional[float]:
    """量比（当前成交量/过去N日平均成交量）"""
    volumes = _volumes(klines)
    if len(volumes) < period + 1:
        return None
    avg = np.mean(volumes[-(period+1):-1])
    if avg == 0:
        return None
    return round(volumes[-1] / avg, 2)
