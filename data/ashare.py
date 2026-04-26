"""
Ashare — 开源极简A股实时行情API
来源: https://github.com/CodeBang06/miniqmt-xtquant-Ashare
核心: 新浪财经+腾讯股票双数据源，自动切换

即引即用，单文件设计，无需token
"""
import re
import time
import json
import logging
from typing import Optional
from datetime import datetime
import urllib.request
import urllib.error
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================
# 辅助函数
# ============================================================

def _get_header() -> dict:
    """构造HTTP请求头（模拟浏览器）"""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn',
    }


def _http_get(url: str, timeout: int = 10) -> Optional[str]:
    """HTTP GET请求，带重试"""
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=_get_header())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode('gbk', errors='replace')
        except Exception as e:
            logger.debug(f"请求失败(尝试{attempt+1}): {e}")
            time.sleep(1)
    return None


def _parse_stock_code(code: str) -> tuple:
    """
    解析股票代码，支持多种格式
    返回: (sina_code, tencent_code)
    """
    code = code.strip().upper()

    # 已经是新浪格式
    if code.startswith('SH') or code.startswith('SZ'):
        sina = code
        num = code[2:]
    # 已经是腾讯格式
    elif code.endswith('.XSHG') or code.endswith('.XSHE'):
        num = code[:6]
        sina = ('sh' if code.endswith('.XSHG') else 'sz') + num
    # 纯数字格式
    else:
        num = code
        if num.startswith('6') or num == '000001':
            sina = 'sh' + num
        else:
            sina = 'sz' + num

    # 腾讯格式
    tencent = 'hk' + num if len(num) == 5 else ('sh' + num if num.startswith('6') else 'sz' + num)

    return sina, tencent


# ============================================================
# 行情获取核心
# ============================================================

def get_price_simple(code: str, freq: str = '1d', count: int = 5,
                      end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    获取股票行情数据

    参数:
        code: 股票代码（支持 sh600519 / 600519.XSHG / 600519 等格式）
        freq: 频率 (1d/1w/1M/1m/5m/15m/30m/60m)
        count: 获取数据条数
        end_date: 截止日期 YYYY-MM-DD

    返回:
        DataFrame: columns=[date, open, close, high, low, volume, amount]
    """
    sina_code, _ = _parse_stock_code(code)

    # ---- 日线/周线/月线 ----
    if freq in ('1d', '1w', '1M'):
        url = f"https://finance.sina.com.cn/realstock/company/{sina_code}/hisdata/klc_kl.js?d={count}"
        text = _http_get(url)
        if not text:
            # 降级：用腾讯接口
            return _get_price_tencent_min(code, freq, count, end_date)

        try:
            # 解析JS数据格式: var hisdata_xx=[{...},...]
            match = re.search(r'=\s*(\[.*?\]);?\s*$', text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(1))
            if not data:
                return None

            records = []
            for item in data:
                records.append({
                    'date': item.get('date', ''),
                    'open': float(item.get('open', 0)),
                    'close': float(item.get('close', 0)),
                    'high': float(item.get('high', 0)),
                    'low': float(item.get('low', 0)),
                    'volume': float(item.get('volume', 0)),
                    'amount': float(item.get('amount', 0)),
                })

            df = pd.DataFrame(records)
            if freq == '1d':
                return df.tail(count)
            elif freq == '1w':
                return df.groupby(df['date'].str[:4] + '-W' + df['date'].str[5:7]).last().reset_index()
            elif freq == '1M':
                return df.groupby(df['date'].str[:7]).last().reset_index()

        except Exception as e:
            logger.debug(f"新浪日线解析失败: {e}")
            return _get_price_tencent_min(code, freq, count, end_date)

    # ---- 分钟线 ----
    else:
        return _get_price_tencent_min(code, freq, count, end_date)

    return None


def _get_price_tencent_min(code: str, freq: str, count: int,
                             end_date: Optional[str]) -> Optional[pd.DataFrame]:
    """腾讯财经分钟线数据"""
    _, tencent_code = _parse_stock_code(code)

    # 频率映射
    freq_map = {
        '1m': '1', '5m': '5', '15m': '15',
        '30m': '30', '60m': '60', '1d': 'day',
    }
    qt_freq = freq_map.get(freq, 'day')

    if qt_freq == 'day':
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq"
               f"&param={tencent_code},day,,,{count},qfq")
    else:
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/kline/mkline"
               f"?param={tencent_code},m{qt_freq},{count}")

    text = _http_get(url)
    if not text:
        return None

    try:
        # 去掉变量赋值前缀
        text = re.sub(r'^[^{]*', '', text.strip())
        data = json.loads(text)

        if qt_freq == 'day':
            qfqday = data.get('data', {}).get(tencent_code, {}).get('qfqday', [])
            records = []
            for item in qfqday[-count:]:
                if isinstance(item, list) and len(item) >= 6:
                    records.append({
                        'date': item[0],
                        'open': float(item[1]),
                        'close': float(item[2]),
                        'high': float(item[3]),
                        'low': float(item[4]),
                        'volume': float(item[5]),
                        'amount': float(item[5]) * float(item[2]) if len(item) > 2 else 0,
                    })
            df = pd.DataFrame(records)
            return df

        else:
            # 分钟线
            mdata = data.get('data', {}).get(tencent_code, {}).get('m' + qt_freq, [])
            records = []
            for item in mdata[-count:]:
                if isinstance(item, list) and len(item) >= 6:
                    records.append({
                        'date': item[0],
                        'open': float(item[1]),
                        'close': float(item[2]),
                        'high': float(item[3]),
                        'low': float(item[4]),
                        'volume': float(item[5]),
                        'amount': float(item[5]) * float(item[2]),
                    })
            df = pd.DataFrame(records)
            return df

    except Exception as e:
        logger.debug(f"腾讯行情解析失败: {e}")
    return None


def get_realtime_quotes(codes: list) -> Optional[pd.DataFrame]:
    """
    批量获取实时行情（新浪接口，一次请求全部）
    codes: 股票代码列表，如 ['sh600519', 'sz000001', '002539']
    """
    if not codes:
        return None

    codes_str = ','.join(codes)
    url = f"https://hq.sinajs.cn/list={codes_str}"

    text = _http_get(url, timeout=15)
    if not text:
        return None

    try:
        pattern = r'hq_str_[a-z]{2}(\d+)="([^"]+)"'
        matches = re.findall(pattern, text)
        records = []
        for code, content in matches:
            parts = content.split(',')
            if len(parts) > 32:
                records.append({
                    'code': code,
                    'name': parts[0],
                    'open': float(parts[1]) if parts[1] else 0,
                    'close': float(parts[3]) if parts[3] else 0,   # 昨收
                    'price': float(parts[3]) if len(parts) > 3 else 0,  # 当前价格用昨收占位
                    'high': float(parts[4]) if parts[4] else 0,
                    'low': float(parts[5]) if parts[5] else 0,
                    'volume': float(parts[8]) if parts[8] else 0,
                    'amount': float(parts[9]) if parts[9] else 0,
                    'change_pct': 0.0,  # 需计算
                })

        if records:
            df = pd.DataFrame(records)
            # 计算涨跌幅
            df['change_pct'] = ((df['price'] - df['close']) / df['close'] * 100).round(2)
            return df
    except Exception as e:
        logger.error(f"批量行情解析失败: {e}")
    return None


# ============================================================
# 测试入口
# ============================================================
if __name__ == "__main__":
    # 测试单只股票
    df = get_price_simple('002539', freq='1d', count=5)
    print("日线数据:\n", df)

    # 测试分钟线
    df2 = get_price_simple('002539', freq='60m', count=10)
    print("\n60分钟数据:\n", df2)

    # 测试批量实时
    df3 = get_realtime_quotes(['sh002539'])
    print("\n实时行情:\n", df3)
