# -*- mode: python ; coding: utf-8 -*-
# auto_trader.spec — PyInstaller 打包配置
# 运行: pyinstaller auto_trader.spec

import sys, os
from pathlib import Path

block_cipher = None

# 主入口
a = Analysis(
    ['../main.py'],
    pathex=[Path(__file__).parent.resolve()],
    binaries=[],
    datas=[
        # 股票池 JSON (bundled in EXE)
        ('../stock_pool.json', '.'),
        # akshare 数据文件 (抓取所有依赖)
        ('../data', 'data'),
        ('../strategy', 'strategy'),
        ('../vision', 'vision'),
        ('../config', 'config'),
        ('../risk', 'risk'),
        ('../core', 'core'),
    ],
    hiddenimports=[
        # akshare 核心依赖
        'akshare', 'akshare.stock', 'akshare.stock.stock_zh_a_spot_em',
        'akshare.stock.stock_zh_a_hist',
        'akshare.cons', 'akshare.pro', 'akshare.pro.data_pro',
        'pandas', 'pandas._libs', 'pandas._libs.tslibs',
        'numpy', 'numpy.core', 'numpy.linalg',
        'requests', 'urllib3', 'certifi', 'charset_normalizer',
        'idna', 'python_dateutil', 'pytz', 'six',
        'lxml', 'et_xmlfile', 'openpyxl', 'xlrd', 'xlwt',
        'aiohttp', 'aiohttp_speed_up',
        # 标准库隐式导入
        'json', 'logging', 'datetime', 'threading', 'pathlib',
        'http.server', 'socketserver', 'urllib.request',
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
    upx=True,
    console=False,        # 打包后无黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,            # 可加 icon.ico
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='auto_trader',
)
