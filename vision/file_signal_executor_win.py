"""
Windows侧 执行器 — 监听共享文件夹，执行交易信号
复制到 Windows虚拟机（Parallels）中运行

依赖安装（Windows命令行）：
    pip install pyautogui pywinauto pillow pytesseract requests

Tesseract OCR 安装：
    https://github.com/UB-Mannheim/tesseract/wiki
    安装后添加PATH，或修改下面的 TESSERACT_CMD 路径

Parallels 共享文件夹：
    Mac共享文件夹 → Windows中通常是 Z:\trading_signals

同花顺模拟账户准备：
    1. 打开同花顺 → 登录模拟账户
    2. 工具栏 → 【工具】→【设置】→【交易设置】
    3. 设置：委托前确认=否，快速交易=是
    4. 调整窗口大小到合适位置

快捷键（同花顺默认）：
    F2 = 买入，F3 = 卖出，Enter = 确认
"""
import json
import time
import logging
import os
from pathlib import Path
from datetime import datetime

# ---- Windows依赖 ----
try:
    import pyautogui
    import win32gui
    import win32con
    import win32api
    from PIL import Image, ImageGrab
    import pytesseract
    import requests
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    print("❌ 缺少依赖！请运行：pip install pyautogui pywinauto pillow pytesseract requests")
    print("   并安装 Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki")

# ---- 配置区（需要修改）----
SIGNAL_DIR = r"Z:\trading_signals"          # Parallels共享文件夹路径
THS_EXE = r"C:\同花顺软件\同花顺\xiadan.exe"  # 同花顺路径
THS_WINDOW = "同花顺"
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
LOG_DIR = r"C:\auto_trader_logs"

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/executor_{datetime.now().strftime('%Y%m%d')}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("WinExecutor")


# ============================================================
# 同花顺操作模块
# ============================================================

def find_window(title: str = THS_WINDOW) -> int:
    """找到同花顺窗口句柄"""
    hwnd = win32gui.FindWindow(None, title)
    if hwnd:
        return hwnd

    # 模糊匹配
    def callback(h, results):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if title in t:
                results.append(h)
    results = []
    win32gui.EnumWindows(callback, results)
    return results[0] if results else 0


def activate_window(hwnd: int) -> bool:
    """激活窗口到前台"""
    if not hwnd:
        return False
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.error(f"激活窗口失败: {e}")
        return False


def check_ths_running() -> bool:
    """检查同花顺是否运行"""
    try:
        win32api.GetClassName(find_window())
        return True
    except:
        return False


def ths_buy(code: str, shares: int, price: float = None) -> bool:
    """
    同花顺买入操作
    流程：F2 → 输入代码 → Tab → 输入数量 → Enter确认
    """
    hwnd = find_window()
    if not activate_window(hwnd):
        logger.error("无法激活同花顺窗口")
        return False

    try:
        # 打开买入面板（F2快捷键）
        pyautogui.press("f2")
        time.sleep(0.6)

        # 输入股票代码
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.typewrite(code, interval=0.05)
        pyautogui.press("enter")
        time.sleep(0.5)

        # Tab到价格框（通常不需要改，用默认委托价）
        # pyautogui.press("tab")

        # Tab到数量框
        pyautogui.press("tab")
        time.sleep(0.2)

        # 输入数量
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(str(shares), interval=0.03)

        # 确认下单
        pyautogui.press("enter")
        time.sleep(0.5)
        pyautogui.press("enter")  # 再次确认（如果有确认弹窗）
        time.sleep(0.3)

        logger.info(f"✅ 买入下单成功: {code} {shares}股")
        return True

    except Exception as e:
        logger.error(f"买入下单失败: {e}")
        return False


def ths_sell(code: str, shares: int, price: float = None) -> bool:
    """
    同花顺卖出操作
    流程：F3 → 输入代码 → Tab → 输入数量 → Enter确认
    """
    hwnd = find_window()
    if not activate_window(hwnd):
        logger.error("无法激活同花顺窗口")
        return False

    try:
        # 打开卖出面板（F3快捷键）
        pyautogui.press("f3")
        time.sleep(0.6)

        # 输入股票代码
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.typewrite(code, interval=0.05)
        pyautogui.press("enter")
        time.sleep(0.5)

        # Tab到数量框
        pyautogui.press("tab")
        pyautogui.press("tab")
        time.sleep(0.2)

        # 输入数量
        pyautogui.hotkey("ctrl", "a")
        pyautogui.typewrite(str(shares), interval=0.03)

        # 确认下单
        pyautogui.press("enter")
        time.sleep(0.5)
        pyautogui.press("enter")
        time.sleep(0.3)

        logger.info(f"✅ 卖出下单成功: {code} {shares}股")
        return True

    except Exception as e:
        logger.error(f"卖出下单失败: {e}")
        return False


# ============================================================
# 截图OCR辅助（可选）
# ============================================================

def capture_ths_price(code: str) -> float:
    """
    截图并OCR识别同花顺中的价格（用于验证下单价格）
    需要根据实际界面调整截图区域坐标
    """
    if not HAS_DEPS:
        return 0.0

    try:
        # 截取同花顺行情区（需要根据实际界面调整region参数）
        screenshot = ImageGrab.grab()
        # region = (x, y, width, height) 根据实际界面调整
        # price_area = screenshot.crop((100, 200, 400, 300))
        # text = pytesseract.image_to_string(price_area, config='--psm 6')
        # 解析价格数字...
        return 0.0
    except Exception as e:
        logger.debug(f"OCR识别失败: {e}")
        return 0.0


# ============================================================
# 信号处理主循环
# ============================================================

def process_signal(signal: dict) -> dict:
    """处理单个交易信号"""
    code = signal["code"]
    name = signal.get("name", code)
    action = signal["action"].upper()
    shares = signal["shares"]
    price = signal.get("price", 0)
    mode = signal.get("mode", "mock")

    logger.info(f"处理信号 [{signal['id']}]: {action} {code}({name}) {shares}股 @{price} | {signal.get('reason','')}")

    # 模式检查
    if mode == "mock":
        logger.info(f"🧪 模拟账户模式: {action} {code} {shares}股")
        # 模拟账户：直接标记成功（实际下单跳过）
        time.sleep(1)  # 模拟下单延迟
        return {"status": "confirmed", "executed_at": datetime.now().isoformat()}

    # 实盘模式：执行真实下单
    if action == "BUY":
        success = ths_buy(code, shares, price)
    elif action == "SELL":
        success = ths_sell(code, shares, price)
    else:
        success = False

    return {
        "status": "done" if success else "failed",
        "executed_at": datetime.now().isoformat(),
        "executed_price": price,
        "executed_shares": shares,
    }


def main():
    """主循环"""
    if not HAS_DEPS:
        logger.error("依赖不全，无法运行！")
        return

    os.makedirs(LOG_DIR, exist_ok=True)
    signal_dir = Path(SIGNAL_DIR)

    if not signal_dir.exists():
        logger.error(f"信号目录不存在: {signal_dir}")
        logger.info("请检查 Parallels 共享文件夹设置")
        return

    logger.info("=" * 50)
    logger.info("🚀 Windows执行器启动")
    logger.info(f"信号目录: {signal_dir}")
    logger.info(f"同花顺: {THS_WINDOW} ({'已运行' if check_ths_running() else '未运行'})")
    logger.info("=" * 50)

    processed = set()

    while True:
        try:
            for f in sorted(signal_dir.glob("*.json")):
                if f.stem in processed:
                    continue

                with open(f, "r", encoding="utf-8") as fp:
                    signal = json.load(fp)

                if signal.get("status") != "pending":
                    processed.add(f.stem)
                    continue

                # 标记执行中
                signal["status"] = "executing"
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(signal, fp, ensure_ascii=False, indent=2)

                # 执行
                result = process_signal(signal)
                signal.update(result)

                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(signal, fp, ensure_ascii=False, indent=2)

                processed.add(f.stem)
                logger.info(f"信号 {f.stem} 处理完成: {result['status']}")

        except Exception as e:
            logger.error(f"主循环异常: {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
