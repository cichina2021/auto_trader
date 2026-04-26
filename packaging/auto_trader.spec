# -*- mode: python ; coding: utf-8 -*-
# auto_trader.spec — PyInstaller 打包配置 (简化版)
# 运行: pyinstaller auto_trader.spec --clean

import sys, os
from pathlib import Path

block_cipher = None

# 主入口脚本
a = Analysis(
    [str(Path(__file__).parent.parent / 'main.py')],
    pathex=[str(Path(__file__).parent.parent.resolve())],
    binaries=[],
    datas=[
        (str(Path(__file__).parent.parent / 'stock_pool.json'), '.'),
    ],
    hiddenimports=[
        # akshare（核心数据源）
        'akshare',
        'akshare.stock',
        'akshare.stock.stock_zh_a_spot_em',
        'akshare.stock.stock_zh_a_hist',
        'akshare.cons',
        'akshare.pro',
        'akshare.pro.data_pro',
        'akshare.optional',
        'akshare.derivative',
        # 数据处理
        'pandas',
        'numpy',
        'requests',
        'urllib3',
        'lxml',
        'openpyxl',
        'xlrd',
        'aiohttp',
        # 标准库
        'json', 'logging', 'datetime', 'threading', 'pathlib',
        'http.server', 'socketserver', 'urllib.request',
        'email', 'html', 'xml', 'csv', 'io',
        'concurrent.futures', 'queue', 'socket', 'struct',
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

# 单文件模式
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
