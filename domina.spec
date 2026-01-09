# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

project_root = os.path.abspath(os.path.dirname(__file__))
ffmpeg_dir = os.path.join(project_root, "third_party", "ffmpeg")

extra_datas = collect_data_files("pyttsx3")
if os.path.isdir(ffmpeg_dir):
    extra_datas.append((ffmpeg_dir, "third_party/ffmpeg"))


a = Analysis(
    [os.path.join("app", "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=extra_datas,
    hiddenimports=["pyttsx3.drivers.sapi5"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
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
    name="DominaOffline",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DominaOffline",
)
