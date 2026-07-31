# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


analysis = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[("sample_data", "sample_data")] + collect_data_files("tkinterdnd2"),
    hiddenimports=["openpyxl", "tkinterdnd2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CSV Cleaner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="CSV Cleaner",
)

app = BUNDLE(
    collection,
    name="CSV Cleaner.app",
    bundle_identifier="com.mlynarskim.csvcleaner",
    info_plist={
        "CFBundleDisplayName": "CSV Cleaner",
        "CFBundleName": "CSV Cleaner",
        "CFBundleShortVersionString": "1.1.1",
        "CFBundleVersion": "1.1.1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    },
)
