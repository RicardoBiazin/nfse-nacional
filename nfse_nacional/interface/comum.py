"""Peças compartilhadas da interface: execução em segundo plano e formatação."""
from __future__ import annotations

import traceback
from decimal import Decimal, InvalidOperation

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from ..cliente_http import ErroApi
from ..servico import ErroValidacao


class _Sinais(QObject):
    ok = Signal(object)
    erro = Signal(object)
    progresso = Signal(str)


class _Tarefa(QRunnable):
    def __init__(self, funcao, com_progresso: bool):
        super().__init__()
        self.funcao = funcao
        self.com_progresso = com_progresso
        self.sinais = _Sinais()

    def run(self):
        try:
            if self.com_progresso:
                r = self.funcao(self.sinais.progresso.emit)
            else:
                r = self.funcao()
            self.sinais.ok.emit(r)
        except Exception as erro:          # noqa: BLE001 - tudo vai para a tela
            erro.__traceback_texto__ = traceback.format_exc()
            self.sinais.erro.emit(erro)


_tarefas_vivas: set = set()


def em_segundo_plano(funcao, ao_terminar=None, ao_falhar=None, progresso=None):
    """Roda `funcao` fora da thread da interface. Com `progresso`, funcao(cb)."""
    t = _Tarefa(funcao, progresso is not None)
    _tarefas_vivas.add(t)

    def fim(_=None):
        _tarefas_vivas.discard(t)
    if ao_terminar:
        t.sinais.ok.connect(ao_terminar)
    if ao_falhar:
        t.sinais.erro.connect(ao_falhar)
    if progresso:
        t.sinais.progresso.connect(progresso)
    t.sinais.ok.connect(fim)
    t.sinais.erro.connect(fim)
    t.setAutoDelete(False)
    QThreadPool.globalInstance().start(t)
    return t


def texto_erro(erro: Exception) -> str:
    if isinstance(erro, ErroValidacao):
        return "Corrija antes de enviar:\n\n• " + "\n• ".join(erro.erros)
    if isinstance(erro, ErroApi):
        if erro.mensagens:
            return f"O sistema nacional recusou (HTTP {erro.status}):\n\n• " + \
                "\n• ".join(str(m) for m in erro.mensagens)
        return str(erro)
    if isinstance(erro, requests.exceptions.SSLError):
        return ("Falha na conexão segura. O servidor recusou o certificado: use um A1 "
                "ICP-Brasil válido do CNPJ da empresa.\n\n" + str(erro)[:300])
    if isinstance(erro, requests.RequestException):
        return f"Falha de comunicação com o sistema nacional:\n\n{erro}"
    return str(erro) or erro.__class__.__name__


def mostrar_erro(pai: QWidget, erro: Exception, titulo: str = "Erro"):
    caixa = QMessageBox(QMessageBox.Icon.Warning, titulo, texto_erro(erro), parent=pai)
    detalhe = getattr(erro, "__traceback_texto__", "")
    corpo = getattr(erro, "corpo", "")
    if detalhe or corpo:
        caixa.setDetailedText((corpo[:4000] + "\n\n" if corpo else "") + detalhe)
    caixa.exec()


def para_decimal(texto: str) -> Decimal | None:
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Valor inválido: {texto!r}") from None


def moeda(valor) -> str:
    if valor in (None, ""):
        return ""
    d = Decimal(str(valor))
    s = f"{d:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


class CampoCodigo(QWidget):
    """QLineEdit de código oficial com busca pela descrição e o descritivo logo abaixo.

    tabela: "servico" (cTribNac), "nbs" ou "municipio" (IBGE). Digitar parte da descrição
    abre a lista; escolher grava só o código. Mantém a interface do QLineEdit usada nas
    telas (text, setText, clear, setPlaceholderText).
    """

    def __init__(self, tabela: str, digitos: int, pai=None):
        from PySide6.QtCore import QStringListModel, Qt, QTimer
        from PySide6.QtWidgets import QCompleter, QLabel, QLineEdit, QVBoxLayout

        from .. import tabelas
        super().__init__(pai)
        self.tabela = tabela
        self.digitos = digitos
        self._padrao = ""
        fonte = {"servico": tabelas.servicos, "nbs": tabelas.nbs,
                 "municipio": tabelas.municipios}[tabela]()
        self._fonte = fonte
        self.edit = QLineEdit()
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #8a8f98; font-size: 11px;")
        comp = QCompleter(QStringListModel([f"{c} - {d}" for c, d in fonte.items()], self), self)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setMaxVisibleItems(12)
        comp.activated.connect(lambda t: QTimer.singleShot(0, lambda: self.setText(t.split(" - ")[0])))
        self.edit.setCompleter(comp)
        self.edit.textChanged.connect(self._atualizar)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lay.addWidget(self.edit)
        lay.addWidget(self.desc)
        self._atualizar()

    # interface de QLineEdit
    def text(self) -> str:
        t = self.edit.text().strip()
        return t.split(" - ")[0].strip() if " - " in t else t

    def setText(self, t: str):
        self.edit.setText(t or "")

    def clear(self):
        self.edit.clear()

    def setPlaceholderText(self, t: str):
        self.edit.setPlaceholderText(t)

    def definir_padrao(self, codigo: str):
        """Código usado quando o campo fica vazio (padrão da empresa): também é descrito."""
        self._padrao = codigo or ""
        self._atualizar()

    def _atualizar(self, *_):
        codigo = "".join(ch for ch in self.text() if ch.isdigit())
        usado = codigo or self._padrao
        if not usado:
            self.desc.setText("")
            return
        desc = self._fonte.get(usado.zfill(self.digitos) if self.tabela == "servico" else usado, "")
        prefixo = "padrão da empresa: " if not codigo else ""
        if desc:
            self.desc.setStyleSheet("color: #8a8f98; font-size: 11px;")
            self.desc.setText(f"{prefixo}{usado} - {desc}")
        elif len(usado) >= self.digitos:
            self.desc.setStyleSheet("color: #d08a1a; font-size: 11px;")
            self.desc.setText(f"{usado}: código não encontrado na tabela oficial")
        else:
            self.desc.setText("")
