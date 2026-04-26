"""
market_scanner.py — 全市场扫描 + 异动监控
基于 stock_pool.json 的 108 只股票
监控涨幅/跌幅/量比异动，优先推送做T机会
"""
import json
import time
import logging
import datetime
from pathlib import Path
from data.market import get_realtime_quote

log = logging.getLogger("scanner")

# 加载股票池
POOL_FILE = Path(__file__).parent / "stock_pool.json"
_all_stocks = json.loads(POOL_FILE.read_text(encoding="utf-8"))
SCAN_CODES = [s["code"] for s in _all_stocks]  # ['600016','600032',...]
# 做T重点关注（从完整池中筛选大盘/中小盘/活跃股）
KEY_CODES = [
    "002539",  # 云图控股（主仓）
    "000625",  # 长安汽车
    "002415",  # 海康威视
    "601138",  # 工业富联
    "002594",  # 比亚迪
    "600690",  # 海尔智家
    "000333",  # 美的集团
    "002241",  # 歌尔股份
    "002083",  # 孚日股份
    "600487",  # 亨通光电
]


class MarketScanner:
    """全市场扫描器（扫描 stock_pool.json 全部108只）"""

    def __init__(self, scan_all: bool = False):
        self.scan_all = scan_all
        self.codes_to_scan = SCAN_CODES if scan_all else KEY_CODES
        # 缓存昨日收盘价（用于计算开盘涨跌）
        self.prev_close: dict[str, float] = {}

    def get_top_movers(self, limit: int = 5) -> list[dict]:
        """获取今日涨幅最大的前N只"""
        quotes = get_realtime_quote(self.codes_to_scan)
        movers = []
        for code, q in quotes.items():
            price = q.get("最新价", 0)
            chg   = q.get("涨跌幅", 0)
            if price <= 0 or chg == 0:
                continue
            movers.append({
                "code": code,
                "name": next((s["name"] for s in _all_stocks if s["code"] == code), code),
                "price": price,
                "chg": chg,
                "source": q.get("来源", ""),
            })
        movers.sort(key=lambda x: x["chg"], reverse=True)
        return movers[:limit]

    def get_top_droppers(self, limit: int = 5) -> list[dict]:
        """获取今日跌幅最大的前N只"""
        quotes = get_realtime_quote(self.codes_to_scan)
        droppers = []
        for code, q in quotes.items():
            price = q.get("最新价", 0)
            chg   = q.get("涨跌幅", 0)
            if price <= 0 or chg == 0:
                continue
            droppers.append({
                "code": code,
                "name": next((s["name"] for s in _all_stocks if s["code"] == code), code),
                "price": price,
                "chg": chg,
                "volume_ratio": q.get("量比", 0),
                "source": q.get("来源", ""),
            })
        droppers.sort(key=lambda x: x["chg"])
        return droppers[:limit]

    def get_t_opportunities(self, threshold: float = -1.5) -> list[dict]:
        """
        扫描做T机会（跌幅>=threshold%的活跃股）
        返回: [{code, name, price, chg, volume_ratio, reason}]
        """
        quotes = get_realtime_quote(self.codes_to_scan)
        opps = []
        for code, q in quotes.items():
            price = q.get("最新价", 0)
            chg   = q.get("涨跌幅", 0)
            vr    = q.get("量比", 0)
            if price <= 0:
                continue
            reasons = []
            if chg <= threshold:
                reasons.append(f"跌幅{chg:.2f}%超阈值")
            if vr >= 1.5:
                reasons.append(f"量比{vr:.2f}放大")
            if chg <= threshold * 0.5:
                reasons.append("超跌关注")
            if reasons:
                opps.append({
                    "code": code,
                    "name": next((s["name"] for s in _all_stocks if s["code"] == code), code),
                    "price": price,
                    "chg": chg,
                    "volume_ratio": vr,
                    "reasons": reasons,
                    "priority": abs(chg) + vr,
                })
        opps.sort(key=lambda x: x["priority"], reverse=True)
        return opps

    def scan_and_report(self) -> str:
        """生成完整扫描报告"""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        report = [f"\n{'='*55}", f"📊 全市场扫描报告 {now}", f"{'='*55}"]

        # 涨幅榜
        top_rise = self.get_top_movers(5)
        report.append("\n📈 今日涨幅榜 TOP5:")
        for i, s in enumerate(top_rise, 1):
            report.append(f"  {i}. {s['name']}({s['code']}) ¥{s['price']:.3f} {s['chg']:+.2f}%")

        # 跌幅榜
        top_drop = self.get_top_droppers(5)
        report.append("\n📉 今日跌幅榜 TOP5:")
        for i, s in enumerate(top_drop, 1):
            vr = s.get("volume_ratio", 0)
            report.append(f"  {i}. {s['name']}({s['code']}) ¥{s['price']:.3f} {s['chg']:+.2f}% 量比{vr:.2f}")

        # 做T机会
        opps = self.get_t_opportunities(threshold=-1.5)
        report.append(f"\n🎯 做T机会 ({len(opps)}只跌幅超-1.5%且量比放大):")
        if not opps:
            report.append("  （暂无明显机会）")
        for s in opps[:10]:
            report.append(f"  ⭐ {s['name']}({s['code']}) ¥{s['price']:.3f} "
                          f"{s['chg']:+.2f}% 量比{s['volume_ratio']:.2f}")
            report.append(f"     原因: {' | '.join(s['reasons'])}")

        report.append(f"\n{'='*55}")
        return "\n".join(report)


# ──────────────── 独立测试 ────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    scanner = MarketScanner(scan_all=False)
    print(scanner.scan_and_report())
