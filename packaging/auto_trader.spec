# -*- mode: python ; coding: utf-8 -*-
# auto_trader.spec — PyInstaller 打包配置
# 运行: cd packaging && pyinstaller auto_trader.spec --clean

import sys, os
from pathlib import Path

block_cipher = None

# PROJECT_ROOT 由 workflow 的 env 设置，fallback 到 packaging 的父目录
_project_root = Path(os.environ.get('PROJECT_ROOT', str(Path(__file__).resolve().parent.parent if '__file__' in dir() else Path.cwd().parent)))
MAIN_SCRIPT = str(_project_root / 'main.py')
STOCK_POOL_JSON = str(_project_root / 'stock_pool.json')

print(f"[PyInstaller] PROJECT_ROOT={_project_root}")
print(f"[PyInstaller] MAIN_SCRIPT={MAIN_SCRIPT}")

a = Analysis(
    [MAIN_SCRIPT],
    pathex=[str(_project_root)],
    binaries=[],
    datas=[
        (STOCK_POOL_JSON, '.'),
    ],
    hiddenimports=[
        'akshare',
        'akshare.stock',
        'akshare.stock.stock_zh_a_spot_em',
        'akshare.stock.stock_zh_a_hist',
        'akshare.cons',
        'akshare.pro',
        'akshare.pro.data_pro',
        'pandas',
        'numpy',
        'requests',
        'urllib3',
        'lxml',
        'openpyxl',
        'aiohttp',
        'json', 'logging', 'datetime', 'threading', 'pathlib',
        'http.server', 'socketserver', 'urllib.request',
        'concurrent.futures', 'queue',
        'certifi', 'charset_normalizer', 'idna', 'python_dateutil',
        'pytz', 'six', 'dateutil',
    ],
    hookspath=[],
    hooksconfig={},
    keys=[],
    win_no_prefer_redirects_version=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='auto_trader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
