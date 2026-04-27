"""
auto_trader.exe — 全市场做T工具 (Windows 单文件版)
PyInstaller: pyinstaller --onefile --windowed --name auto_trader main.py
股票池: 108只 (bundled in EXE)
"""

import os, sys, json, time, logging, datetime, threading, hashlib
import subprocess
import requests
from pathlib import Path
from typing import Optional, List, Dict, Any

# ═══════════════════════════════════════════════════════
#  模式 & 配置区  ← 改这里切换
# ═══════════════════════════════════════════════════════
MODE = "mock"         # "mock"=模拟账户(不实际下单) | "live"=实盘
AUTO_SCAN = True      # True=全市场扫描108只 | False=只看KEY_CODES
THS_TRADES_HOST = "http://127.0.0.1:6003"  # ths_trades WEB API
PARALLELS_SIGNAL_DIR = None  # Parallels共享文件夹路径，留空=本机模式

# 底仓配置
BASE_POSITION = 15_300  # 底仓不动
T_POSITION    =  1_200  # 做T仓位
COST_PRICE     = 10.731  # 成本价

# 做T信号阈值
T_CONFIG = {
    "buy_drop_threshold": -0.5,   # 跌幅≥0.5%买
    "sell_rise_threshold": 0.5,   # 涨幅≥0.5%卖
    "macd_hist_threshold": 0.02, # MACD柱状图阈值
    "boll_lower_pct": 10,         # 布林下轨偏离%
    "boll_upper_pct": 10,         # 布林上轨偏离%
    "volume_ratio_min": 1.8,      # 量比最低要求
    "confidence_min": 65,          # 综合置信度最低要求(%)
}

# 重点盯盘股票（从108只中精选大盘/活跃/中小盘组合）
KEY_CODES = [
    "002539",  # 云图控股（主仓）
    "000625",  # 长安汽车
    "002415",  # 海康威视
    "601138",  # 工业富联
    "002594",  # 比亚迪
    "600690",  # 海尔智家
    "000333",  # 美的集团
    "002241",  # 歌尔股份
    "002049",  # 紫光国微
    "002230",  # 科大讯飞
    "002236",  # 大华股份
    "000651",  # 格力电器
    "600309",  # 万华化学
    "600519",  # 贵州茅台
    "601318",  # 中国平安
    "600016",  # 民生银行
    "000858",  # 五粮液
    "600887",  # 伊利股份
    "002714",  # 牧原股份
    "000002",  # 万科A
]

# ═══════════════════════════════════════════════════════
#  股票池 (108只，内嵌不依赖外部文件)
# ═══════════════════════════════════════════════════════
def _load_stock_pool():
    """加载股票池，优先读同目录json，没有则用KEY_CODES"""
    base = getattr(sys, '_MEIPASS', str(Path(__file__).parent))
    json_path = Path(base) / 'stock_pool.json'
    if json_path.exists():
        return json.loads(json_path.read_text(encoding='utf-8'))
    return [{"code": c, "name": ""} for c in KEY_CODES]

ALL_STOCKS = _load_stock_pool()
ALL_CODES = [s['code'] for s in ALL_STOCKS]

# ═══════════════════════════════════════════════════════
#  日志系统
# ═══════════════════════════════════════════════════════
def _setup_logging():
    log_dir = Path(os.environ.get('APPDATA', '.')) / 'auto_trader' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"trader_{datetime.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('trader')

log = _setup_logging()

# ═══════════════════════════════════════════════════════
#  数据源层 (akshare → 东方财富直接HTTP → 同花顺Sina)
# ═══════════════════════════════════════════════════════
_akshare_ok = True   # akshare是否可用
_last_request_time = 0.0
_request_lock = threading.Lock()

def _rate_limit():
    """防封：每秒最多1次请求"""
    global _last_request_time
    with _request_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_request_time = time.time()

def get_realtime_quote(codes: List[str]) -> List[Dict[str, Any]]:
    """
    获取实时行情，自动降级：
    1. akshare（东方财富）
    2. 新浪财经直接HTTP
    3. 腾讯财经直接HTTP
    """
    global _akshare_ok

    # ── 尝试1: akshare ──
    if _akshare_ok:
        _rate_limit()
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            result = []
            code_set = set(codes)
            for _, row in df.iterrows():
                sc = str(row.get('代码', '')).zfill(6)
                if sc in code_set:
                    result.append(_parse_em_row(row))
            if result:
                log.info(f"[数据源] akshare 成功获取 {len(result)} 只")
                return result
            _akshare_ok = False
        except Exception as e:
            log.warning(f"[数据源] akshare 失败: {e}，切换备用源")
            _akshare_ok = False

    # ── 尝试2: 新浪财经批量API ──
    try:
        _rate_limit()
        sina_url = f"http://hq.sinajs.cn/list={','.join(codes)}"
        headers = {'Referer': 'http://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
        r = requests.get(sina_url, headers=headers, timeout=8)
        r.encoding = 'gbk'
        lines = r.text.strip().split('\n')
        result = []
        for line in lines:
            m = line.split('=')
            if len(m) < 2 or not m[1].strip():
                continue
            code = m[0].split('_')[-1]
            parts = m[1].strip().replace('"', '').split(',')
            if len(parts) < 10:
                continue
            result.append({
                'code': code.zfill(6),
                'name': parts[0],
                'price': float(parts[3]) if parts[3] not in ('', '0') else 0,
                'change_pct': float(parts[3]) - float(parts[2]) if parts[2] not in ('', '0') else 0,
                'volume_ratio': 0,
                'volume': float(parts[8]) if len(parts) > 8 and parts[8] else 0,
                'high': float(parts[4]) if parts[4] not in ('', '0') else 0,
                'low': float(parts[5]) if parts[5] not in ('', '0') else 0,
                'open': float(parts[1]) if parts[1] not in ('', '0') else 0,
                'prev_close': float(parts[2]) if parts[2] not in ('', '0') else 0,
            })
        if result:
            log.info(f"[数据源] 新浪财经 成功获取 {len(result)} 只")
            return result
    except Exception as e:
        log.warning(f"[数据源] 新浪财经失败: {e}")

    # ── 尝试3: 腾讯财经 ──
    try:
        _rate_limit()
        qt_codes = [f"sh{c}" if c.startswith(('6', '5')) else f"sz{c}" for c in codes]
        url = f"https://qt.gtimg.cn/q={','.join(qt_codes)}"
        r = requests.get(url, timeout=8)
        r.encoding = 'gbk'
        lines = r.text.strip().split('\n')
        result = []
        for line in lines:
            if '="pvts"' in line or len(line) < 50:
                continue
            parts = line.split('~')
            if len(parts) < 50:
                continue
            code_raw = parts[0].split('_')[-1] if '_' in parts[0] else parts[0]
            result.append({
                'code': code_raw,
                'name': parts[1],
                'price': float(parts[3]) if parts[3] not in ('', '-') else 0,
                'change_pct': float(parts[31]) if parts[31] not in ('', '-') else 0,
                'volume_ratio': float(parts[37]) if len(parts) > 37 and parts[37] not in ('', '-') else 0,
                'volume': float(parts[36]) if len(parts) > 36 and parts[36] not in ('', '-') else 0,
                'high': float(parts[33]) if parts[33] not in ('', '-') else 0,
                'low': float(parts[34]) if parts[34] not in ('', '-') else 0,
                'open': float(parts[5]) if parts[5] not in ('', '-') else 0,
                'prev_close': float(parts[4]) if parts[4] not in ('', '-') else 0,
            })
        if result:
            log.info(f"[数据源] 腾讯财经 成功获取 {len(result)} 只")
            return result
    except Exception as e:
        log.warning(f"[数据源] 腾讯财经失败: {e}")

    log.error("[数据源] 所有数据源均失败！")
    return []

def _parse_em_row(row) -> Dict[str, Any]:
    """解析东方财富行情行"""
    code = str(row.get('代码', '')).zfill(6)
    price = row.get('最新价', 0) or 0
    prev = row.get('昨收', 0) or 0
    chg = float(price) - float(prev)
    chg_pct = (chg / float(prev) * 100) if float(prev) > 0 else 0
    return {
        'code': code,
        'name': row.get('名称', ''),
        'price': float(price),
        'change_pct': round(chg_pct, 2),
        'volume_ratio': float(row.get('量比', 0) or 0),
        'volume': float(row.get('成交额', 0) or 0),
        'high': float(row.get('最高', 0) or 0),
        'low': float(row.get('最低', 0) or 0),
        'open': float(row.get('今开', 0) or 0),
        'prev_close': float(prev),
    }

# ═══════════════════════════════════════════════════════
#  历史K线获取 (akshare → 新浪分时 → 腾讯K线)
# ═══════════════════════════════════════════════════════
def get_kline(code: str, period: str = "daily", count: int = 60) -> Optional[Dict]:
    """
    获取K线数据
    period: daily | weekly | monthly | 60min | 30min | 15min | 5min
    """
    _rate_limit()
    try:
        import akshare as ak
        symbol = f"{code}.SH" if code.startswith(('6', '5')) else f"{code}.SZ"
        df = ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq", count=count)
        if df is not None and len(df) > 5:
            closes = df['收盘'].tolist()
            highs = df['最高'].tolist()
            lows = df['最低'].tolist()
            vols = df['成交量'].tolist()
            return {'close': closes, 'high': highs, 'low': lows, 'volume': vols,
                    'code': code}
    except Exception as e:
        log.debug(f"[K线] {code} akshare失败: {e}")

    # 备用: 用腾讯5档+估算
    return _get_kline_fallback(code, count)

def _get_kline_fallback(code: str, count: int) -> Optional[Dict]:
    """通过腾讯财经获取简化K线"""
    try:
        qt_code = f"sh{code}" if code.startswith(('6', '5')) else f"sz{code}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={qt_code},day,,,{count},qfq"
        r = requests.get(url, timeout=8)
        r.encoding = 'utf-8'
        text = r.text
        import re
        m = re.search(r'data:\\["([^\]]+)"', text)
        if not m:
            return None
        raw = m.group(1)
        bars = re.findall(r'\[([^\]]+)\]', raw)
        closes, highs, lows, vols = [], [], [], []
        for bar in bars[-count:]:
            parts = bar.split(',')
            if len(parts) >= 6:
                closes.append(float(parts[1]))
                highs.append(float(parts[2]))
                lows.append(float(parts[3]))
                vols.append(float(parts[4]))
        return {'close': closes, 'high': highs, 'low': lows, 'volume': vols, 'code': code}
    except Exception as e:
        log.debug(f"[K线备用] {code} 失败: {e}")
        return None

# ═══════════════════════════════════════════════════════
#  技术指标计算
# ═══════════════════════════════════════════════════════
def calc_ma(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calc_ema(prices: List[float], period: int) -> float:
    if not prices:
        return 0
    if len(prices) < 2:
        return prices[-1]
    k = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    if len(prices) < slow:
        return 0, 0, 0
    ema_fast = _ema_series(prices, fast)
    ema_slow = _ema_series(prices, slow)
    dif = ema_fast - ema_slow
    dea = _ema_single(list(zip(ema_fast, ema_slow)), signal)
    bar = 2 * (dif - dea)
    return round(dif, 4), round(dea, 4), round(bar, 4)

def _ema_series(prices: List[float], period: int) -> List[float]:
    k = 2 / (period + 1)
    ema = [prices[0]]
    for p in prices[1:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema

def _ema_single(pairs: List, period: int) -> float:
    if not pairs:
        return 0
    k = 2 / (period + 1)
    dif_list = [a - b for a, b in pairs]
    ema = dif_list[0]
    for d in dif_list[1:]:
        ema = d * k + ema * (1 - k)
    return ema

def calc_kdj(highs: List[float], lows: List[float], closes: List[float],
             n: int = 9, m1: int = 3, m2: int = 3) -> tuple:
    if len(closes) < n:
        return 50, 50, 50
    k_vals, d_vals = [50], [50]
    rsv = []
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv_val = (closes[i] - ll) / (hh - ll) * 100 if hh > ll else 50
        rsv.append(rsv_val)
    for r in rsv:
        k_vals.append(r / 3 + k_vals[-1] * 2 / 3)
        d_vals.append(k_vals[-1] / m1 + d_vals[-1] * (m1 - 1) / m1)
    k = round(k_vals[-1], 2)
    d = round(d_vals[-1], 2)
    j = round(3 * k - 2 * d, 2)
    return k, d, j

def calc_boll(closes: List[float], period: int = 20, multiplier: float = 2.0):
    if len(closes) < period:
        return 0, 0, 0
    recent = closes[-period:]
    mid = sum(recent) / period
    std = (sum((x - mid) ** 2 for x in recent) / period) ** 0.5
    upper = mid + multiplier * std
    lower = mid - multiplier * std
    return round(upper, 3), round(mid, 3), round(lower, 3)

# ═══════════════════════════════════════════════════════
#  做T信号计算 (5种策略融合)
# ═══════════════════════════════════════════════════════
def calc_t_signals(code: str, quote: Dict, kline: Optional[Dict] = None) -> Dict:
    """
    综合5种策略计算做T信号
    返回: {confidence, action, reason, strategies}
    """
    price = quote.get('price', 0)
    change_pct = quote.get('change_pct', 0)
    vol_ratio = quote.get('volume_ratio', 0)
    prev_close = quote.get('prev_close', price)

    if not kline or len(kline.get('close', [])) < 30:
        kline = get_kline(code)

    signals = {}
    scores = []

    # ── 策略1: 跌幅买 / 涨幅卖 (基础分 0-30) ──
    s1_score = 0
    if change_pct <= -T_CONFIG['buy_drop_threshold']:
        s1_score = min(30, abs(change_pct) * 8)
        s1_action = "买"
    elif change_pct >= T_CONFIG['sell_rise_threshold']:
        s1_score = min(30, change_pct * 8)
        s1_action = "卖"
    else:
        s1_action = "观望"
    signals['跌幅买/涨幅卖'] = {'score': s1_score, 'action': s1_action,
                                'detail': f"涨跌:{change_pct:+.2f}%"}
    scores.append(s1_score)

    # ── 策略2: MACD多周期共振 (0-25) ──
    macd_score = 0
    macd_action = "观望"
    if kline and len(kline.get('close', [])) >= 30:
        closes = kline['close']
        highs = kline.get('high', closes)
        lows = kline.get('low', closes)
        dif, dea, bar = calc_macd(closes)
        k, d, j = calc_kdj(highs, lows, closes)
        # 60分钟MACD
        k60 = get_kline(code, '60min', 60)
        dif60 = dea60 = bar60 = 0
        if k60 and len(k60.get('close', [])) >= 30:
            dif60, dea60, bar60 = calc_macd(k60['close'])
        # 15分钟MACD
        k15 = get_kline(code, '30min', 30)
        dif15 = dea15 = bar15 = 0
        if k15 and len(k15.get('close', [])) >= 20:
            dif15, dea15, bar15 = calc_macd(k15['close'], 8, 16, 6)

        # 多周期金叉共振
        hist_positive = bar > 0 and bar60 > 0
        hist_negative = bar < 0 and bar60 < 0
        if hist_positive and bar15 > 0 and k < d:
            macd_score = 25
            macd_action = "买"
        elif hist_negative and bar15 < 0 and k > d:
            macd_score = 25
            macd_action = "卖"
        elif bar > 0 and bar60 > 0:
            macd_score = 18
            macd_action = "买(次级)"
        elif bar < 0 and bar60 < 0:
            macd_score = 18
            macd_action = "卖(次级)"

        macd_detail = f"DIF:{dif:.3f} DEA:{dea:.3f} 柱:{bar:.3f} K:{k:.1f} D:{d:.1f}"
    else:
        macd_detail = "K线不足"
    signals['MACD多周期'] = {'score': macd_score, 'action': macd_action, 'detail': macd_detail}
    scores.append(macd_score)

    # ── 策略3: 布林带回归 (0-20) ──
    boll_score = 0
    boll_action = "观望"
    if kline and len(kline.get('close', [])) >= 25:
        closes = kline['close']
        upper, mid, lower = calc_boll(closes)
        pos = (price - lower) / (upper - lower) * 100 if upper > lower else 50
        if pos <= 15:  # 触及下轨
            boll_score = min(20, (15 - pos) * 1.5 + 8)
            boll_action = "买"
        elif pos >= 85:  # 触及上轨
            boll_score = min(20, (pos - 85) * 1.5 + 8)
            boll_action = "卖"
        boll_detail = f"上:{upper:.2f} 中:{mid:.2f} 下:{lower:.2f} 位置:{pos:.0f}%"
    else:
        boll_detail = "布林数据不足"
    signals['布林带回归'] = {'score': boll_score, 'action': boll_action, 'detail': boll_detail}
    scores.append(boll_score)

    # ── 策略4: 量比异动 + KDJ超卖/超买 (0-15) ──
    vol_score = 0
    vol_action = "观望"
    if vol_ratio >= T_CONFIG['volume_ratio_min']:
        if change_pct < 0:  # 下跌放量
            vol_score = min(15, vol_ratio * 4)
            vol_action = "买"
        elif change_pct > 0:  # 上涨放量
            vol_score = min(15, vol_ratio * 4)
            vol_action = "卖"
    if kline and len(kline.get('close', [])) >= 15:
        closes = kline['close']
        highs = kline.get('high', closes)
        lows = kline.get('low', closes)
        k, d, j = calc_kdj(highs, lows, closes)
        if j < 20:  # KDJ超卖
            vol_score = max(vol_score, 12)
            vol_action = "买"
        elif j > 80:  # KDJ超买
            vol_score = max(vol_score, 12)
            vol_action = "卖"
    signals['量价异动'] = {'score': vol_score, 'action': vol_action, 'detail': f"量比:{vol_ratio:.1f}"}
    scores.append(vol_score)

    # ── 策略5: 均价偏离 + 日内趋势 (0-10) ──
    ma_score = 0
    ma_action = "观望"
    if kline and len(kline.get('close', [])) >= 5:
        ma5 = calc_ma(kline['close'], 5)
        ma10 = calc_ma(kline['close'], 10)
        ma20 = calc_ma(kline['close'], 20)
        dev5 = (price - ma5) / ma5 * 100 if ma5 else 0
        if dev5 <= -1.5:
            ma_score = min(10, abs(dev5) * 4)
            ma_action = "买"
        elif dev5 >= 1.5:
            ma_score = min(10, dev5 * 4)
            ma_action = "卖"
        ma_detail = f"MA5:{ma5:.2f} MA10:{ma10:.2f} 偏离:{dev5:+.2f}%"
    else:
        ma_detail = "均线数据不足"
    signals['均价偏离'] = {'score': ma_score, 'action': ma_action, 'detail': ma_detail}
    scores.append(ma_score)

    # ── 综合评分 ──
    total = sum(scores)
    max_possible = 100
    confidence = round(total / max_possible * 100, 1)

    # 决策：综合评分 + 多数策略方向一致
    buy_count = sum(1 for s in signals.values() if s['action'] in ('买', '买(次级)'))
    sell_count = sum(1 for s in signals.values() if s['action'] in ('卖', '卖(次级)'))

    if confidence >= T_CONFIG['confidence_min'] and buy_count > sell_count and buy_count >= 2:
        action = "买"
        reason = f"置信度{confidence}% | 买信号{buy_count}个 | {change_pct:+.2f}%"
    elif confidence >= T_CONFIG['confidence_min'] and sell_count > buy_count and sell_count >= 2:
        action = "卖"
        reason = f"置信度{confidence}% | 卖信号{sell_count}个 | {change_pct:+.2f}%"
    elif change_pct <= -1.0 and vol_ratio >= 1.5:  # 特殊情况：大幅下跌+放量
        action = "买"
        confidence = max(confidence, 75)
        reason = f"异动买入 | 跌幅{change_pct:+.2f}% | 量比{vol_ratio:.1f}"
    elif change_pct >= 1.0 and vol_ratio >= 1.5:
        action = "卖"
        confidence = max(confidence, 75)
        reason = f"异动卖出 | 涨幅{change_pct:+.2f}% | 量比{vol_ratio:.1f}"
    else:
        action = "观望"
        reason = f"置信度不足({confidence}%) | 信号分散"

    return {
        'code': code,
        'name': quote.get('name', code),
        'price': price,
        'change_pct': change_pct,
        'confidence': confidence,
        'action': action,
        'reason': reason,
        'signals': signals,
        'all_scores': dict(zip(signals.keys(), scores)),
    }

# ═══════════════════════════════════════════════════════
#  执行层 (ths_trades WEB API / 文件信号)
# ═══════════════════════════════════════════════════════
def exec_ths_trades(action: str, code: str, price: float, quantity: int) -> Dict:
    """通过 ths_trades WEB API 执行下单"""
    side = "buy" if action == "买" else "sell"
    payload = {
        "method": "order",
        "account": "模拟账户" if MODE == "mock" else "实盘账户",
        "stock_code": code,
        "price": round(price, 2),
        "quantity": quantity,
        "price_type": "limit",
        "side": side,
    }
    try:
        r = requests.post(f"{THS_TRADES_HOST}/api", json=payload, timeout=15)
        resp = r.json()
        if resp.get('success') or resp.get('code') == 0:
            log.info(f"[实盘] ✅ {action} {code} {quantity}股 @{price:.2f} — {resp}")
            return {'ok': True, 'detail': resp}
        else:
            log.error(f"[实盘] ❌ {action} {code} 失败: {resp}")
            return {'ok': False, 'detail': resp}
    except Exception as e:
        log.error(f"[实盘] ❌ ths_trades连接失败: {e}，改用文件信号")
        return {'ok': False, 'detail': str(e)}

def write_signal_file(action: str, code: str, price: float, quantity: int):
    """写信号文件(跨Mac→Windows通信)"""
    if not PARALLELS_SIGNAL_DIR:
        log.debug("[信号] PARALLELS_SIGNAL_DIR未配置，跳过文件写入")
        return
    signal_file = Path(PARALLELS_SIGNAL_DIR) / 't_signal.json'
    signal_file.write_text(json.dumps({
        'action': action, 'code': code, 'price': round(price, 2),
        'quantity': quantity, 'mode': MODE,
        'ts': datetime.datetime.now().isoformat(),
    }, ensure_ascii=False), encoding='utf-8')
    log.info(f"[信号] 📁 写入信号文件: {signal_file}")

# ═══════════════════════════════════════════════════════
#  风险检查
# ═══════════════════════════════════════════════════════
TRADED_TODAY = {}   # {code: [buy_qty, sell_qty]}
MAX_T_SINGLE = 2400  # 单次做T最多2400股
MAX_T_DAY = 4800     # 每日做T最多4800股

def check_risk(action: str, code: str, quantity: int, price: float) -> tuple:
    """风控检查，返回 (通过, 原因)"""
    today = datetime.date.today().isoformat()
    if today not in TRADED_TODAY:
        TRADED_TODAY[today] = {'buy': 0, 'sell': 0}

    if action == "买":
        if quantity > MAX_T_SINGLE:
            return False, f"单次买入量{quantity}超限({MAX_T_SINGLE})"
        if TRADED_TODAY[today]['buy'] + quantity > MAX_T_DAY:
            return False, f"今日买入量超限({MAX_T_DAY})"
        if price < COST_PRICE * 0.92:  # 跌幅>8%不追
            return False, f"价格{price}距成本{COST_PRICE}跌幅过深({(price/COST_PRICE-1)*100:.1f}%)"
    else:
        if quantity > MAX_T_SINGLE:
            return False, f"单次卖出量{quantity}超限({MAX_T_SINGLE})"
        if TRADED_TODAY[today]['sell'] + quantity > MAX_T_DAY:
            return False, f"今日卖出量超限({MAX_T_DAY})"
        if price < COST_PRICE * 1.05:  # 涨幅<5%不卖
            return False, f"价格{price}涨幅不足({(price/COST_PRICE-1)*100:.1f}%)"

    return True, "通过"

def record_trade(action: str, quantity: int):
    today = datetime.date.today().isoformat()
    if today not in TRADED_TODAY:
        TRADED_TODAY[today] = {'buy': 0, 'sell': 0}
    key = 'buy' if action == '买' else 'sell'
    TRADED_TODAY[today][key] += quantity

# ═══════════════════════════════════════════════════════
#  全市场扫描 (重点盯盘 + 全池异动)
# ═══════════════════════════════════════════════════════
SCAN_RESULTS = []   # 最近一次扫描结果
_last_scan_time = None

def scan_market() -> List[Dict]:
    """全市场扫描：108只找异动，输出做T机会列表"""
    global SCAN_RESULTS, _last_scan_time

    now = datetime.datetime.now()
    is_trading = _is_trading_time(now)

    # 盘中盘后都扫全池108只（做T机会不挑时间）
    scan_codes = ALL_CODES

    log.info(f"[扫描] 股票池 {len(scan_codes)} 只，{'盘中' if is_trading else '非交易时间'}...")
    quotes = get_realtime_quote(scan_codes)

    if not quotes:
        log.warning("[扫描] 行情获取为空，跳过本轮")
        return SCAN_RESULTS

    results = []
    for quote in quotes:
        code = quote['code']
        chg = abs(quote.get('change_pct', 0))
        vol_r = quote.get('volume_ratio', 0)

        # 异动过滤：涨跌幅<0.3%且量比<1.3 → 跳过（无做T价值）
        if chg < 0.3 and vol_r < 1.3:
            continue

        kline = get_kline(code)
        sig = calc_t_signals(code, quote, kline)

        # 只保留有机会的票
        if sig['confidence'] >= 55 or chg >= 1.0:
            results.append(sig)

    # 按置信度排序
    results.sort(key=lambda x: x['confidence'], reverse=True)
    SCAN_RESULTS = results
    _last_scan_time = now

    log.info(f"[扫描] 完成，{len(results)} 只有做T机会，TOP3: "
             + " | ".join(f"{r['code']} {r['action']}({r['confidence']}%)" for r in results[:3]))
    return results

def _is_trading_time(now: datetime.datetime) -> bool:
    """判断是否在交易时间"""
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (datetime.time(9, 25) <= t <= datetime.time(11, 35) or
            datetime.time(12, 55) <= t <= datetime.time(15, 5))

# ═══════════════════════════════════════════════════════
#  做T核心循环
# ═══════════════════════════════════════════════════════
_running = False

def t0_loop():
    """做T主循环（定时扫描+信号输出）"""
    global _running
    log.info(f"[启动] 做T循环开始 | 模式:{'模拟' if MODE=='mock' else '实盘'} | 股票池:{len(ALL_CODES)}只")
    scan_count = 0

    while _running:
        now = datetime.datetime.now()
        is_trading = _is_trading_time(now)

        # 盘中30秒扫一次，盘后5分钟扫一次（监控用）
        scan_interval = 30 if is_trading else 300
        scan_count += 1
        results = scan_market()

        if results and is_trading and results[0]['confidence'] >= T_CONFIG['confidence_min']:
            best = results[0]
            action = best['action']
            code = best['code']
            price = best['price']

            # 风控检查
            qty = min(T_POSITION, MAX_T_SINGLE)
            ok, reason = check_risk(action, code, qty, price)

            if not ok:
                log.info(f"[风控] {code} {action}被拦截: {reason}")
                best['risk_blocked'] = reason
            else:
                # 执行
                if MODE == "mock":
                    log.info(f"🤖 [模拟] {'买入' if action=='买' else '卖出'} {code} "
                             f"{qty}股 @{price:.2f} | 置信度:{best['confidence']}% | {best['reason']}")
                    record_trade(action, qty)
                else:
                    # 优先ths_trades，失败则写文件
                    res = exec_ths_trades(action, code, price, qty)
                    if not res['ok']:
                        write_signal_file(action, code, price, qty)
                    record_trade(action, qty)

            _print_top_signals(results, f"📈 TOP机会 #{scan_count}")

        time.sleep(scan_interval)  # 盘中30秒/盘后5分钟

    log.info("[停止] 做T循环已退出")

def _print_top_signals(results: List[Dict], title: str):
    """打印信号表格"""
    print(f"\n{'='*60}")
    print(f"{title} | {datetime.datetime.now().strftime('%H:%M:%S')}")
    print(f"{'代码':<8} {'名称':<8} {'现价':>7} {'涨跌%':>7} {'置信%':>6} "
          f"{'动作':<5} {'信号详情'}")
    print('-'*80)
    for r in results[:8]:
        chg_color = '\033[92m' if r['change_pct'] >= 0 else '\033[91m'
        reset = '\033[0m'
        sigs = [f"{k}({v['score']})" for k, v in r['signals'].items() if v['score'] > 0]
        print(f"{r['code']:<8} {r.get('name',''):<8} {r['price']:>7.2f} "
              f"{chg_color}{r['change_pct']:>+7.2f}{reset} "
              f"{r['confidence']:>6.1f}% {r['action']:<5} {' '.join(sigs)}")
    print(f"{'='*60}\n")

# ═══════════════════════════════════════════════════════
#  HTTP服务器 (接收信号 / 查看状态)
# ═══════════════════════════════════════════════════════
def _start_http_server(port=8080):
    """轻量HTTP服务器：查看扫描结果+手动触发"""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
    except ImportError:
        log.warning("[HTTP] 内置http.server不可用，跳过HTTP服务")
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/status' or self.path == '/':
                results = SCAN_RESULTS[-20:]
                html = self._build_html(results)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == '/scan':
                content_len = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_len).decode('utf-8')
                try:
                    data = json.loads(body)
                    code = data.get('code', '')
                    if code:
                        quote = get_realtime_quote([code])
                        if quote:
                            sig = calc_t_signals(code, quote[0])
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps(sig, ensure_ascii=False).encode('utf-8'))
                            return
                except:
                    pass
                self.send_response(400)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def _build_html(self, results):
            """构建清晰分区的做T监控界面"""
            import datetime as dt

            # 分离买卖信号
            buy_signals = [r for r in results if r['action'] == '买']
            sell_signals = [r for r in results if r['action'] == '卖']
            watch_signals = [r for r in results if r['action'] == '观望']

            # 今日交易统计
            today = dt.date.today().isoformat()
            traded = TRADED_TODAY.get(today, {'buy': 0, 'sell': 0})

            # 做T范围计算
            buy_range_max = COST_PRICE
            sell_min = COST_PRICE * 1.05

            last_scan = _last_scan_time.strftime('%H:%M:%S') if _last_scan_time else '等待扫描...'
            mode_text = '模拟账户' if MODE == 'mock' else '实盘模式'

            # 用普通字符串，不用f-string，避免{{}}和{}冲突
            html = ['<!DOCTYPE html>\n<html><head>\n<meta charset="utf-8">\n<title>做T监控系统</title>\n'
                    '<style>\n'
                    '* { margin:0; padding:0; box-sizing:border-box; }\n'
                    'body { font-family:Arial,sans-serif; background:#1a1a2e; color:#eee; min-height:100vh; }\n'
                    '.header { background:linear-gradient(135deg,#16213e,#0f3460); padding:20px; border-bottom:2px solid #e94560; }\n'
                    '.header h1 { color:#fff; font-size:24px; margin-bottom:10px; }\n'
                    '.config-bar { display:flex; gap:30px; flex-wrap:wrap; font-size:13px; margin-top:10px; }\n'
                    '.config-item { background:rgba(255,255,255,0.1); padding:8px 15px; border-radius:8px; }\n'
                    '.config-item span { color:#e94560; font-weight:bold; }\n'
                    '.main { display:grid; grid-template-columns:1fr 1fr; gap:15px; padding:15px; }\n'
                    '.signal-panel { background:#16213e; border-radius:12px; overflow:hidden; }\n'
                    '.panel-header { padding:15px 20px; font-size:16px; font-weight:bold; display:flex; justify-content:space-between; align-items:center; }\n'
                    '.buy-panel .panel-header { background:linear-gradient(90deg,#1b4332,#2d6a4f); }\n'
                    '.sell-panel .panel-header { background:linear-gradient(90deg,#7f1d1d,#991b1b); }\n'
                    '.panel-header .count { background:rgba(255,255,255,0.2); padding:2px 10px; border-radius:10px; font-size:12px; }\n'
                    '.signal-list { padding:10px; max-height:400px; overflow-y:auto; }\n'
                    '.signal-card { background:rgba(255,255,255,0.05); border-radius:8px; padding:12px; margin-bottom:10px; border-left:4px solid; }\n'
                    '.buy-panel .signal-card { border-color:#22c55e; }\n'
                    '.sell-panel .signal-card { border-color:#ef4444; }\n'
                    '.card-header { display:flex; justify-content:space-between; margin-bottom:8px; }\n'
                    '.code { font-weight:bold; font-size:15px; }\n'
                    '.name { color:#888; font-size:13px; }\n'
                    '.action-badge { padding:3px 12px; border-radius:4px; font-weight:bold; font-size:13px; }\n'
                    '.buy-panel .action-badge { background:#22c55e; }\n'
                    '.sell-panel .action-badge { background:#ef4444; }\n'
                    '.price-row { display:flex; gap:20px; margin:8px 0; font-size:13px; }\n'
                    '.price-item { flex:1; }\n'
                    '.price-label { color:#888; font-size:11px; }\n'
                    '.price-value { font-size:16px; font-weight:bold; }\n'
                    '.confidence { background:rgba(233,69,96,0.2); color:#e94560; padding:2px 8px; border-radius:4px; font-size:12px; }\n'
                    '.reason { font-size:12px; color:#aaa; margin-top:8px; line-height:1.4; }\n'
                    '.empty { text-align:center; color:#666; padding:40px; }\n'
                    '.footer { background:#16213e; padding:15px 20px; border-top:1px solid #333; display:flex; justify-content:space-between; font-size:13px; }\n'
                    '.stat-item { color:#888; }\n'
                    '.stat-item span { color:#fff; font-weight:bold; }\n'
                    '.log-section { background:#0d0d1a; padding:15px; grid-column:1/-1; border-radius:12px; }\n'
                    '.log-title { color:#888; font-size:12px; margin-bottom:10px; }\n'
                    '.log-content { font-family:Consolas,monospace; font-size:12px; color:#4ade80; max-height:100px; overflow-y:auto; }\n'
                    '.pos { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }\n'
                    '.pos-up { background:#ef4444; }\n'
                    '.pos-down { background:#22c55e; }\n'
                    '</style>\n'
                    '</head><body>\n'

                    '<div class="header">\n'
                    '<h1>&#x1F4CA; 云图控股 T+0 做T监控系统</h1>\n'
                    '<div class="config-bar">\n'
                    '<div class="config-item">模式: <span>' + mode_text + '</span></div>\n'
                    '<div class="config-item">成本价: <span>&#165;%.3f</span></div>\n' % COST_PRICE +
                    '<div class="config-item">买入区间: <span>&#165;%.2f以内</span></div>\n' % buy_range_max +
                    '<div class="config-item">卖出区间: <span>&#165;%.2f以上</span></div>\n' % sell_min +
                    '<div class="config-item">做T仓位: <span>%d股</span></div>\n' % T_POSITION +
                    '<div class="config-item">置信度: <span>%d%%</span></div>\n' % T_CONFIG['confidence_min'] +
                    '</div>\n'
                    '</div>\n'

                    '<div class="main">\n'

                    '<div class="signal-panel buy-panel">\n'
                    '<div class="panel-header">\n'
                    '<span>&#x1F7E2; 买入信号</span>\n'
                    '<span class="count">%d 只</span>\n' % len(buy_signals) +
                    '</div>\n'
                    '<div class="signal-list">\n']

            # 买入信号卡片
            if buy_signals:
                for r in buy_signals[:8]:
                    chg = r['change_pct']
                    chg_color = '#22c55e' if chg < 0 else '#f59e0b'
                    buy_price = r['price'] * 0.998
                    html.append(
                        '<div class="signal-card">\n'
                        '<div class="card-header">\n'
                        '<span class="code">' + r['code'] + '</span>\n'
                        '<span class="name">' + r.get('name', '') + '</span>\n'
                        '<span class="action-badge">买</span>\n'
                        '</div>\n'
                        '<div class="price-row">\n'
                        '<div class="price-item"><div class="price-label">现价</div><div class="price-value">&#165;%.2f</div></div>\n' % r['price'] +
                        '<div class="price-item"><div class="price-label">建议买价</div><div class="price-value" style="color:#22c55e">&#165;%.2f</div></div>\n' % buy_price +
                        '<div class="price-item">\n'
                        '<div class="price-label">涨跌</div>\n'
                        '<div class="price-value" style="color:' + chg_color + '">%+.2f%%</div>\n' % chg +
                        '</div>\n'
                        '</div>\n'
                        '<div class="reason">&#x1F4CC; ' + r.get('reason', '') + '</div>\n'
                        '<div style="margin-top:8px;">\n'
                        '<span class="confidence">置信度 %.0f%%</span>\n' % r['confidence'] +
                        '</div>\n'
                        '</div>\n')
            else:
                html.append('<div class="empty">暂无买入信号</div>\n')

            html.append('</div>\n</div>\n'

                        '<div class="signal-panel sell-panel">\n'
                        '<div class="panel-header">\n'
                        '<span>&#x1F534; 卖出信号</span>\n'
                        '<span class="count">%d 只</span>\n' % len(sell_signals) +
                        '</div>\n'
                        '<div class="signal-list">\n')

            # 卖出信号卡片
            if sell_signals:
                for r in sell_signals[:8]:
                    chg = r['change_pct']
                    chg_color = '#ef4444' if chg > 0 else '#f59e0b'
                    sell_price = r['price'] * 1.002
                    html.append(
                        '<div class="signal-card">\n'
                        '<div class="card-header">\n'
                        '<span class="code">' + r['code'] + '</span>\n'
                        '<span class="name">' + r.get('name', '') + '</span>\n'
                        '<span class="action-badge">卖</span>\n'
                        '</div>\n'
                        '<div class="price-row">\n'
                        '<div class="price-item"><div class="price-label">现价</div><div class="price-value">&#165;%.2f</div></div>\n' % r['price'] +
                        '<div class="price-item"><div class="price-label">建议卖价</div><div class="price-value" style="color:#ef4444">&#165;%.2f</div></div>\n' % sell_price +
                        '<div class="price-item">\n'
                        '<div class="price-label">涨跌</div>\n'
                        '<div class="price-value" style="color:' + chg_color + '">%+.2f%%</div>\n' % chg +
                        '</div>\n'
                        '</div>\n'
                        '<div class="reason">&#x1F4CC; ' + r.get('reason', '') + '</div>\n'
                        '<div style="margin-top:8px;">\n'
                        '<span class="confidence">置信度 %.0f%%</span>\n' % r['confidence'] +
                        '</div>\n'
                        '</div>\n')
            else:
                html.append('<div class="empty">暂无卖出信号</div>\n')

            # 观望信号
            watch_html = ''
            if watch_signals:
                watch_list = ', '.join(r['code'] + '(' + '%.0f%%)' % r['confidence'] for r in watch_signals[:5])
                watch_html = '<div style="color:#f59e0b;margin-bottom:10px;">&#x23F3; 观望中: ' + watch_list + '</div>\n'
            else:
                watch_html = '<div style="color:#666;">暂无观望信号</div>\n'

            html.append('</div>\n</div>\n'

                        '<div class="log-section">\n'
                        '<div class="log-title">&#x1F4DC; 今日交易统计 | 买入 %d股 / 卖出 %d股</div>\n' % (traded.get('buy', 0), traded.get('sell', 0)) +
                        '<div class="log-content">\n' +
                        watch_html +
                        '</div>\n'
                        '</div>\n'
                        '</div>\n'

                        '<div class="footer">\n'
                        '<div>\n'
                        '<span class="stat-item">最后扫描: <span>' + last_scan + '</span></span>\n'
                        '<span class="stat-item" style="margin-left:20px;">股票池: <span>%d只</span></span>\n' % len(ALL_CODES) +
                        '<span class="stat-item" style="margin-left:20px;">盯盘: <span>%d只</span></span>\n' % len(KEY_CODES) +
                        '</div>\n'
                        '<div style="color:#666;">F5刷新 | API: POST /scan</div>\n'
                        '</div>\n'

                        '</body></html>')

            return ''.join(html).encode('utf-8')

        def log_message(self, fmt, *args):
            pass  # 减少日志噪音

    try:
        server = HTTPServer(('0.0.0.0', port), Handler)
        log.info(f"[HTTP] 监控面板: http://localhost:{port}/status")
        server.serve_forever()
    except Exception as e:
        log.warning(f"[HTTP] HTTP服务启动失败: {e}")

# ═══════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════
def main():
    global _running

    print(f"""
    ╔══════════════════════════════════════════════╗
    ║        云图控股 T+0 自动做T系统              ║
    ║  模式: {'【模拟账户】 不实际下单' if MODE=='mock' else '【实盘模式】 ths_trades自动下单'}        ║
    ║  股票池: {len(ALL_CODES)} 只  盯盘: {len(KEY_CODES)} 只           ║
    ║  做T仓位: {T_POSITION}股  底仓: {BASE_POSITION}股           ║
    ║  ths_trades: {THS_TRADES_HOST}              ║
    ║  监控面板: http://localhost:8080/status      ║
    ╚══════════════════════════════════════════════╝
    """)

    log.info(f"═══════════ 启动 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ═══════════")
    log.info(f"模式:{'模拟' if MODE=='mock' else '实盘'} | 池:{len(ALL_CODES)}只 | 盯盘:{len(KEY_CODES)}只")

    _running = True

    # 启动HTTP服务
    http_thread = threading.Thread(target=_start_http_server, daemon=True)
    http_thread.start()

    # 启动做T主循环
    t_thread = threading.Thread(target=t0_loop, daemon=True)
    t_thread.start()

    # 优雅退出
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[退出] 收到Ctrl+C，正在停止...")
        _running = False
        time.sleep(2)
        log.info("[退出] 再见！")

if __name__ == '__main__':
    main()
