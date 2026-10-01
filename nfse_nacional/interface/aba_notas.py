"""Aba de notas: lista, sincronização com o ADN, cancelamento, DANFSe, exportação."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from .. import exportar
from ..banco import Banco
from ..eventos import MOTIVOS_CANCELAMENTO
from .comum import em_segundo_plano, moeda, mostrar_erro

COLUNAS = [("Situação", "situacao"), ("Origem", "origem"), ("Nº NFS-e", "numero"),
           ("nDPS", "n_dps"), ("Competência", "d_compet"), ("Tomador / Prestador", "_parte"),
           ("Descrição", "descricao"), ("Valor", "v_serv"), ("ISS", "v_issqn"),
           ("Chave", "chave"), ("Mensagem", "mensagem")]
CORES = {"autorizada": "#1b7f3b", "cancelada": "#9a9a9a", "rejeitada": "#b3261e",
         "indefinida": "#b26a00", "pendente": "#b26a00"}


class DialogoCancelar(QDialog):
    def __init__(self, pai=None):
        super().__init__(pai)
        self.setWindowTitle("Cancelar NFS-e")
        self.motivo = QComboBox()
        for k, v in MOTIVOS_CANCELAMENTO.items():
            self.motivo.addItem(f"{k} - {v}", k)
        self.just = QPlainTextEdit(); self.just.setPlaceholderText("Justificativa (15 a 255 caracteres)")
        f = QFormLayout(self)
        f.addRow("Motivo", self.motivo)
        f.addRow("Justificativa", self.just)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._ok); b.rejected.connect(self.reject)
        f.addRow(b)

    def _ok(self):
        n = len(self.just.toPlainText().strip())
        if not 15 <= n <= 255:
            QMessageBox.warning(self, "Cancelar", f"A justificativa tem {n} caracteres; precisa de 15 a 255.")
            return
        self.accept()


class AbaNotas(QWidget):
    def __init__(self, banco: Banco, obter_emissor, obter_empresa, pai=None):
        super().__init__(pai)
        self.banco = banco
        self.obter_emissor = obter_emissor      # (silencioso=False) -> Emissor | None
        self.obter_empresa = obter_empresa      # () -> Empresa | None (listar não exige certificado)

        hoje = QDate.currentDate()
        self.inicio = QDateEdit(QDate(hoje.year(), hoje.month(), 1)); self.inicio.setCalendarPopup(True)
        self.fim = QDateEdit(hoje.addMonths(1)); self.fim.setCalendarPopup(True)
        for d in (self.inicio, self.fim):
            d.setDisplayFormat("dd/MM/yyyy")
            d.dateChanged.connect(self.recarregar)
        self.origem = QComboBox()
        for r, v in (("Todas", ""), ("Emitidas", "emitida"), ("Recebidas", "recebida")):
            self.origem.addItem(r, v)
        self.situacao = QComboBox()
        for r, v in (("Todas", ""), ("Autorizadas", "autorizada"), ("Canceladas", "cancelada"),
                     ("Rejeitadas", "rejeitada"), ("Indefinidas", "indefinida")):
            self.situacao.addItem(r, v)
        self.busca = QLineEdit(); self.busca.setPlaceholderText("buscar nome, descrição, número, chave")
        for w in (self.origem, self.situacao):
            w.currentIndexChanged.connect(self.recarregar)
        self.busca.returnPressed.connect(self.recarregar)

        filtros = QHBoxLayout()
        for rot, w in (("De", self.inicio), ("até", self.fim), ("Origem", self.origem),
                       ("Situação", self.situacao)):
            filtros.addWidget(QLabel(rot)); filtros.addWidget(w)
        filtros.addWidget(self.busca, 1)

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels([c[0] for c in COLUNAS])
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.tabela.doubleClicked.connect(lambda _i: self._ver_xml())

        self.status = QLabel("")
        acoes = QHBoxLayout()
        botoes = [("Sincronizar ADN", self._sincronizar), ("Reconsultar", self._reconsultar),
                  ("DANFSe (PDF)", self._danfse), ("Cancelar NFS-e", self._cancelar),
                  ("Ver XML", self._ver_xml), ("Importar XML", self._importar_xml),
                  ("Exportar XLSX", self._exportar_xlsx), ("Exportar XMLs", self._exportar_xmls)]
        self.botoes = {}
        for rot, fn in botoes:
            b = QPushButton(rot); b.clicked.connect(fn); acoes.addWidget(b); self.botoes[rot] = b
        acoes.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(filtros); lay.addWidget(self.tabela, 1); lay.addLayout(acoes); lay.addWidget(self.status)
        self._linhas = []

    # ------------------------------------------------------------ lista
    def _datas(self):
        return (self.inicio.date().toString("yyyy-MM-dd"), self.fim.date().toString("yyyy-MM-dd"))

    def recarregar(self):
        emp = self.obter_empresa()
        self.tabela.setRowCount(0)
        self._linhas = []
        if not emp:
            return
        ini, fim = self._datas()
        self._linhas = self.banco.notas(emp.id, emp.ambiente, ini, fim,
                                        self.origem.currentData(), self.situacao.currentData(),
                                        self.busca.text().strip())
        self.tabela.setRowCount(len(self._linhas))
        total = 0
        for i, n in enumerate(self._linhas):
            parte = n["tomador_nome"] if n["origem"] == "emitida" else n["prestador_nome"]
            for j, (_, campo) in enumerate(COLUNAS):
                v = parte if campo == "_parte" else n[campo]
                if campo in ("v_serv", "v_issqn"):
                    v = moeda(v)
                if campo == "d_compet" and v:
                    v = "/".join(reversed(v.split("-")))
                it = QTableWidgetItem("" if v is None else str(v))
                if campo in ("v_serv", "v_issqn", "numero", "n_dps"):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if campo == "situacao":
                    it.setForeground(QColor(CORES.get(n["situacao"], "#000")))
                self.tabela.setItem(i, j, it)
            if n["situacao"] == "autorizada" and n["origem"] == "emitida" and n["v_serv"]:
                total += float(n["v_serv"])
        self.tabela.resizeColumnsToContents()
        self.tabela.setColumnWidth(6, 260)
        self.status.setText(f"{len(self._linhas)} nota(s). Emitidas autorizadas no período: R$ {moeda(total)}")

    def _selecionadas(self):
        linhas = sorted({i.row() for i in self.tabela.selectedIndexes()})
        return [self._linhas[i] for i in linhas]

    def _uma(self):
        sel = self._selecionadas()
        if len(sel) != 1:
            QMessageBox.information(self, "Notas", "Selecione uma nota.")
            return None
        return sel[0]

    # ------------------------------------------------------------ ações
    def _sincronizar(self):
        em = self.obter_emissor()
        if not em:
            return
        b = self.botoes["Sincronizar ADN"]
        b.setEnabled(False)

        def fim(n):
            b.setEnabled(True)
            self.status.setText(f"Sincronização concluída: {n} documento(s) novo(s).")
            self.recarregar()

        def falha(e):
            b.setEnabled(True)
            self.recarregar()
            mostrar_erro(self, e, "Sincronização")
        em_segundo_plano(lambda cb: em.sincronizar(cb), fim, falha, progresso=self.status.setText)

    def _reconsultar(self):
        n = self._uma()
        em = self.obter_emissor()
        if not (n and em):
            return
        em_segundo_plano(lambda: em.reconsultar(n["id"]),
                         lambda r: (self.recarregar(), QMessageBox.information(
                             self, "Reconsulta", f"Situação: {r.situacao}\n{r.mensagem or ''}")),
                         lambda e: mostrar_erro(self, e, "Reconsulta"))

    def _cancelar(self):
        n = self._uma()
        em = self.obter_emissor()
        if not (n and em):
            return
        if n["origem"] != "emitida" or n["situacao"] != "autorizada":
            QMessageBox.information(self, "Cancelar", "Só notas emitidas e autorizadas podem ser canceladas.")
            return
        d = DialogoCancelar(self)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        motivo, just = d.motivo.currentData(), d.just.toPlainText().strip()
        em_segundo_plano(lambda: em.cancelar(n["id"], motivo, just),
                         lambda _r: (self.recarregar(),
                                     QMessageBox.information(self, "Cancelar", "NFS-e cancelada.")),
                         lambda e: mostrar_erro(self, e, "Cancelamento"))

    def _danfse(self):
        n = self._uma()
        em = self.obter_emissor()
        if not (n and em):
            return
        arq, _ = QFileDialog.getSaveFileName(self, "Salvar DANFSe", f"DANFSe_{n['numero'] or n['chave']}.pdf",
                                             "PDF (*.pdf)")
        if not arq:
            return

        def salvar(pdf):
            Path(arq).write_bytes(pdf)
            if hasattr(os, "startfile"):
                os.startfile(arq)          # noqa: S606 - abre no visualizador padrão
        em_segundo_plano(lambda: em.danfse(n["id"]), salvar, lambda e: mostrar_erro(self, e, "DANFSe"))

    def _ver_xml(self):
        n = self._uma()
        if not n:
            return
        nota = self.banco.nota(n["id"])
        xml = nota["nfse_xml"] or nota["dps_xml"]
        if not xml:
            return
        from lxml import etree
        try:
            texto = etree.tostring(etree.fromstring(xml), pretty_print=True, encoding="unicode")
        except Exception:      # noqa: BLE001
            texto = xml.decode("utf-8", "replace")
        dlg = QDialog(self); dlg.setWindowTitle(f"XML — {n['chave'] or n['id_dps']}"); dlg.resize(900, 650)
        ed = QPlainTextEdit(texto); ed.setReadOnly(True)
        QVBoxLayout(dlg).addWidget(ed)
        dlg.exec()

    def _importar_xml(self):
        em = self.obter_emissor()
        if not em:
            return
        arqs, _ = QFileDialog.getOpenFileNames(self, "Importar XML de NFS-e/evento", "", "XML (*.xml)")
        erros = []
        for a in arqs:
            try:
                em.importar_xml(Path(a).read_bytes())
            except Exception as e:      # noqa: BLE001
                erros.append(f"{Path(a).name}: {e}")
        self.recarregar()
        if erros:
            QMessageBox.warning(self, "Importar", "\n".join(erros))

    def _exportar_xlsx(self):
        if not self._linhas:
            return
        ini, fim = self._datas()
        arq, _ = QFileDialog.getSaveFileName(self, "Exportar planilha", f"NFSe_{ini}_{fim}.xlsx", "Excel (*.xlsx)")
        if arq:
            exportar.exportar_xlsx(self._linhas, arq)
            self.status.setText(f"Planilha salva em {arq}")

    def _exportar_xmls(self):
        sel = self._selecionadas() or self._linhas
        if not sel:
            return
        pasta = QFileDialog.getExistingDirectory(self, "Pasta para os XMLs")
        if pasta:
            n = exportar.exportar_xmls(self.banco, [x["id"] for x in sel], pasta)
            self.status.setText(f"{n} XML(s) salvos em {pasta}")
