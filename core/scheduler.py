"""
主调度器 — AutoTrader v2
支持模拟账户直接运行测试
"""
import time
import logging
import signal as sys_signal
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("/Users/dl/WorkBuddy/20260425075457/auto_trader/logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"trader_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("AutoTrader")

from data.market import market
from strategy.engine import StrategyEngine
from vision.ths_api import UnifiedTrader
from risk.manager import RiskManager
from config.settings import LOOP_INTERVAL


class AutoTrader:

    def __init__(self):
        logger.info("=" * 60)
        logger.info("🚀 AutoTrader v2 启动")
        logger.info(f"   交易模式: {__import__('config.settings', fromlist=['VISION']).VISION['mode']}")
        logger.info(f"   循环间隔: {LOOP_INTERVAL}秒")
        logger.info("=" * 60)

        self.engine = StrategyEngine()
        self.trader = UnifiedTrader()
        self.risk = RiskManager()
        self.running = True

        sys_signal.signal(sys_signal.SIGINT, self._shutdown)
        sys_signal.signal(sys_signal.SIGTERM, self._shutdown)

    def _shutdown(self, *args):
        logger.info("收到退出信号，正在安全停止...")
        self.running = False

    def run(self):
        """主循环"""
        while self.running:
            try:
                now = datetime.now()

                # 检查交易时间
                if not market.is_trading_time():
                    nxt = self._seconds_to_next_open()
                    logger.debug(f"非交易时间，{nxt}秒后再检查")
                    time.sleep(min(nxt, 60))
                    continue

                logger.info(f"\n{'='*40}")
                logger.info(f"[{now.strftime('%H:%M:%S')}] 开始评估...")

                # 执行策略评估
                signals = self.engine.evaluate_all()

                if not signals:
                    logger.info("  暂无信号，等待下一轮...")
                else:
                    for signal in signals:
                        self._handle_signal(signal)

                # 每小时输出风控摘要
                if now.minute == 0:
                    summary = self.risk.get_summary()
                    logger.info(f"📊 风控摘要: 今日盈亏={summary['daily_pnl']}元 交易{summary['trade_count']}次")

                time.sleep(LOOP_INTERVAL)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"主循环异常: {e}", exc_info=True)
                time.sleep(10)

        logger.info("AutoTrader 已停止")

    def _handle_signal(self, signal):
        """处理信号"""
        code = "002539"
        name = "云图控股"

        # 风控检查
        ok, reason = self.risk.can_trade(code, signal.action, signal.shares, signal.price or 0)
        if not ok:
            logger.warning(f"⛔ 风控拦截: {reason}")
            return

        # 执行交易
        logger.info(f"\n  📌 信号: {signal.action} {name} {signal.shares}股 @{signal.price}")
        logger.info(f"     策略: {signal.strategy} | 置信度: {signal.confidence:.0%}")
        logger.info(f"     原因: {signal.reason}")

        result = self.trader.execute(
            code=code,
            name=name,
            action=signal.action,
            shares=signal.shares,
            price=signal.price or 0,
            reason=signal.reason,
            strategy=signal.strategy,
            mode="mock"   # 模拟账户模式
        )

        if result["success"]:
            logger.info(f"  ✅ 执行成功 ({result['method']})")
            self.engine.update_position(code, signal.action, signal.shares, signal.price or 0)
            # 模拟账户：PnL=0
            self.risk.record_trade(code, signal.action, signal.shares, signal.price or 0, pnl=0)
        else:
            logger.error(f"  ❌ 执行失败: {result}")

    def _seconds_to_next_open(self) -> int:
        now = datetime.now()
        if now.hour < 9 or (now.hour == 9 and now.minute < 30):
            target = now.replace(hour=9, minute=30, second=0)
        elif now.hour == 11 and now.minute >= 30:
            target = now.replace(hour=13, minute=0, second=0)
        elif now.hour >= 15:
            return 3600
        else:
            target = now.replace(hour=9, minute=30, second=0)
        return max(int((target - now).total_seconds()), 60)


if __name__ == "__main__":
    trader = AutoTrader()
    trader.run()