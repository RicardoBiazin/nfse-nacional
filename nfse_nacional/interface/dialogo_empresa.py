"""Cadastro de empresa emissora + importação do certificado A1."""
from __future__ import annotations

import datetime as dt

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import cofre
from ..banco import Banco, Empresa
from ..certificado import Certificado, SenhaCertificadoIncorreta
from ..dps import so_digitos
from .comum import CampoCodigo, em_segundo_plano, mostrar_erro

OP_SIMP_NAC = [("1", "Não optante"), ("2", "MEI"), ("3", "Simples Nacional ME/EPP")]
REG_AP_SN = [("", "—"), ("1", "Tributos federais e ISS pelo SN"),
             ("2", "Federais pelo SN, ISS por fora"), ("3", "Federais e ISS por fora do SN")]
REG_ESP = [("0", "Nenhum"), ("1", "Ato cooperado"), ("2", "Estimativa"),
           ("3", "Microempresa municipal"), ("4", "Notário ou registrador"),
           ("5", "Profissional autônomo"), ("6", "Sociedade de profissionais"), ("9", "Outros")]
CONVENIO = [(None, "Não sei (consultar)"), (1, "Ativo"), (0, "Inativo")]
AMBIENTES = [("producao_restrita", "Produção Restrita (testes)"), ("producao", "PRODUÇÃO (vale imposto)")]


def combo(opcoes, atual) -> QComboBox:
    c = QComboBox()
    for valor, rotulo in opcoes:
        c.addItem(rotulo, valor)
    i = next((n for n, (v, _) in enumerate(opcoes) if v == atual), 0)
    c.setCurrentIndex(i)
    return c


class DialogoEmpresa(QDialog):
    def __init__(self, banco: Banco, empresa: Empresa | None = None, pai=None):
        super().__init__(pai)
        self.banco = banco
        self.e = empresa or Empresa(cnpj="")
        self.setWindowTitle("Empresa emissora")
        self.resize(640, 560)
        abas = QTabWidget()

        # ---- identificação
        w = QWidget(); f = QFormLayout(w)
        self.cnpj = QLineEdit(self.e.cnpj); self.cnpj.setReadOnly(bool(self.e.id))
        self.cnpj.setPlaceholderText("vem do certificado")
        self.razao = QLineEdit(self.e.razao)
        self.im = QLineEdit(self.e.im)
        self.c_mun = CampoCodigo("municipio", 7); self.c_mun.setText(self.e.c_mun); self.c_mun.setPlaceholderText("IBGE ou nome da cidade")
        self.fone = QLineEdit(self.e.fone)
        self.email = QLineEdit(self.e.email)
        self.serie = QLineEdit(self.e.serie); self.serie.setPlaceholderText("1 a 49999 (70000+ é a série do portal)")
        self.proximo = QSpinBox(); self.proximo.setRange(1, 999_999_999)
        self.ambiente = combo(AMBIENTES, self.e.ambiente)
        if self.e.id:
            self.proximo.setValue(banco.proximo_numero(self.e.id, self.e.ambiente, self.e.serie))
        self.rot_cert = QLabel()
        bt_cert = QPushButton("Certificados…")
        bt_cert.clicked.connect(lambda: abas.setCurrentIndex(abas.count() - 1))
        linha_cert = QHBoxLayout(); linha_cert.addWidget(self.rot_cert, 1); linha_cert.addWidget(bt_cert)
        f.addRow("Certificado em uso", linha_cert)
        f.addRow("CNPJ", self.cnpj)
        f.addRow("Razão social", self.razao)
        f.addRow("Inscrição municipal", self.im)
        f.addRow("Município (IBGE)", self.c_mun)
        f.addRow("Telefone", self.fone)
        f.addRow("E-mail", self.email)
        f.addRow("Série da DPS", self.serie)
        f.addRow("Próximo nº da DPS", self.proximo)
        f.addRow("Ambiente", self.ambiente)
        abas.addTab(w, "Identificação")

        # ---- tributação
        w = QWidget(); f = QFormLayout(w)
        self.op_simp_nac = combo(OP_SIMP_NAC, self.e.op_simp_nac)
        self.reg_ap = combo(REG_AP_SN, self.e.reg_ap_trib_sn)
        self.reg_esp = combo(REG_ESP, self.e.reg_esp_trib)
        self.convenio = combo(CONVENIO, self.e.convenio_ativo)
        bt_conv = QPushButton("Consultar")
        bt_conv.clicked.connect(self._consultar_convenio)
        lc = QHBoxLayout(); lc.addWidget(self.convenio, 1); lc.addWidget(bt_conv)
        self.p_aliq = QLineEdit(self.e.p_aliq); self.p_aliq.setPlaceholderText("ex.: 2,00 (usada só quando a regra exige)")
        self.p_fed = QLineEdit(self.e.p_tot_fed)
        self.p_est = QLineEdit(self.e.p_tot_est)
        self.p_mun = QLineEdit(self.e.p_tot_mun)
        self.p_sn = QLineEdit(self.e.p_tot_sn)
        f.addRow("Simples Nacional", self.op_simp_nac)
        f.addRow("Regime de apuração (ME/EPP)", self.reg_ap)
        f.addRow("Regime especial", self.reg_esp)
        f.addRow("Convênio do município", lc)
        f.addRow("Alíquota ISS padrão (%)", self.p_aliq)
        g = QGroupBox("Tributos aproximados (Lei 12.741)"); fg = QFormLayout(g)
        fg.addRow("Federal % (não optante)", self.p_fed)
        fg.addRow("Estadual % (não optante)", self.p_est)
        fg.addRow("Municipal % (não optante)", self.p_mun)
        fg.addRow("Simples Nacional % (ME/EPP)", self.p_sn)
        f.addRow(g)
        abas.addTab(w, "Tributação")

        # ---- serviço padrão
        w = QWidget(); f = QFormLayout(w)
        self.c_trib_nac = CampoCodigo("servico", 6); self.c_trib_nac.setText(self.e.c_trib_nac); self.c_trib_nac.setPlaceholderText("código ou parte da descrição")
        self.c_trib_mun = QLineEdit(self.e.c_trib_mun)
        self.c_nbs = CampoCodigo("nbs", 9); self.c_nbs.setText(self.e.c_nbs); self.c_nbs.setPlaceholderText("código ou parte da descrição")
        self.descr = QLineEdit(self.e.descricao_padrao)
        f.addRow("Cód. tributação nacional", self.c_trib_nac)
        f.addRow("Cód. tributação municipal", self.c_trib_mun)
        f.addRow("NBS", self.c_nbs)
        f.addRow("Descrição padrão", self.descr)
        g = QGroupBox("IBS/CBS (Reforma Tributária) — deixe vazio para não enviar o grupo")
        fg = QFormLayout(g)
        self.ibs_ind = QLineEdit(self.e.ibs_c_ind_op); self.ibs_ind.setPlaceholderText("cIndOp, 6 dígitos (Anexo C)")
        self.ibs_cst = QLineEdit(self.e.ibs_cst); self.ibs_cst.setPlaceholderText("CST, 3 dígitos")
        self.ibs_class = QLineEdit(self.e.ibs_c_class_trib); self.ibs_class.setPlaceholderText("cClassTrib, 6 dígitos")
        fg.addRow("Indicador da operação", self.ibs_ind)
        fg.addRow("CST", self.ibs_cst)
        fg.addRow("Classificação tributária", self.ibs_class)
        f.addRow(g)
        abas.addTab(w, "Serviço padrão")

        # ---- certificados (vários por empresa)
        w = QWidget(); v = QVBoxLayout(w)
        aviso = QLabel("Pode cadastrar mais de um certificado A1: o renovado antes do antigo "
                       "vencer, ou o de outra filial com o mesmo CNPJ raiz. O <b>principal</b> é "
                       "usado na emissão; se ele vencer, o app usa o válido com maior validade.")
        aviso.setWordWrap(True)
        v.addWidget(aviso)
        self.tab_cert = QTableWidget(0, 5)
        self.tab_cert.setHorizontalHeaderLabels(["Principal", "Titular", "CNPJ/CPF", "Válido até", "Situação"])
        self.tab_cert.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tab_cert.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tab_cert.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tab_cert.verticalHeader().setVisible(False)
        self.tab_cert.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.tab_cert, 1)
        linha = QHBoxLayout()
        for rot, fn in (("Adicionar certificado (.pfx)…", self._importar_cert),
                        ("Tornar principal", self._tornar_principal),
                        ("Remover", self._remover_cert)):
            b = QPushButton(rot); b.clicked.connect(fn); linha.addWidget(b)
        linha.addStretch(1)
        v.addLayout(linha)
        abas.addTab(w, "Certificados")
        self._linhas_cert = []
        if self.e.id:
            cofre.migrar_certificado_antigo(banco, self.e)
        self._recarregar_certs()

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(abas); lay.addWidget(botoes)

    # ------------------------------------------------------------ certificados
    def _recarregar_certs(self):
        self._linhas_cert = self.banco.certificados(self.e.id) if self.e.id else []
        self.tab_cert.setRowCount(len(self._linhas_cert))
        agora = dt.datetime.now(dt.timezone.utc)
        em_uso = ""
        for i, r in enumerate(self._linhas_cert):
            try:
                val = dt.datetime.fromisoformat(r["validade"])
                dias = (val - agora).days
                situacao = "VENCIDO" if dias < 0 else (f"vence em {dias} dias" if dias < 30 else "válido")
                cor = "#b3261e" if dias < 0 else ("#b26a00" if dias < 30 else "#1b7f3b")
                val_txt = val.astimezone().strftime("%d/%m/%Y")
            except ValueError:
                situacao, cor, val_txt = "?", "#000", r["validade"]
            for j, txt in enumerate(("★" if r["principal"] else "", r["titular"], r["documento"],
                                     val_txt, situacao)):
                it = QTableWidgetItem(txt)
                if j == 4:
                    it.setForeground(QColor(cor))
                self.tab_cert.setItem(i, j, it)
            if r["principal"]:
                em_uso = f"{r['titular']} (até {val_txt}) — {situacao}"
        self.tab_cert.resizeColumnsToContents()
        self.tab_cert.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rot_cert.setText(em_uso or "nenhum certificado importado")
        if self.e.id:
            atual = self.banco.empresa(self.e.id)
            if atual:
                self.e.cert_arquivo = atual.cert_arquivo

    def _cert_selecionado(self):
        linhas = {i.row() for i in self.tab_cert.selectedIndexes()}
        if len(linhas) != 1:
            QMessageBox.information(self, "Certificados", "Selecione um certificado na lista.")
            return None
        return self._linhas_cert[linhas.pop()]

    def _importar_cert(self):
        arq, _ = QFileDialog.getOpenFileName(self, "Certificado A1", "", "Certificado (*.pfx *.p12)")
        if not arq:
            return
        senha, ok = QInputDialog.getText(self, "Senha do certificado", "Senha:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        self.adicionar_certificado(arq, senha)

    def adicionar_certificado(self, arq: str, senha: str) -> bool:
        try:
            previa = Certificado.de_arquivo(arq, senha)
            if not self.e.id:
                # Empresa nova: o CNPJ vem do primeiro certificado; grava para ter id.
                self.e = self._coletar()
                self.e.cnpj = self.e.cnpj or previa.documento[1]
                self.e.razao = self.e.razao or previa.titular.split(":")[0]
                self.e = self.banco.salvar_empresa(self.e)
                self.cnpj.setText(self.e.cnpj)
                self.cnpj.setReadOnly(True)
                self.razao.setText(self.e.razao)
            principal = False
            if self._linhas_cert:
                principal = QMessageBox.question(
                    self, "Certificado", "Usar este certificado como principal?"
                ) == QMessageBox.StandardButton.Yes
            cofre.adicionar_a_empresa(self.banco, self.e, arq, senha, principal=principal)
        except SenhaCertificadoIncorreta:
            QMessageBox.warning(self, "Certificado", "Senha incorreta.")
            return False
        except Exception as erro:      # noqa: BLE001
            mostrar_erro(self, erro, "Certificado")
            return False
        self._recarregar_certs()
        return True

    def _tornar_principal(self):
        r = self._cert_selecionado()
        if r:
            self.banco.definir_certificado_principal(self.e.id, r["id"])
            self._recarregar_certs()

    def _remover_cert(self):
        r = self._cert_selecionado()
        if not r:
            return
        if QMessageBox.question(self, "Remover certificado",
                                f"Remover o certificado de {r['titular']} (até {r['validade'][:10]})? "
                                "A cópia do .pfx e a senha guardadas pelo app serão apagadas."
                                ) != QMessageBox.StandardButton.Yes:
            return
        cofre.remover_da_empresa(self.banco, self.e, r["id"])
        self._recarregar_certs()

    def _consultar_convenio(self):
        if not (self._linhas_cert and so_digitos(self.c_mun.text())):
            QMessageBox.information(self, "Convênio", "Importe o certificado e informe o município antes.")
            return
        from ..servico import Emissor
        e = self._coletar()

        def consultar():
            cert = cofre.certificado_ativo(self.banco, e)
            return Emissor(self.banco, e, cert).parametros_convenio()

        def pronto(dados):
            import json
            texto = json.dumps(dados, ensure_ascii=False, indent=2)[:3000]
            ativo = "ativo" in texto.lower() and "inativo" not in texto.lower()
            QMessageBox.information(self, "Parâmetros do convênio", texto)
            self.convenio.setCurrentIndex(1 if ativo else self.convenio.currentIndex())
        em_segundo_plano(consultar, pronto, lambda erro: mostrar_erro(self, erro, "Convênio"))

    def _coletar(self) -> Empresa:
        e = self.e
        e.cnpj = so_digitos(self.cnpj.text())
        e.razao = self.razao.text().strip()
        e.im = self.im.text().strip()
        e.c_mun = so_digitos(self.c_mun.text())
        e.fone = self.fone.text().strip()
        e.email = self.email.text().strip()
        e.serie = so_digitos(self.serie.text()) or "1"
        e.ambiente = self.ambiente.currentData()
        e.op_simp_nac = self.op_simp_nac.currentData()
        e.reg_ap_trib_sn = self.reg_ap.currentData() if e.op_simp_nac == "3" else ""
        e.reg_esp_trib = self.reg_esp.currentData()
        e.convenio_ativo = self.convenio.currentData()
        e.p_aliq = self.p_aliq.text().strip().replace(",", ".")
        e.p_tot_fed = self.p_fed.text().strip().replace(",", ".") or "0"
        e.p_tot_est = self.p_est.text().strip().replace(",", ".") or "0"
        e.p_tot_mun = self.p_mun.text().strip().replace(",", ".") or "0"
        e.p_tot_sn = self.p_sn.text().strip().replace(",", ".") or "0"
        e.c_trib_nac = so_digitos(self.c_trib_nac.text())
        e.c_trib_mun = so_digitos(self.c_trib_mun.text())
        e.c_nbs = so_digitos(self.c_nbs.text())
        e.descricao_padrao = self.descr.text().strip()
        e.ibs_c_ind_op = so_digitos(self.ibs_ind.text())
        e.ibs_cst = so_digitos(self.ibs_cst.text())
        e.ibs_c_class_trib = so_digitos(self.ibs_class.text())
        return e

    def _salvar(self):
        e = self._coletar()
        if len(e.cnpj) not in (11, 14):
            QMessageBox.warning(self, "Empresa", "Importe o certificado para identificar o CNPJ.")
            return
        if e.ambiente == "producao":
            r = QMessageBox.question(
                self, "Produção",
                "No ambiente de PRODUÇÃO as notas têm valor fiscal e geram imposto. Confirmar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        salva = self.banco.salvar_empresa(e)
        atual = self.banco.proximo_numero(salva.id, salva.ambiente, salva.serie)
        if self.proximo.value() < atual and self.e.id and QMessageBox.question(
                self, "Numeração", f"Voltar a numeração para {self.proximo.value()}? "
                f"Números já usados serão rejeitados pela Sefin.") != QMessageBox.StandardButton.Yes:
            self.proximo.setValue(atual)
        if self.proximo.value() != atual:
            self.banco.definir_proximo_numero(salva.id, salva.ambiente, salva.serie, self.proximo.value())
        self.e = salva
        self.accept()
