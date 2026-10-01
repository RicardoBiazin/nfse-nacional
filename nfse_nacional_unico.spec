# Versão em ARQUIVO ÚNICO, para rodar de pasta de rede / Google Drive:
#   pyinstaller nfse_nacional_unico.spec  ->  dist/NFSE_Nacional.exe
# O .exe extrai o Python e as DLLs para a pasta temporária LOCAL antes de iniciar,
# então o Windows nunca carrega DLL direto do drive virtual (erro "Failed to load Python DLL").
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["main.py"],
    datas=[("schemas", "schemas"), ("recursos", "recursos")],
    hiddenimports=collect_submodules("keyring.backends") + ["win32ctypes.core"],
    excludes=["tkinter", "pytest", "xmlsec", "pypdfium2", "pypdf",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NFSE_Nacional",
          console=False, upx=False, icon="recursos/icone.ico",
          runtime_tmpdir=None)
