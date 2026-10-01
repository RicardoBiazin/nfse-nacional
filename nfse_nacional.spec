# PyInstaller: pyinstaller nfse_nacional.spec  ->  dist/NFSE_Nacional/NFSE_Nacional.exe
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["main.py"],
    datas=[("schemas", "schemas")],
    hiddenimports=collect_submodules("keyring.backends") + ["win32ctypes.core"],
    excludes=["tkinter", "pytest", "xmlsec"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NFSE_Nacional",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="NFSE_Nacional", upx=False)
