# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

app_name = "Domina"
entry_script = os.path.join("src", "domina_app", "main.py")

ffmpeg_dir = os.path.join("third_party", "ffmpeg", "bin")
extra_datas = []
if os.path.isdir(ffmpeg_dir):
    for filename in os.listdir(ffmpeg_dir):
        extra_datas.append((os.path.join(ffmpeg_dir, filename), "ffmpeg"))

hidden_imports = collect_submodules("pyttsx3")

analysis = Analysis(
    [entry_script],
    pathex=["."],
    binaries=[],
    datas=extra_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
