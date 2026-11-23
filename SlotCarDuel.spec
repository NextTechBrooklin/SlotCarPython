# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build spec - run via .\build_exe.ps1
from PyInstaller.utils.hooks import collect_data_files

datas = [("assets", "assets")]
datas += collect_data_files("customtkinter")

a = Analysis(
    ["run_app.py"],
    pathex=["src"],
    datas=datas,
    hiddenimports=["slotcar.ui.app"],
    excludes=["numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SlotCarDuel",
    icon="assets/app.ico",
    console=False,
    upx=True,
)
