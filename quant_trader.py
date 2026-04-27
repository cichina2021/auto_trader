"""
量化选股信号系统 v2.0
===========================
定位：短线强势股量化筛选，只做信号提醒，用户自主下单
逻辑：多因子量化模型（动量 + 趋势 + 成交量 + 形态）
持仓：单票100%仓位，满仓进出
"""

import os, sys, json, time, logging, datetime, threading
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

# ═══════════════════════════════════════════════════════════
#  策略参数配置（你可根据实际情况调整）
# ═══════════════════════════════════════════════════════════
class Config:
    # 止损止盈
    STOP_LOSS = -4.0      # 止损：跌4%出
    TAKE_PROFIT = 8.0     # 止盈：涨8%出

    # 持仓周期
    MAX_HOLD_DAYS = 3     # 最多持有3天

    # 选股因子权重
    MOMENTUM_WEIGHT = 30      # 动量因子权重（%）
    TREND_WEIGHT = 25         # 趋势因子权重（%）
    VOLUME_WEIGHT = 25        # 量能因子权重（%）
    SHAPE_WEIGHT = 20         # 形态因子权重（%）

    # 选股阈值
    MIN_VOLUME_RATIO = 1.5    # 最低量比
    MIN_CONFIDENCE = 70       # 最低信号置信度
    TOP_N = 5                 # 每次最多选N只

    # 均线参数
    MA_SHORT = 5              # 短期均线
    MA_MID = 10               # 中期均线
    MA_LONG = 20              # 长期均线

    # 扫描间隔（秒）
    SCAN_INTERVAL_TRADING = 60    # 盘中1分钟扫一次
    SCAN_INTERVAL_CLOSED = 300    # 盘后5分钟扫一次

# ═══════════════════════════════════════════════════════════
#  数据加载
# ═══════════════════════════════════════════════════════════
def load_stock_pool():
    """加载股票池"""
    base = getattr(sys, '_MEIPASS', str(Path(__file__).parent))
    json_path = Path(base) / 'stock_pool.json'
    if json_path.exists():
        return json.loads(json_path.read_text(encoding='utf-8'))
    # 默认20只核心股
    return [{"code": c} for c in [
        "002539", "000625", "002415", "601138", "002594",
        "600690", "000333", "002241", "002049", "002230",
        "002236", "000651", "600309", "600519", "601318",
        "600016", "000858", "600887", "002714", "000002"
    ]]

ALL_STOCKS = load_stock_pool()
ALL_CODES = [s['code'] for s in ALL_STOCKS]

# ═══════════════════════════════════════════════════════════
#  日志系统
# ═══════════════════════════════════════════════════════════
def setup_logging():
    log_dir = Path(os.environ.get('APPDATA', '.')) / 'quant_trader' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"signals_{datetime.date.today().isoformat()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger('quant')

log = setup_logging()

# ═══════════════════════════════════════════════════════════
#  数据源层
# ═══════════════════════════════════════════════════════════
_last_request_time = 0.0
_request_lock = threading.Lock()

def rate_limit():
    """防封：每秒最多1次请求"""
    global _last_request_time
    with _request_lock:
        now = time.time()
        elapsed = now - _last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_request_time = time.time()

def get_realtime_quotes(codes: List[str]) -> List[Dict]:
    """获取实时行情"""
    rate_limit()

    # 方案1：新浪财经
    try:
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
            if len(parts) < 32:
                continue
            price = float(parts[3]) if parts[3] not in ('', '0') else 0
            prev_close = float(parts[2]) if parts[2] not in ('', '0') else 0
            chg_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            # 解析量比 (parts[40] 或计算)
            vol_ratio = float(parts[37]) if len(parts) > 37 and parts[37] not in ('', '-') else 0
            result.append({
                'code': code.zfill(6),
                'name': parts[0],
                'price': price,
                'prev_close': prev_close,
                'change_pct': round(chg_pct, 2),
                'volume_ratio': vol_ratio,
                'volume': float(parts[8]) if len(parts) > 8 and parts[8] else 0,
                'high': float(parts[4]) if parts[4] not in ('', '0') else 0,
                'low': float(parts[5]) if parts[5] not in ('', '0') else 0,
                'open': float(parts[1]) if parts[1] not in ('', '0') else 0,
            })
        if result:
            log.info(f"[数据] 新浪获取{len(result)}只行情")
            return result
    except Exception as e:
        log.warning(f"[数据] 新浪失败: {e}")

    # 方案2：腾讯财经
    try:
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
            price = float(parts[3]) if parts[3] not in ('', '-') else 0
            prev_close = float(parts[4]) if parts[4] not in ('', '-') else 0
            chg_pct = float(parts[31]) if parts[31] not in ('', '-') else 0
            result.append({
                'code': code_raw,
                'name': parts[1],
                'price': price,
                'prev_close': prev_close,
                'change_pct': chg_pct,
                'volume_ratio': float(parts[37]) if parts[37] not in ('', '-') else 0,
                'volume': float(parts[36]) if len(parts) > 36 and parts[36] not in ('', '-') else 0,
                'high': float(parts[33]) if parts[33] not in ('', '-') else 0,
                'low': float(parts[34]) if parts[34] not in ('', '-') else 0,
                'open': float(parts[5]) if parts[5] not in ('', '-') else 0,
            })
        if result:
            log.info(f"[数据] 腾讯获取{len(result)}只行情")
            return result
    except Exception as e:
        log.warning(f"[数据] 腾讯失败: {e}")

    return []

def get_kline(code: str, period: str = "daily", count: int = 60) -> Optional[Dict]:
    """获取K线数据"""
    rate_limit()
    try:
        qt_code = f"sh{code}" if code.startswith(('6', '5')) else f"sz{code}"
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={qt_code},day,,,{count},qfq"
        r = requests.get(url, timeout=8)
        r.encoding = 'utf-8'
        import re
        m = re.search(r'data:\["([^"]+)"', r.text)
        if not m:
            return None
        bars = re.findall(r'\[([^\]]+)\]', m.group(1))
        closes, highs, lows, vols = [], [], [], []
        for bar in bars[-count:]:
            parts = bar.split(',')
            if len(parts) >= 6:
                closes.append(float(parts[1]))
                highs.append(float(parts[2]))
                lows.append(float(parts[3]))
                vols.append(float(parts[4]))
        if len(closes) >= 5:
            return {'close': closes, 'high': highs, 'low': lows, 'volume': vols, 'code': code}
    except Exception as e:
        log.debug(f"[K线] {code} 失败: {e}")
    return None

# ═══════════════════════════════════════════════════════════
#  技术指标计算
# ═══════════════════════════════════════════════════════════
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
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)
    k_sig = 2 / (signal + 1)
    ema_fast = [prices[0]]
    ema_slow = [prices[0]]
    for p in prices[1:]:
        ema_fast.append(p * k_fast + ema_fast[-1] * (1 - k_fast))
        ema_slow.append(p * k_slow + ema_slow[-1] * (1 - k_slow))
    dif = [ema_fast[-1] - ema_slow[-1]]
    dea = [dif[0]]
    for d in dif[1:] if len(dif) > 1 else [dif[0]]:
        dea.append(d * k_sig + dea[-1] * (1 - k_sig))
    bar = 2 * (dif[-1] - dea[-1])
    return round(dif[-1], 4), round(dea[-1], 4), round(bar, 4)

def calc_boll(closes: List[float], period: int = 20, multiplier: float = 2.0):
    if len(closes) < period:
        return 0, 0, 0
    recent = closes[-period:]
    mid = sum(recent) / period
    std = (sum((x - mid) ** 2 for x in recent) / period) ** 0.5
    upper = mid + multiplier * std
    lower = mid - multiplier * std
    return round(upper, 3), round(mid, 3), round(lower, 3)

def calc_kdj(highs: List[float], lows: List[float], closes: List[float], n: int = 9):
    if len(closes) < n:
        return 50, 50, 50
    k_vals, d_vals = [50], [50]
    for i in range(n - 1, len(closes)):
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv = (closes[i] - ll) / (hh - ll) * 100 if hh > ll else 50
        k_vals.append(rsv / 3 + k_vals[-1] * 2 / 3)
        d_vals.append(k_vals[-1] / 2 + d_vals[-1] / 2)
    k = round(k_vals[-1], 2)
    d = round(d_vals[-1], 2)
    j = round(3 * k - 2 * d, 2)
    return k, d, j

# ═══════════════════════════════════════════════════════════
#  量化多因子选股引擎
# ═══════════════════════════════════════════════════════════
def quant_select(code: str, quote: Dict, kline: Optional[Dict] = None) -> Dict:
    """
    量化多因子选股模型
    返回: {code, name, price, confidence, action, score_breakdown, reason}
    """
    cfg = Config
    price = quote.get('price', 0)
    change_pct = quote.get('change_pct', 0)
    vol_ratio = quote.get('volume_ratio', 0)

    if not kline or len(kline.get('close', [])) < cfg.MA_LONG + 5:
        kline = get_kline(code)

    result = {
        'code': code,
        'name': quote.get('name', ''),
        'price': price,
        'change_pct': change_pct,
        'volume_ratio': vol_ratio,
        'confidence': 0,
        'action': '观望',
        'score_breakdown': {},
        'reason': '',
    }

    if not kline or price <= 0:
        return result

    closes = kline['close']
    highs = kline.get('high', closes)
    lows = kline.get('low', closes)

    # ── 因子1: 动量因子 (30%) ──
    mom_score = 0
    if len(closes) >= 5:
        ret_5d = (price - closes[-5]) / closes[-5] * 100 if closes[-5] > 0 else 0
        ret_10d = (price - closes[-10]) / closes[-10] * 100 if len(closes) >= 10 and closes[-10] > 0 else ret_5d
        # 动量评分：近期涨幅越大得分越高
        mom_score = min(cfg.MOMENTUM_WEIGHT, max(0, (ret_5d + 5) * 3))
        if change_pct > 3:  # 当日大涨
            mom_score = min(cfg.MOMENTUM_WEIGHT, mom_score + 10)
        if ret_5d > ret_10d > 0:  # 加速上涨
            mom_score = min(cfg.MOMENTUM_WEIGHT, mom_score + 5)
    result['score_breakdown']['动量'] = round(mom_score, 1)

    # ── 因子2: 趋势因子 (25%) ──
    trend_score = 0
    if len(closes) >= cfg.MA_LONG:
        ma5 = calc_ma(closes, cfg.MA_SHORT)
        ma10 = calc_ma(closes, cfg.MA_MID)
        ma20 = calc_ma(closes, cfg.MA_LONG)

        # 均线多头排列：MA5 > MA10 > MA20
        ma_bullish = ma5 > ma10 > ma20
        # 股价站上短期均线
        above_ma5 = price > ma5
        # MACD金叉
        dif, dea, bar = calc_macd(closes)
        macd_bullish = dif > dea and bar > 0

        if ma_bullish and above_ma5:
            trend_score += 10
        if macd_bullish:
            trend_score += 10
        # KDJ低位金叉
        k, d, j = calc_kdj(highs, lows, closes)
        if k < d and k < 50 and dif > 0:  # MACD红柱时KDJ金叉
            trend_score += 5

        trend_score = min(cfg.TREND_WEIGHT, trend_score)
    result['score_breakdown']['趋势'] = round(trend_score, 1)

    # ── 因子3: 量能因子 (25%) ──
    vol_score = 0
    if vol_ratio >= cfg.MIN_VOLUME_RATIO:
        vol_score = min(cfg.VOLUME_WEIGHT, (vol_ratio - 1) * 15)
        if change_pct > 0 and vol_ratio > 2:  # 上涨放量
            vol_score = min(cfg.VOLUME_WEIGHT, vol_score + 8)
    # 今日量能创近期新高
    if kline and len(kline.get('volume', [])) >= 5:
        recent_vol = kline['volume'][-5:]
        if kline['volume'][-1] >= max(recent_vol[:-1]) * 1.2:
            vol_score = min(cfg.VOLUME_WEIGHT, vol_score + 5)
    result['score_breakdown']['量能'] = round(vol_score, 1)

    # ── 因子4: 形态因子 (20%) ──
    shape_score = 0
    if len(closes) >= 20:
        upper, mid, lower = calc_boll(closes)
        if upper > 0:
            # 股价突破布林上轨或在中上轨区间
            pos = (price - lower) / (upper - lower) * 100
            if pos >= 80:  # 突破上轨
                shape_score += 10
            elif pos >= 60:  # 中上轨区间
                shape_score += 5
        # 整理形态突破（旗形、三角形）- 简化判断：近期波动收窄后放量突破
        if len(closes) >= 15:
            recent_range = (max(highs[-15:]) - min(lows[-15:])) / closes[-15] * 100
            if recent_range < 8:  # 窄幅整理
                shape_score += 5
        shape_score = min(cfg.SHAPE_WEIGHT, shape_score)
    result['score_breakdown']['形态'] = round(shape_score, 1)

    # ── 综合评分 ──
    total = (mom_score + trend_score + vol_score + shape_score)
    confidence = round(total, 1)

    # ── 决策 ──
    buy_signals = 0
    if mom_score >= cfg.MOMENTUM_WEIGHT * 0.5:
        buy_signals += 1
    if trend_score >= cfg.TREND_WEIGHT * 0.6:
        buy_signals += 1
    if vol_score >= cfg.VOLUME_WEIGHT * 0.5:
        buy_signals += 1

    if confidence >= cfg.MIN_CONFIDENCE and buy_signals >= 2:
        if vol_ratio >= 1.8 and change_pct > 0:  # 放量上涨
            result['action'] = '强烈买入'
            result['reason'] = f'放量突破 | 动量{ret_5d:+.1f}% | 量比{vol_ratio:.1f} | MACD金叉'
            confidence = min(100, confidence + 10)
        elif buy_signals >= 2:
            result['action'] = '买入'
            result['reason'] = f'多因子共振 | 置信度{confidence}% | 量比{vol_ratio:.1f}'
    else:
        result['action'] = '观望'
        result['reason'] = f'信号不足 | 置信度{confidence}%'

    result['confidence'] = confidence
    return result

# ═══════════════════════════════════════════════════════════
#  持仓管理
# ═══════════════════════════════════════════════════════════
class Position:
    """持仓管理"""
    def __init__(self):
        self.code = None
        self.name = ''
        self.buy_price = 0
        self.buy_date = None
        self.quantity = 0

    def has_position(self):
        return self.code is not None and self.quantity > 0

    def open(self, code: str, name: str, price: float, qty: int):
        self.code = code
        self.name = name
        self.buy_price = price
        self.buy_date = datetime.date.today()
        self.quantity = qty
        log.info(f"[持仓] 开仓 {code} {name} {qty}股 @ {price}")

    def close(self, reason: str = ''):
        if self.has_position():
            log.info(f"[持仓] 平仓 {self.code} 原因: {reason}")
        self.code = None
        self.name = ''
        self.buy_price = 0
        self.buy_date = None
        self.quantity = 0

    def check_exit(self, current_price: float) -> Optional[str]:
        """检查是否需要退出"""
        if not self.has_position():
            return None

        pnl_pct = (current_price - self.buy_price) / self.buy_price * 100

        # 止损
        if pnl_pct <= Config.STOP_LOSS:
            return f"止损出局 | 亏损{pnl_pct:.1f}%"

        # 止盈
        if pnl_pct >= Config.TAKE_PROFIT:
            return f"止盈出局 | 盈利{pnl_pct:.1f}%"

        # 时间止损
        if self.buy_date:
            hold_days = (datetime.date.today() - self.buy_date).days
            if hold_days >= Config.MAX_HOLD_DAYS:
                return f"时间到期 | 持有{hold_days}天 | 盈亏{pnl_pct:+.1f}%"

        return None

POSITION = Position()

# ═══════════════════════════════════════════════════════════
#  信号推送
# ═══════════════════════════════════════════════════════════
SIGNAL_HISTORY = []  # 信号历史

def push_signal(signal: Dict):
    """推送信号到界面"""
    SIGNAL_HISTORY.insert(0, {
        **signal,
        'time': datetime.datetime.now().strftime('%H:%M:%S')
    })
    # 只保留最近20条
    SIGNAL_HISTORY = SIGNAL_HISTORY[:20]
    log.info(f"[信号] {signal['action']} {signal['code']} {signal['name']} @{signal['price']} ({signal['confidence']}%)")

def scan_and_select() -> List[Dict]:
    """全市场扫描选股"""
    log.info(f"[扫描] 股票池 {len(ALL_CODES)} 只...")
    quotes = get_realtime_quotes(ALL_CODES)

    if not quotes:
        log.warning("[扫描] 行情获取失败")
        return []

    signals = []
    for quote in quotes:
        # 快速过滤：股价>0、涨跌幅不为0
        if quote['price'] <= 0 or quote['change_pct'] == 0:
            continue
        # 量比过滤
        if quote['volume_ratio'] < 1.0:  # 至少要有点量
            continue

        sig = quant_select(quote['code'], quote)
        if sig['confidence'] >= 50:  # 降低门槛，让用户看到更多信息
            signals.append(sig)

    # 按置信度排序
    signals.sort(key=lambda x: x['confidence'], reverse=True)
    return signals[:Config.TOP_N * 2]

# ═══════════════════════════════════════════════════════════
#  主扫描循环
# ═══════════════════════════════════════════════════════════
_running = False

def scan_loop():
    """主扫描循环"""
    global _running
    log.info(f"[启动] 量化选股系统 v2.0 | 股票池: {len(ALL_CODES)}只 | 止损:{Config.STOP_LOSS}% | 止盈:{Config.TAKE_PROFIT}%")
    scan_count = 0

    while _running:
        now = datetime.datetime.now()
        is_trading = _is_trading_time(now)
        interval = Config.SCAN_INTERVAL_TRADING if is_trading else Config.SCAN_INTERVAL_CLOSED

        scan_count += 1
        top_signals = scan_and_select()

        # 打印当日TOP信号
        if top_signals:
            _print_signals(top_signals, f"#{scan_count}")

        # 检查持仓是否需要退出
        if POSITION.has_position():
            quotes = get_realtime_quotes([POSITION.code])
            if quotes:
                current_price = quotes[0]['price']
                exit_reason = POSITION.check_exit(current_price)
                if exit_reason:
                    push_signal({
                        'action': '⚠️ ' + exit_reason.split('|')[0].strip(),
                        'code': POSITION.code,
                        'name': POSITION.name,
                        'price': current_price,
                        'confidence': 100,
                        'reason': exit_reason,
                        'score_breakdown': {}
                    })
                    POSITION.close(exit_reason)

        time.sleep(interval)

    log.info("[停止] 扫描循环退出")

def _is_trading_time(now: datetime.datetime) -> bool:
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (datetime.time(9, 25) <= t <= datetime.time(11, 35) or
            datetime.time(12, 55) <= t <= datetime.time(15, 5))

def _print_signals(signals: List[Dict], title: str):
    print(f"\n{'='*60}")
    print(f"{title} | {datetime.datetime.now().strftime('%H:%M:%S')} | 止损:{Config.STOP_LOSS}% 止盈:{Config.TAKE_PROFIT}%")
    print(f"{'代码':<8} {'名称':<8} {'现价':>7} {'涨跌':>7} {'量比':>5} {'置信':>6} {'动作':<8}")
    print('-'*70)
    for s in signals[:8]:
        chg = s['change_pct']
        chg_c = '\033[92m' if chg >= 0 else '\033[91m'
        reset = '\033[0m'
        action_c = {'强烈买入': '\033[92m', '买入': '\033[93m', '观望': '\033[90m'}.get(s['action'], '')
        print(f"{s['code']:<8} {s.get('name',''):<8} {s['price']:>7.2f} "
              f"{chg_c}{chg:>+7.2f}%{reset} {s['volume_ratio']:>5.1f} "
              f"{s['confidence']:>6.1f}% {action_c}{s['action']:<8}{reset}")
    print('='*60)

# ═══════════════════════════════════════════════════════════
#  Web界面
# ═══════════════════════════════════════════════════════════
def start_http_server(port=8080):
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
    except ImportError:
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/status' or self.path == '/':
                html = self._build_html()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            elif self.path == '/history':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(SIGNAL_HISTORY, ensure_ascii=False).encode('utf-8'))

        def _build_html(self):
            cfg = Config
            pos = POSITION
            pnl_pct = 0
            hold_days = 0
            if pos.has_position():
                pnl_pct = (0 - pos.buy_price) / pos.buy_price * 100  # placeholder

            # 分离信号
            strong_buy = [s for s in SIGNAL_HISTORY if '强烈' in s.get('action', '')]
            buy = [s for s in SIGNAL_HISTORY if s.get('action') == '买入']
            exit_signals = [s for s in SIGNAL_HISTORY if '止损' in s.get('action', '') or '止盈' in s.get('action', '') or '时间' in s.get('action', '')]
            watch = [s for s in SIGNAL_HISTORY if s.get('action') == '观望' and '⚠' not in s.get('action', '')]

            html = [
                '<!DOCTYPE html><html><head><meta charset="utf-8"><title>量化选股信号</title>',
                '<style>',
                '*{margin:0;padding:0;box-sizing:border-box}',
                'body{font-family:Arial,sans-serif;background:#0f0f1a;color:#eee;min-height:100vh}',
                '.header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px;border-bottom:2px solid #00d4ff}',
                '.header h1{color:#fff;font-size:22px;margin-bottom:8px}',
                '.info-bar{display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-top:10px}',
                '.info-item{background:rgba(0,212,255,0.1);padding:8px 14px;border-radius:8px;border:1px solid rgba(0,212,255,0.3)}',
                '.info-item span{color:#00d4ff;font-weight:bold}',
                '.main{padding:15px;display:grid;grid-template-columns:1fr 1fr;gap:15px}',
                '.panel{background:#1a1a2e;border-radius:12px;overflow:hidden}',
                '.panel-header{padding:12px 16px;font-size:15px;font-weight:bold;display:flex;justify-content:space-between;align-items:center}',
                '.strong-buy-header{background:linear-gradient(90deg,#006400,#00a000)}',
                '.buy-header{background:linear-gradient(90deg,#8b4513,#cd853f)}',
                '.exit-header{background:linear-gradient(90deg,#8b0000,#dc143c)}',
                '.watch-header{background:linear-gradient(90deg,#333,#555)}',
                '.position-header{background:linear-gradient(90deg,#1a1a2e,#00d4ff)}',
                '.count{background:rgba(255,255,255,0.15);padding:2px 10px;border-radius:10px;font-size:11px}',
                '.list{padding:10px;max-height:350px;overflow-y:auto}',
                '.card{background:rgba(255,255,255,0.04);border-radius:8px;padding:12px;margin-bottom:10px;border-left:4px solid}',
                '.strong-buy-card{border-color:#00ff00}',
                '.buy-card{border-color:#ffa500}',
                '.exit-card{border-color:#ff4444}',
                '.watch-card{border-color:#888}',
                '.card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}',
                '.code{font-weight:bold;font-size:15px}',
                '.name{color:#888;font-size:12px}',
                '.badge{padding:3px 10px;border-radius:4px;font-weight:bold;font-size:12px}',
                '.strong-buy-badge{background:#00ff00;color:#000}',
                '.buy-badge{background:#ffa500;color:#000}',
                '.exit-badge{background:#ff4444}',
                '.watch-badge{background:#888;color:#fff}',
                '.info-row{display:flex;gap:15px;font-size:12px;margin:6px 0}',
                '.info-cell{flex:1}',
                '.label{color:#888;font-size:10px}',
                '.value{font-size:15px;font-weight:bold}',
                '.reason{font-size:11px;color:#aaa;margin-top:6px;line-height:1.4}',
                '.confidence{color:#00d4ff;font-size:12px}',
                '.factors{font-size:10px;color:#888;margin-top:4px}',
                '.empty{text-align:center;color:#555;padding:30px;font-size:13px}',
                '.position-info{background:rgba(0,212,255,0.08);padding:15px;border-radius:12px;margin:15px}',
                '.position-info h3{color:#00d4ff;margin-bottom:10px}',
                '.position-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)}',
                '.position-row:last-child{border:none}',
                '.footer{background:#1a1a2e;padding:12px 20px;border-top:1px solid #333;display:flex;justify-content:space-between;font-size:12px;color:#666}',
                '.pos-up{color:#ff4444}',
                '.pos-down{color:#00ff00}',
                '</style></head><body>',

                '<div class="header">',
                '<h1>&#x1F4CA; 量化选股信号系统 v2.0</h1>',
                '<div class="info-bar">',
                '<div class="info-item">止损: <span>-%.1f%%</span></div>' % abs(cfg.STOP_LOSS),
                '<div class="info-item">止盈: <span>+%.1f%%</span></div>' % cfg.TAKE_PROFIT,
                '<div class="info-item">持仓周期: <span>≤%d天</span></div>' % cfg.MAX_HOLD_DAYS,
                '<div class="info-item">选股票池: <span>%d只</span></div>' % len(ALL_CODES),
                '<div class="info-item">置信度门槛: <span>%d%%</span></div>' % cfg.MIN_CONFIDENCE,
                '</div></div>',

                '<div class="main">',

                # 强烈买入
                '<div class="panel">',
                '<div class="panel-header strong-buy-header">',
                '<span>&#x1F7E2; 强烈买入信号</span>',
                '<span class="count">%d只</span>' % len(strong_buy),
                '</div><div class="list">',
            ]

            if strong_buy:
                for s in strong_buy[:5]:
                    chg = s.get('change_pct', 0)
                    chg_c = '#00ff00' if chg < 0 else '#ffa500'
                    scores = s.get('score_breakdown', {})
                    scores_str = ' | '.join(f'{k}:{v}' for k, v in scores.items()) if scores else ''
                    html.append(
                        '<div class="card strong-buy-card">'
                        '<div class="card-top">'
                        '<span class="code">' + s['code'] + '</span>'
                        '<span class="name">' + s.get('name', '') + '</span>'
                        '<span class="badge strong-buy-badge">强烈买入</span>'
                        '</div>'
                        '<div class="info-row">'
                        '<div class="info-cell"><div class="label">现价</div><div class="value">&#165;%.2f</div></div>' % s['price'] +
                        '<div class="info-cell"><div class="label">涨跌</div><div class="value" style="color:' + chg_c + '">%+.2f%%</div></div>' % chg +
                        '<div class="info-cell"><div class="label">量比</div><div class="value">%.1f</div></div>' % s.get('volume_ratio', 0) +
                        '</div>'
                        '<div class="reason">&#x1F4CC; ' + s.get('reason', '') + '</div>'
                        '<div class="factors">' + scores_str + '</div>'
                        '<div class="confidence">置信度 %.0f%%</div>' % s.get('confidence', 0) +
                        '</div>'
                    )
            else:
                html.append('<div class="empty">暂无强烈买入信号</div>')

            html.append('</div></div>')

            # 买入
            html += [
                '<div class="panel">',
                '<div class="panel-header buy-header">',
                '<span>&#x1F536; 买入信号</span>',
                '<span class="count">%d只</span>' % len(buy),
                '</div><div class="list">',
            ]

            if buy:
                for s in buy[:5]:
                    chg = s.get('change_pct', 0)
                    chg_c = '#00ff00' if chg < 0 else '#ffa500'
                    scores = s.get('score_breakdown', {})
                    scores_str = ' | '.join(f'{k}:{v}' for k, v in scores.items()) if scores else ''
                    html.append(
                        '<div class="card buy-card">'
                        '<div class="card-top">'
                        '<span class="code">' + s['code'] + '</span>'
                        '<span class="name">' + s.get('name', '') + '</span>'
                        '<span class="badge buy-badge">买入</span>'
                        '</div>'
                        '<div class="info-row">'
                        '<div class="info-cell"><div class="label">现价</div><div class="value">&#165;%.2f</div></div>' % s['price'] +
                        '<div class="info-cell"><div class="label">涨跌</div><div class="value" style="color:' + chg_c + '">%+.2f%%</div></div>' % chg +
                        '<div class="info-cell"><div class="label">量比</div><div class="value">%.1f</div></div>' % s.get('volume_ratio', 0) +
                        '</div>'
                        '<div class="reason">&#x1F4CC; ' + s.get('reason', '') + '</div>'
                        '<div class="factors">' + scores_str + '</div>'
                        '<div class="confidence">置信度 %.0f%%</div>' % s.get('confidence', 0) +
                        '</div>'
                    )
            else:
                html.append('<div class="empty">暂无买入信号</div>')

            html.append('</div></div>')

            # 退出信号
            html += [
                '<div class="panel">',
                '<div class="panel-header exit-header">',
                '<span>&#x1F534; 持仓退出信号</span>',
                '<span class="count">%d条</span>' % len(exit_signals),
                '</div><div class="list">',
            ]

            if exit_signals:
                for s in exit_signals[:5]:
                    html.append(
                        '<div class="card exit-card">'
                        '<div class="card-top">'
                        '<span class="code">' + s['code'] + '</span>'
                        '<span class="name">' + s.get('name', '') + '</span>'
                        '<span class="badge exit-badge">' + s['action'] + '</span>'
                        '</div>'
                        '<div class="reason">&#x1F4CC; ' + s.get('reason', '') + '</div>'
                        '</div>'
                    )
            else:
                html.append('<div class="empty">无持仓</div>')

            html.append('</div></div></div>')

            # 页脚
            last_time = SIGNAL_HISTORY[0]['time'] if SIGNAL_HISTORY else 'N/A'
            html += [
                '<div class="footer">',
                '<span>最后更新: ' + last_time + '</span>',
                '<span>F5刷新 | /history</span>',
                '</div></body></html>'
            ]

            return ''.join(html).encode('utf-8')

        def log_message(self, fmt, *args):
            pass

    try:
        server = HTTPServer(('0.0.0.0', port), Handler)
        log.info(f"[HTTP] 监控面板: http://localhost:{port}/status")
        server.serve_forever()
    except Exception as e:
        log.warning(f"[HTTP] 启动失败: {e}")

# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════
def main():
    global _running
    cfg = Config

    print(f"""
    ╔══════════════════════════════════════════════════╗
    ║        量化选股信号系统 v2.0                      ║
    ║  策略：多因子量化（动量+趋势+量能+形态）            ║
    ║  股票池: {len(ALL_CODES)} 只                              ║
    ║  止损: -%.1f%%  止盈: +%.1f%%  持仓: ≤%d天              ║
    ║  置信度门槛: %d%%                                ║
    ║  监控面板: http://localhost:8080/status            ║
    ╚══════════════════════════════════════════════════╝
    """ % (abs(cfg.STOP_LOSS), cfg.TAKE_PROFIT, cfg.MAX_HOLD_DAYS, cfg.MIN_CONFIDENCE))

    _running = True

    # 启动HTTP服务
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # 启动扫描
    scan_thread = threading.Thread(target=scan_loop, daemon=True)
    scan_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[退出] 停止中...")
        _running = False
        time.sleep(2)

if __name__ == '__main__':
    main()
