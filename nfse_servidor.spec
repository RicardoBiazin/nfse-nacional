# Servidor web interno, arquivo único:  pyinstaller --noconfirm --distpath dist_unico nfse_servidor.spec
#   -> dist_unico\NFSE_Servidor.exe  (rodar | instalar-servico | importar-dados-desktop | criar-admin)
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["servidor.py"],
    datas=[("schemas", "schemas"), ("recursos", "recursos"),
           ("nfse_nacional/web/templates", "nfse_nacional/web/templates"),
           ("nfse_nacional/web/static", "nfse_nacional/web/static")],
    hiddenimports=collect_submodules("keyring.backends") + collect_submodules("uvicorn")
                  + ["win32ctypes.core"],
    excludes=["tkinter", "pytest", "xmlsec", "pypdfium2", "PySide6", "shiboken6"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NFSE_Servidor",
          console=True, upx=False, icon="recursos/icone.ico")
