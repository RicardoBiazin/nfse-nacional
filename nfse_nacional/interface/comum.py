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
