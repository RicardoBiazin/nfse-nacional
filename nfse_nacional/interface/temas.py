"""Temas da interface: claro, escuro, sunset e azul claro (paleta do Fusion).

A escolha fica em preferencias.ini na pasta de dados; sem escolha, segue o modo claro/escuro do Windows.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

# nome -> (rótulo, cores). Cores: fundo da janela, fundo de campos, alternado, texto,
# botão, destaque (seleção), texto do destaque, link, texto desabilitado.
TEMAS = {
    "claro": ("Claro", dict(janela="#f4f6f8", base="#ffffff", alternada="#eef1f4", texto="#1d2733",
                            botao="#e9edf1", destaque="#2b5cb8", texto_destaque="#ffffff",
                            link="#2b3f8c", desabilitado="#9aa3ad")),
    "escuro": ("Escuro", dict(janela="#1e2329", base="#15191e", alternada="#1b2026", texto="#e3e7ec",
                              botao="#2a3139", destaque="#3d6fd1", texto_destaque="#ffffff",
                              link="#8fa8ff", desabilitado="#6b7581")),
    "sunset": ("Sunset", dict(janela="#2a1b2d", base="#1f1422", alternada="#2f1f33", texto="#ffe7d6",
                              botao="#43293f", destaque="#ff7a4d", texto_destaque="#1f1422",
                              link="#ffb38a", desabilitado="#8c7280")),
    "azul": ("Azul claro", dict(janela="#e6f1fb", base="#ffffff", alternada="#eef6fd", texto="#0f2a44",
                                botao="#d3e6f7", destaque="#2f80c9", texto_destaque="#ffffff",
                                link="#1f5f9e", desabilitado="#8ea3b8")),
}


def _config() -> QSettings:
    # Arquivo na pasta de dados (não o registro): os testes isolam a pasta e não sujam o PC.
    from ..config import pasta_dados
    return QSettings(str(pasta_dados() / "preferencias.ini"), QSettings.Format.IniFormat)


def _do_sistema() -> str:
    dicas = QGuiApplication.styleHints()
    return "escuro" if dicas.colorScheme() == Qt.ColorScheme.Dark else "claro"


def tema_salvo() -> str:
    nome = _config().value("tema", "", str)
    return nome if nome in TEMAS else _do_sistema()


def paleta(nome: str) -> QPalette:
    c = {k: QColor(v) for k, v in TEMAS[nome][1].items()}
    p = QPalette()
    R = QPalette.ColorRole
    for papel, cor in ((R.Window, c["janela"]), (R.WindowText, c["texto"]), (R.Base, c["base"]),
                       (R.AlternateBase, c["alternada"]), (R.Text, c["texto"]),
                       (R.Button, c["botao"]), (R.ButtonText, c["texto"]),
                       (R.Highlight, c["destaque"]), (R.HighlightedText, c["texto_destaque"]),
                       (R.Link, c["link"]), (R.ToolTipBase, c["base"]), (R.ToolTipText, c["texto"]),
                       (R.PlaceholderText, c["desabilitado"]), (R.BrightText, QColor("#ff5c5c"))):
        p.setColor(papel, cor)
    G = QPalette.ColorGroup.Disabled
    for papel in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G, papel, c["desabilitado"])
    return p


def aplicar(nome: str, app: QApplication | None = None, salvar: bool = False):
    app = app or QApplication.instance()
    if nome not in TEMAS:
        nome = _do_sistema()
    app.setPalette(paleta(nome))
    if salvar:
        _config().setValue("tema", nome)
    return nome
