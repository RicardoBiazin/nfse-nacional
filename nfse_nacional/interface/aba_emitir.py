"""Aba de emissão de NFS-e."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDateEdit,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..banco import Banco, Tomador
from ..dps import so_digitos
from ..servico import DadosNota, Emissor
from .comum import em_segundo_plano, mostrar_erro, para_decimal

RETENCAO = [("1", "Não retido"), ("2", "Retido pelo tomador"), ("3", "Retido pelo intermediário")]
TRIB_ISSQN = [("1", "Operação tributável"), ("2", "Imunidade"), ("3", "Exportação de serviço"),
              ("4", "Não incidência")]


def _combo(opcoes):
    c = QComboBox()
    for v, r in opcoes:
        c.addItem(r, v)
    return c


class AbaEmitir(QWidget):
    emitida = Signal()

    def __init__(self, banco: Banco, obter_emissor, pai=None):
        super().__init__(pai)
        self.banco = banco
        self.obter_emissor = obter_emissor          # () -> Emissor | None

        # ---- tomador
        g_tom = QGroupBox("Tomador")
        grid = QGridLayout(g_tom)
        self.t_doc = QLineEdit(); self.t_doc.setPlaceholderText("CPF ou CNPJ (vazio = sem tomador)")
        self.t_doc.editingFinished.connect(self._carregar_tomador)
        self.t_nome = QLineEdit()
        self.t_im = QLineEdit()
        self.t_email = QLineEdit()
        self.t_fone = QLineEdit()
        self.t_cmun = QLineEdit(); self.t_cmun.setPlaceholderText("IBGE")
        self.t_cep = QLineEdit()
        self.t_lgr = QLineEdit()
        self.t_nro = QLineEdit()
        self.t_cpl = QLineEdit()
        self.t_bairro = QLineEdit()
        campos = [("CPF/CNPJ", self.t_doc), ("Nome / razão social", self.t_nome),
                  ("Inscr. municipal", self.t_im), ("E-mail", self.t_email),
                  ("Telefone", self.t_fone), ("Município (IBGE)", self.t_cmun),
                  ("CEP", self.t_cep), ("Logradouro", self.t_lgr), ("Número", self.t_nro),
                  ("Complemento", self.t_cpl), ("Bairro", self.t_bairro)]
        for i, (rot, w) in enumerate(campos):
            grid.addWidget(QLabel(rot), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        self._atualizar_completer()

        # ---- serviço
        g_serv = QGroupBox("Serviço")
        f = QFormLayout(g_serv)
        self.descricao = QPlainTextEdit(); self.descricao.setFixedHeight(80)
        self.c_trib_nac = QLineEdit(); self.c_trib_nac.setPlaceholderText("padrão da empresa")
        self.c_trib_mun = QLineEdit(); self.c_trib_mun.setPlaceholderText("padrão da empresa")
        self.c_nbs = QLineEdit(); self.c_nbs.setPlaceholderText("padrão da empresa")
        self.c_loc = QLineEdit(); self.c_loc.setPlaceholderText("IBGE do local da prestação (padrão: município da empresa)")
        self.compet = QDateEdit(QDate.currentDate()); self.compet.setCalendarPopup(True)
        self.compet.setDisplayFormat("dd/MM/yyyy")
        self.info = QLineEdit()
        f.addRow("Descrição", self.descricao)
        f.addRow("Competência", self.compet)
        f.addRow("Cód. tributação nacional", self.c_trib_nac)
        f.addRow("Cód. tributação municipal", self.c_trib_mun)
        f.addRow("NBS", self.c_nbs)
        f.addRow("Local da prestação", self.c_loc)
        f.addRow("Informações complementares", self.info)

        # ---- valores
        g_val = QGroupBox("Valores e ISSQN")
        f = QFormLayout(g_val)
        self.v_serv = QLineEdit(); self.v_serv.setPlaceholderText("0,00")
        self.v_desc = QLineEdit(); self.v_desc.setPlaceholderText("desconto incondicionado")
        self.trib = _combo(TRIB_ISSQN)
        self.ret = _combo(RETENCAO)
        self.p_aliq = QLineEdit(); self.p_aliq.setPlaceholderText("vazio = automático pela regra")
        self.ibs = QCheckBox("Enviar grupo IBS/CBS configurado na empresa"); self.ibs.setChecked(True)
        f.addRow("Valor do serviço (R$)", self.v_serv)
        f.addRow("Desconto incondicionado", self.v_desc)
        f.addRow("Tributação do ISSQN", self.trib)
        f.addRow("Retenção do ISSQN", self.ret)
        f.addRow("Alíquota ISS (%)", self.p_aliq)
        f.addRow("", self.ibs)

        bt_validar = QPushButton("Validar e salvar XML (não envia)")
        bt_validar.clicked.connect(self._simular)
        self.bt_emitir = QPushButton("Emitir NFS-e")
        self.bt_emitir.setDefault(True)
        self.bt_emitir.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.bt_emitir.clicked.connect(self._emitir)
        bt_limpar = QPushButton("Limpar")
        bt_limpar.clicked.connect(self.limpar)
        botoes = QHBoxLayout()
        botoes.addWidget(bt_limpar); botoes.addStretch(1)
        botoes.addWidget(bt_validar); botoes.addWidget(self.bt_emitir)

        conteudo = QWidget()
        lay = QVBoxLayout(conteudo)
        lay.addWidget(g_tom); lay.addWidget(g_serv); lay.addWidget(g_val); lay.addStretch(1)
        rolagem = QScrollArea(); rolagem.setWidgetResizable(True); rolagem.setWidget(conteudo)
        principal = QVBoxLayout(self)
        principal.addWidget(rolagem); principal.addLayout(botoes)

    # ------------------------------------------------------------ tomador
    def _atualizar_completer(self):
        docs = [t.documento for t in self.banco.tomadores()]
        comp = QCompleter(docs, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.activated.connect(lambda _t: self._carregar_tomador())
        self.t_doc.setCompleter(comp)

    def _carregar_tomador(self):
        t = self.banco.tomador(so_digitos(self.t_doc.text()))
        if not t:
            return
        for w, v in ((self.t_nome, t.nome), (self.t_im, t.im), (self.t_email, t.email),
                     (self.t_fone, t.fone), (self.t_cmun, t.c_mun), (self.t_cep, t.cep),
                     (self.t_lgr, t.logradouro), (self.t_nro, t.numero),
                     (self.t_cpl, t.complemento), (self.t_bairro, t.bairro)):
            w.setText(v)

    def preencher_padroes(self, emissor: Emissor | None):
        if emissor and not self.descricao.toPlainText().strip():
            self.descricao.setPlainText(emissor.empresa.descricao_padrao)

    def limpar(self):
        for w in (self.t_doc, self.t_nome, self.t_im, self.t_email, self.t_fone, self.t_cmun,
                  self.t_cep, self.t_lgr, self.t_nro, self.t_cpl, self.t_bairro, self.c_trib_nac,
                  self.c_trib_mun, self.c_nbs, self.c_loc, self.info, self.v_serv, self.v_desc,
                  self.p_aliq):
            w.clear()
        self.descricao.clear()
        self.trib.setCurrentIndex(0); self.ret.setCurrentIndex(0)
        self.compet.setDate(QDate.currentDate())
        self.preencher_padroes(self.obter_emissor())

    # ------------------------------------------------------------ dados
    def _dados(self) -> DadosNota:
        tomador = None
        doc = so_digitos(self.t_doc.text())
        if doc:
            if len(doc) not in (11, 14):
                raise ValueError("CPF/CNPJ do tomador inválido.")
            if not self.t_nome.text().strip():
                raise ValueError("Informe o nome do tomador.")
            end = [self.t_cmun, self.t_cep, self.t_lgr, self.t_bairro]
            if any(w.text().strip() for w in end + [self.t_nro, self.t_cpl]) and \
                    not all(w.text().strip() for w in end):
                raise ValueError("Endereço do tomador incompleto: município (IBGE), CEP, "
                                 "logradouro e bairro são obrigatórios (ou deixe todos vazios).")
            tomador = Tomador(
                documento=doc, nome=self.t_nome.text().strip(), im=self.t_im.text().strip(),
                email=self.t_email.text().strip(), fone=self.t_fone.text().strip(),
                c_mun=so_digitos(self.t_cmun.text()), cep=so_digitos(self.t_cep.text()),
                logradouro=self.t_lgr.text().strip(), numero=self.t_nro.text().strip(),
                complemento=self.t_cpl.text().strip(), bairro=self.t_bairro.text().strip())
        v = para_decimal(self.v_serv.text())
        if v is None:
            raise ValueError("Informe o valor do serviço.")
        descricao = self.descricao.toPlainText().strip()
        if not descricao:
            raise ValueError("Informe a descrição do serviço.")
        q = self.compet.date()
        p_aliq = para_decimal(self.p_aliq.text())
        return DadosNota(
            descricao=descricao, v_serv=v, tomador=tomador,
            d_compet=dt.date(q.year(), q.month(), q.day()),
            c_trib_nac=so_digitos(self.c_trib_nac.text()),
            c_trib_mun=so_digitos(self.c_trib_mun.text()),
            c_nbs=so_digitos(self.c_nbs.text()), c_loc_prestacao=so_digitos(self.c_loc.text()),
            p_aliq=p_aliq, usar_aliquota_padrao=p_aliq is None,
            tp_ret_issqn=self.ret.currentData(), trib_issqn=self.trib.currentData(),
            v_desc_incond=para_decimal(self.v_desc.text()),
            info_complementar=self.info.text().strip(), incluir_ibscbs=self.ibs.isChecked())

    def _simular(self):
        em = self.obter_emissor()
        if not em:
            return
        try:
            d = self._dados()
            n = self.banco.proximo_numero(em.empresa.id, em.empresa.ambiente, em.empresa.serie)
            xml = em.preparar(em.montar_dps(d, n))
        except Exception as erro:      # noqa: BLE001
            mostrar_erro(self, erro, "Validação")
            return
        arq, _ = QFileDialog.getSaveFileName(self, "Salvar DPS assinada", f"DPS_{n}.xml", "XML (*.xml)")
        if arq:
            with open(arq, "wb") as f:
                f.write(xml)
        QMessageBox.information(self, "Validação", "DPS válida no schema oficial e assinada.\n"
                                "Nada foi enviado.")

    def _emitir(self):
        em = self.obter_emissor()
        if not em:
            return
        try:
            d = self._dados()
        except Exception as erro:      # noqa: BLE001
            mostrar_erro(self, erro, "Emissão")
            return
        producao = em.empresa.ambiente == "producao"
        texto = (f"Emitir NFS-e de R$ {self.v_serv.text()} para "
                 f"{d.tomador.nome if d.tomador else 'tomador não identificado'}?")
        if producao:
            texto += "\n\nAMBIENTE DE PRODUÇÃO: a nota terá valor fiscal."
        if QMessageBox.question(self, "Emitir", texto) != QMessageBox.StandardButton.Yes:
            return
        self.bt_emitir.setEnabled(False)
        self.bt_emitir.setText("Enviando…")

        def fim(r):
            self.bt_emitir.setEnabled(True); self.bt_emitir.setText("Emitir NFS-e")
            self._atualizar_completer()
            self.emitida.emit()
            if r.situacao == "autorizada":
                QMessageBox.information(self, "NFS-e autorizada",
                                        f"NFS-e nº {r.numero}\nChave: {r.chave}"
                                        + (f"\n\nAvisos: {r.mensagem}" if r.mensagem else ""))
                self.limpar()
            elif r.situacao == "rejeitada":
                QMessageBox.warning(self, "Rejeitada", r.mensagem)
            else:
                QMessageBox.warning(self, "Situação indefinida",
                                    "Não houve confirmação do sistema nacional. A nota ficou "
                                    "'indefinida': use 'Reconsultar' na aba Notas antes de "
                                    "emitir de novo.\n\n" + r.mensagem)

        def falha(erro):
            self.bt_emitir.setEnabled(True); self.bt_emitir.setText("Emitir NFS-e")
            mostrar_erro(self, erro, "Emissão")
        em_segundo_plano(lambda: em.emitir(d), fim, falha)
