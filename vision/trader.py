"""
视觉交易层 — 纯视觉方案
核心原理：
  1. Mac侧 将交易指令写入 JSON 信号文件（共享文件夹）
  2. Windows侧运行 vision_executor.py，读取信号，截图识别，控制同花顺下单

本文件是 Mac侧的信号发布器
"""
import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from config.settings import VISION

logger = logging.getLogger(__name__)


class SignalPublisher:
    """
    Mac侧：将交易信号写入共享目录
    Windows侧：vision_executor.py 读取并执行
    """

    def __init__(self):
        self.signal_dir = Path(VISION["signal_dir"])
        self.signal_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"信号目录: {self.signal_dir}")

    def publish(self, code: str, action: str, shares: int, price: float, reason: str) -> str:
        """
        发布交易信号
        返回: signal_id
        """
        signal_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{code}_{action}"
        signal = {
            "id": signal_id,
            "code": code,
            "action": action,          # BUY / SELL
            "shares": shares,
            "price": price,            # 参考价，实际按市价委托
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",       # pending / executing / done / failed
        }

        signal_file = self.signal_dir / f"{signal_id}.json"
        with open(signal_file, "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)

        logger.info(f"📤 信号已发布: {action} {code} {shares}股 @{price} | {reason}")
        return signal_id

    def wait_result(self, signal_id: str, timeout: int = 60) -> dict:
        """等待信号执行结果"""
        signal_file = self.signal_dir / f"{signal_id}.json"
        start = time.time()
        while time.time() - start < timeout:
            try:
                with open(signal_file, "r", encoding="utf-8") as f:
                    signal = json.load(f)
                if signal["status"] in ("done", "failed"):
                    return signal
            except:
                pass
            time.sleep(2)
        return {"status": "timeout", "id": signal_id}


# ============================================================
# Windows侧执行器（需部署到Windows虚拟机运行）
# 文件: vision/vision_executor_win.py
# ============================================================
WINDOWS_EXECUTOR_CODE = '''
"""
Windows侧 视觉执行器
需要在 Windows 虚拟机（安装了同花顺）上运行
依赖: pyautogui, pillow, pytesseract, pywin32
"""
import json
import time
import os
import logging
from pathlib import Path
from datetime import datetime

try:
    import pyautogui
    import win32gui
    import win32con
    from PIL import Image, ImageGrab
    import pytesseract
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    print("请安装: pip install pyautogui pillow pytesseract pywin32")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SIGNAL_DIR = r"Z:\\trading_signals"   # 共享文件夹路径（根据实际Parallels共享路径修改）
THS_WINDOW = "同花顺"

pyautogui.FAILSAFE = True   # 鼠标移到左上角紧急停止
pyautogui.PAUSE = 0.5


def find_ths_window():
    """找到同花顺主窗口"""
    hwnd = win32gui.FindWindow(None, THS_WINDOW)
    if hwnd == 0:
        # 模糊匹配
        def callback(h, hwnds):
            if win32gui.IsWindowVisible(h):
                title = win32gui.GetWindowText(h)
                if "同花顺" in title:
                    hwnds.append(h)
        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        return hwnds[0] if hwnds else None
    return hwnd


def activate_ths():
    """激活同花顺窗口"""
    hwnd = find_ths_window()
    if not hwnd:
        logger.error("未找到同花顺窗口！")
        return False
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    return True


def open_trade_panel(action: str):
    """打开交易面板"""
    if action == "BUY":
        pyautogui.hotkey("F2")   # 同花顺买入快捷键
    else:
        pyautogui.hotkey("F3")   # 同花顺卖出快捷键
    time.sleep(0.8)


def fill_and_submit(code: str, shares: int, price_type: str = "market"):
    """
    填写股票代码、数量并提交
    price_type: market=市价 / limit=限价
    """
    # 输入股票代码
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(code, interval=0.05)
    pyautogui.press("enter")
    time.sleep(0.3)

    # 清空并填写数量（Tab到数量框）
    pyautogui.press("tab")
    pyautogui.press("tab")
    pyautogui.hotkey("ctrl", "a")
    pyautogui.typewrite(str(shares), interval=0.05)

    # 确认下单
    pyautogui.press("enter")
    time.sleep(0.5)

    # 弹窗确认（如有）
    pyautogui.press("enter")
    time.sleep(0.3)


def execute_signal(signal: dict) -> bool:
    """执行交易信号"""
    code = signal["code"]
    action = signal["action"]
    shares = signal["shares"]

    logger.info(f"执行信号: {action} {code} {shares}股")

    if not activate_ths():
        return False

    open_trade_panel(action)
    fill_and_submit(code, shares)

    logger.info(f"✅ 执行完成: {action} {code} {shares}股")
    return True


def main():
    """主循环：监控信号文件夹"""
    signal_dir = Path(SIGNAL_DIR)
    logger.info(f"🚀 Windows执行器启动，监控: {signal_dir}")

    processed = set()

    while True:
        try:
            for f in signal_dir.glob("*.json"):
                if f.stem in processed:
                    continue
                with open(f, "r", encoding="utf-8") as fp:
                    signal = json.load(fp)

                if signal.get("status") != "pending":
                    processed.add(f.stem)
                    continue

                # 标记为执行中
                signal["status"] = "executing"
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(signal, fp, ensure_ascii=False, indent=2)

                # 执行
                success = execute_signal(signal)
                signal["status"] = "done" if success else "failed"
                signal["executed_at"] = datetime.now().isoformat()

                with open(f, "w", encoding="utf-8") as fp:
                    json.dump(signal, fp, ensure_ascii=False, indent=2)

                processed.add(f.stem)

        except Exception as e:
            logger.error(f"执行器错误: {e}")

        time.sleep(3)


if __name__ == "__main__":
    main()
'''


def write_windows_executor():
    """将Windows执行器代码写到文件"""
    output_path = Path(__file__).parent / "vision_executor_win.py"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(WINDOWS_EXECUTOR_CODE.strip())
    print(f"Windows执行器已生成: {output_path}")
    print("请将此文件复制到Windows虚拟机并运行")


# 生成Windows执行器文件
write_windows_executor()
