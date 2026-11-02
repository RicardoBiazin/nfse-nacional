"""Janela principal."""
from __future__ import annotations

import sys

from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import VERSAO, cofre, demo
from ..config import pasta_base
from ..banco import Banco
from ..servico import Emissor, tomadores_de_notas
from .aba_emitir import AbaEmitir
from .aba_notas import AbaNotas
from . import temas
from .comum import mostrar_erro
from .dialogo_empresa import DialogoEmpresa


class Janela(QMainWindow):
    def __init__(self, banco: Banco | None = None):
        super().__init__()
        self.banco = banco or Banco()
        self._emissor: Emissor | None = None
        self.setWindowTitle(f"NFS-e Nacional {VERSAO}")
        self.setWindowIcon(icone())
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
        self.aba_emitir.obter_empresa = self._empresa_atual   # busca de tomador por empresa
        self.aba_notas.duplicar.connect(self._duplicar)
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
        menu_tema = self.menuBar().addMenu("Tema")
        grupo = QActionGroup(self)
        atual = temas.tema_salvo()
        self.acoes_tema = {}
        for nome, (rotulo, _cores) in temas.TEMAS.items():
            a = QAction(rotulo, self, checkable=True, checked=nome == atual)
            a.triggered.connect(lambda _c=False, n=nome: temas.aplicar(n, salvar=True))
            grupo.addAction(a); menu_tema.addAction(a)
            self.acoes_tema[nome] = a
        menu_teste = self.menuBar().addMenu("Teste")
        menu_teste.addAction("Criar empresa de teste (fictícia)", self._criar_empresa_teste)
        menu_teste.addAction("Remover empresa de teste", self._remover_empresa_teste)
        self.menuBar().addAction(sobre)

        self._carregar_empresas()

    def _criar_empresa_teste(self):
        e = demo.criar_empresa_teste(self.banco)
        self._carregar_empresas(e.id)
        QMessageBox.information(
            self, "Empresa de teste",
            f"{e.razao} — CNPJ {e.cnpj}.\n\nTudo nela é inventado: certificado autoassinado, "
            "tomadores e 2 notas de exemplo. Ela não fala com o sistema nacional; use "
            "\"Validar e salvar XML\" para ver o XML assinado. Para apagar: menu Teste > "
            "Remover empresa de teste.")

    def _remover_empresa_teste(self):
        if not self.banco.empresa_por_cnpj(demo.CNPJ_TESTE):
            QMessageBox.information(self, "Empresa de teste", "Não há empresa de teste cadastrada.")
            return
        if QMessageBox.question(
                self, "Empresa de teste", "Apagar a empresa de teste e as notas fictícias dela? "
                "As outras empresas não são tocadas.") != QMessageBox.StandardButton.Yes:
            return
        demo.remover_empresa_teste(self.banco)
        self._emissor = None
        self._carregar_empresas()

    def _duplicar(self, dados):
        self.aba_emitir.carregar(dados)
        self.abas.setCurrentIndex(0)

    def _sobre(self):
        caixa = QMessageBox(self)
        caixa.setWindowTitle("Sobre")
        caixa.setIconPixmap(icone().pixmap(72, 72))
        caixa.setText(f"<b>NFS-e Nacional {VERSAO}</b><br><br>Emissão (Sefin Nacional) e consulta (ADN) "
                      "da NFS-e Padrão Nacional.<br>Leiaute DPS 1.01 · DANFSe conforme NT 008/2026.")
        caixa.exec()

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
            self.selo.setText("Cadastre uma empresa (ou menu Teste)")
            self.selo.setStyleSheet("")
        elif demo.eh_teste(e):
            self.selo.setText("  EMPRESA DE TESTE (fictícia)  ")
            self.selo.setStyleSheet("background:#6a4fb3; color:white; font-weight:bold; border-radius:4px")
        elif e.ambiente == "producao":
            self.selo.setText("  PRODUÇÃO  ")
            self.selo.setStyleSheet("background:#b3261e; color:white; font-weight:bold; border-radius:4px")
        else:
            self.selo.setText("  PRODUÇÃO RESTRITA (testes)  ")
            self.selo.setStyleSheet("background:#f2b705; color:black; font-weight:bold; border-radius:4px")
        if e:
            tomadores_de_notas(self.banco, e.id)      # tomadores das notas já sincronizadas
            self.aba_emitir._atualizar_completer()
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
        try:
            cert = cofre.certificado_ativo(self.banco, e)
        except Exception as erro:      # noqa: BLE001
            if not silencioso:
                mostrar_erro(self, erro, "Certificado")
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


def icone() -> QIcon:
    return QIcon(str(pasta_base() / "recursos" / "icone.png"))


def registrar_falhas(pasta=None):
    """O .exe não tem console: erro sem tratamento e queda do processo iam para lugar nenhum.
    Agora vão para falhas.log na pasta de dados (o usuário manda o arquivo junto com o relato)."""
    import datetime as dt
    import faulthandler
    import threading
    import traceback
    from ..config import pasta_dados
    caminho = (pasta or pasta_dados()) / "falhas.log"
    try:
        grande = caminho.exists() and caminho.stat().st_size > 512_000
        log = open(caminho, "w" if grande else "a", encoding="utf-8")
    except OSError:
        return None
    log.write(f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} aberto NFS-e Nacional {VERSAO}\n")
    log.flush()
    faulthandler.enable(log, all_threads=True)

    def gancho(tipo, valor, tb):
        log.write(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S} erro sem tratamento\n")
        traceback.print_exception(tipo, valor, tb, file=log)
        log.flush()
    sys.excepthook = gancho
    threading.excepthook = lambda a: gancho(a.exc_type, a.exc_value, a.exc_traceback)
    return caminho


def executar() -> int:
    registrar_falhas()
    if sys.platform == "win32":
        # Sem um AppUserModelID próprio a barra de tarefas agrupa sob o python.exe e mostra o ícone dele.
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Biazin.NFSeNacional")
        except (AttributeError, OSError):
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NFS-e Nacional")
    app.setStyle("Fusion")
    temas.aplicar(temas.tema_salvo(), app)
    app.setWindowIcon(icone())
    j = Janela()
    j.show()
    return app.exec()
