"""Janela principal."""
from __future__ import annotations

import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import VERSAO, cofre
from ..banco import Banco
from ..servico import Emissor
from .aba_emitir import AbaEmitir
from .aba_notas import AbaNotas
from .comum import mostrar_erro
from .dialogo_empresa import DialogoEmpresa


class Janela(QMainWindow):
    def __init__(self, banco: Banco | None = None):
        super().__init__()
        self.banco = banco or Banco()
        self._emissor: Emissor | None = None
        self.setWindowTitle(f"NFS-e Nacional {VERSAO}")
        self.resize(1200, 760)

        self.empresas = QComboBox(); self.empresas.setMinimumWidth(380)
        self.empresas.currentIndexChanged.connect(self._trocar_empresa)
        self.selo = QLabel(); self.selo.setMargin(4)
        bt_nova = QPushButton("Nova empresa"); bt_nova.clicked.connect(self._nova)
        bt_editar = QPushButton("Configurar empresa"); bt_editar.clicked.connect(self._editar)
        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:")); topo.addWidget(self.empresas)
        topo.addWidget(bt_editar); topo.addWidget(bt_nova); topo.addStretch(1); topo.addWidget(self.selo)

        self.abas = QTabWidget()
        self.aba_emitir = AbaEmitir(self.banco, self.emissor)
        self.aba_notas = AbaNotas(self.banco, self.emissor, self._empresa_atual)
        self.aba_emitir.emitida.connect(
            lambda: self.aba_notas.mostrar_ambiente(self._empresa_atual().ambiente))
        self.abas.addTab(self.aba_emitir, "Emitir NFS-e")
        self.abas.addTab(self.aba_notas, "Notas")
        self.abas.currentChanged.connect(lambda i: i == 1 and self.aba_notas.recarregar())

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(topo); lay.addWidget(self.abas)
        self.setCentralWidget(central)

        sobre = QAction("Sobre", self)
        sobre.triggered.connect(lambda: QMessageBox.about(
            self, "Sobre", f"NFS-e Nacional {VERSAO}\n\nEmissão (Sefin Nacional) e consulta (ADN) "
            "da NFS-e Padrão Nacional.\nLeiaute DPS 1.01."))
        self.menuBar().addAction(sobre)

        self._carregar_empresas()

    # ------------------------------------------------------------ empresas
    def _carregar_empresas(self, selecionar_id: int | None = None):
        self.empresas.blockSignals(True)
        self.empresas.clear()
        for e in self.banco.empresas():
            self.empresas.addItem(f"{e.razao or '(sem nome)'} — {e.cnpj}", e.id)
        self.empresas.blockSignals(False)
        if selecionar_id is not None:
            i = self.empresas.findData(selecionar_id)
            self.empresas.setCurrentIndex(max(i, 0))
        self._trocar_empresa()

    def _empresa_atual(self):
        id_ = self.empresas.currentData()
        return self.banco.empresa(id_) if id_ is not None else None

    def _trocar_empresa(self, *_):
        self._emissor = None
        e = self._empresa_atual()
        if not e:
            self.selo.setText("Cadastre uma empresa")
            self.selo.setStyleSheet("")
        elif e.ambiente == "producao":
            self.selo.setText("  PRODUÇÃO  ")
            self.selo.setStyleSheet("background:#b3261e; color:white; font-weight:bold; border-radius:4px")
        else:
            self.selo.setText("  PRODUÇÃO RESTRITA (testes)  ")
            self.selo.setStyleSheet("background:#f2b705; color:black; font-weight:bold; border-radius:4px")
        self.aba_emitir.preencher_padroes(self.emissor(silencioso=True))
        self.aba_notas.recarregar()

    def emissor(self, silencioso: bool = False) -> Emissor | None:
        if self._emissor and self._emissor.empresa.id == self.empresas.currentData():
            return self._emissor
        e = self._empresa_atual()
        if not e:
            if not silencioso:
                QMessageBox.information(self, "Empresa", "Cadastre uma empresa primeiro.")
            return None
        if silencioso and not e.cert_arquivo:
            return None
        try:
            cert = cofre.abrir_certificado(e.cert_arquivo, e.cnpj)
        except Exception as erro:      # noqa: BLE001
            if not silencioso:
                mostrar_erro(self, erro, "Certificado")
            return None
        if cert.vencido and not silencioso:
            QMessageBox.warning(self, "Certificado", "O certificado está vencido. Importe um novo.")
            return None
        self._emissor = Emissor(self.banco, e, cert)
        return self._emissor

    def _nova(self):
        d = DialogoEmpresa(self.banco, None, self)
        if d.exec():
            self._carregar_empresas(d.e.id)

    def _editar(self):
        e = self._empresa_atual()
        if not e:
            return self._nova()
        d = DialogoEmpresa(self.banco, e, self)
        if d.exec():
            self._carregar_empresas(d.e.id)


def executar() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NFS-e Nacional")
    app.setStyle("Fusion")
    j = Janela()
    j.show()
    return app.exec()
