"""Fumaça da interface em modo offscreen (sem rede, sem diálogos modais)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")

import keyring  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from nfse_nacional import cofre  # noqa: E402
from nfse_nacional.banco import Banco, Empresa, Tomador  # noqa: E402

from .conftest import CNPJ, SENHA  # noqa: E402
from .test_cli import CofreMemoria  # noqa: E402
from .test_servico import SessaoFalsa, _emissao_ok  # noqa: E402


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def janela(app, tmp_path, pfx_bytes, monkeypatch):
    anterior = keyring.get_keyring()
    keyring.set_keyring(CofreMemoria())
    avisos = []
    for nome in ("information", "warning", "about"):
        monkeypatch.setattr(QMessageBox, nome, lambda *a, _n=nome, **k: avisos.append((_n, a[2] if len(a) > 2 else "")))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    # mostrar_erro() usa QMessageBox(...).exec(): registra em vez de abrir modal.
    monkeypatch.setattr(QMessageBox, "exec", lambda self: avisos.append(("erro", self.text())) or 0)
    pfx = tmp_path / "c.pfx"; pfx.write_bytes(pfx_bytes)
    banco = Banco(tmp_path / "ui.db")
    e = banco.salvar_empresa(Empresa(cnpj=CNPJ, razao="EMPRESA TESTE", c_mun="4115200",
                                     op_simp_nac="3", reg_ap_trib_sn="1", c_trib_nac="010701",
                                     descricao_padrao="Serviço padrão"))
    cofre.adicionar_a_empresa(banco, e, pfx, SENHA)
    from nfse_nacional.interface.janela import Janela
    j = Janela(banco)
    j.avisos = avisos
    yield j
    j.close()
    banco.fechar()
    keyring.set_keyring(anterior)


def test_janela_abre_com_empresa_e_padroes(janela):
    assert janela.empresas.count() == 1
    assert "RESTRITA" in janela.selo.text()
    assert janela.aba_emitir.descricao.toPlainText() == "Serviço padrão"


def test_emitir_pela_interface(janela, qtbot=None):
    from PySide6.QtCore import QThreadPool
    em = janela.emissor()
    s = SessaoFalsa(); s.rota("POST", r"/nfse$", _emissao_ok)
    em._sessao = s
    a = janela.aba_emitir
    a.t_doc.setText("123.456.789-09"); a.t_nome.setText("Fulano")
    a.v_serv.setText("1.234,56")
    a._emitir()
    QThreadPool.globalInstance().waitForDone(10000)
    QApplication.processEvents()
    assert any(n == "information" for n, _ in janela.avisos), janela.avisos
    janela.aba_notas.recarregar()
    assert janela.aba_notas.tabela.rowCount() == 1
    assert janela.aba_notas.tabela.item(0, 0).text() == "autorizada"
    assert "1.234,56" in janela.aba_notas.status.text()


def test_notas_mostra_producao_por_padrao_e_busca(janela):
    n = janela.aba_notas
    assert n.ambiente.currentData() == "producao"
    e = janela._empresa_atual()
    janela.banco.inserir_nota(empresa_id=e.id, ambiente="producao", origem="emitida",
                              situacao="autorizada", numero="17", d_compet=f"{__import__('datetime').date.today():%Y-%m-%d}",
                              tomador_nome="CLIENTE EXEMPLO", descricao="ERP", v_serv="1500.00")
    n.recarregar()
    assert n.tabela.rowCount() == 1
    n.busca.setText("inexistente"); n.recarregar()
    assert n.tabela.rowCount() == 0


def test_sincronizar_avisa_resultado(janela):
    from PySide6.QtCore import QThreadPool
    from .test_servico import resposta
    em = janela.emissor()
    s = SessaoFalsa()
    s.rota("GET", r"/contribuintes/DFe/", lambda u, k: resposta(404, {
        "StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
        "Erros": [{"Codigo": "E2220", "Descricao": "Nenhum documento localizado"}]}))
    import nfse_nacional.interface.aba_notas as mod
    original = mod.Emissor
    mod.Emissor = lambda b, e, c: original(b, e, c, sessao=s)
    try:
        janela.aba_notas._sincronizar()
        QThreadPool.globalInstance().waitForDone(10000)
        QApplication.processEvents()
    finally:
        mod.Emissor = original
    assert any("0 documento(s)" in t for _, t in janela.avisos), janela.avisos
    assert "adn.nfse.gov.br" in s.chamadas[0][1]          # consultou PRODUÇÃO


def _nota_do_portal(janela):
    """Grava uma NFS-e emitida 'pelo portal' (como viria da sincronização)."""
    import datetime as dt
    from decimal import Decimal
    from nfse_nacional.dps import DPS, Endereco, Pessoa, Prestador, Servico, Valores, gerar_xml, para_bytes
    from .test_servico import nfse_de
    e = janela._empresa_atual()
    d = DPS(c_loc_emi="4205407", serie="70000", n_dps=17, d_compet=dt.date(2026, 9, 1),
            prestador=Prestador(documento=CNPJ, op_simp_nac="3", reg_ap_trib_sn="1"),
            tomador=Pessoa(documento="11444777000161", nome="CLIENTE EXEMPLO SERVICOS",
                           endereco=Endereco(c_mun="3106200", cep="30110000", logradouro="RUA DOS EXEMPLOS",
                                             numero="6627", bairro="CENTRO")),
            servico=Servico("010601", "Gestão de projeto ERP", c_nbs="115011000"),
            valores=Valores(v_serv=Decimal("1500")))
    xml = nfse_de(para_bytes(gerar_xml(d)), numero="17")
    return janela.banco.inserir_nota(
        empresa_id=e.id, ambiente="producao", origem="emitida", situacao="autorizada",
        numero="17", d_compet=dt.date.today().isoformat(), tomador_doc="11444777000161",
        tomador_nome="CLIENTE EXEMPLO SERVICOS", v_serv="1500.00", nfse_xml=xml,
        chave="4205407" + "7" * 43)


def test_busca_tomador_e_repetir_ultima_nota(janela):
    from nfse_nacional.servico import tomadores_de_notas
    _nota_do_portal(janela)
    assert tomadores_de_notas(janela.banco, janela._empresa_atual().id) == 1
    a = janela.aba_emitir
    a._atualizar_completer()
    i = a.busca_tom.findData("11444777000161")
    assert i >= 0 and "CLIENTE" in a.busca_tom.itemText(i)
    a._escolher_tomador(i)
    assert a.t_nome.text().startswith("CLIENTE") and a.t_cmun.text() == "3106200"
    a._repetir_ultima()
    assert a.descricao.toPlainText() == "Gestão de projeto ERP"
    assert a.v_serv.text() == "1.500,00" and a.c_trib_nac.text() == "010601"
    assert a._dados().v_serv == 1500


def test_duplicar_nota_preenche_emissao(janela):
    id_ = _nota_do_portal(janela)
    n = janela.aba_notas
    n.recarregar()
    n.tabela.selectRow(0)
    assert n._linhas[0]["id"] == id_
    n._duplicar()
    a = janela.aba_emitir
    assert janela.abas.currentIndex() == 0
    assert a.t_doc.text() == "11444777000161" and a.c_nbs.text() == "115011000"


def test_dialogo_empresa_varios_certificados(janela, tmp_path):
    from nfse_nacional.interface.dialogo_empresa import DialogoEmpresa
    from .conftest import _pfx
    d = DialogoEmpresa(janela.banco, janela._empresa_atual(), janela)
    assert d.tab_cert.rowCount() == 1 and d.tab_cert.item(0, 0).text() == "★"
    novo = tmp_path / "renovado.pfx"
    novo.write_bytes(_pfx(CNPJ, SENHA, 800))
    assert d.adicionar_certificado(str(novo), SENHA)       # question() responde Sim: vira principal
    assert d.tab_cert.rowCount() == 2
    principal = [d.tab_cert.item(i, 3).text() for i in range(2) if d.tab_cert.item(i, 0).text()]
    assert len(principal) == 1 and "válido" in d.rot_cert.text()
    outro = tmp_path / "outro.pfx"
    outro.write_bytes(_pfx("99888777000166", SENHA))
    assert not d.adicionar_certificado(str(outro), SENHA)  # outra empresa: recusado
    assert d.tab_cert.rowCount() == 2


def test_dados_invalidos_nao_enviam(janela):
    a = janela.aba_emitir
    a.descricao.clear()
    a.v_serv.setText("10")
    with pytest.raises(ValueError):
        a._dados()


def test_campo_codigo_descreve_e_busca_por_descricao(app):
    from nfse_nacional.interface.comum import CampoCodigo
    c = CampoCodigo("servico", 6)
    c.setText("010601")
    assert c.desc.text() == "010601 - Assessoria e consultoria em informática."
    c.setText("010601 - Assessoria e consultoria em informática.")
    assert c.text() == "010601"                                   # grava só o código
    c.setText("999999")
    assert "não encontrado" in c.desc.text()
    c.clear(); c.definir_padrao("010601")
    assert c.desc.text().startswith("padrão da empresa: 010601")
    comp = c.edit.completer()
    comp.setCompletionPrefix("consultoria em inform")
    assert 1 <= comp.completionCount() < 10
    m = CampoCodigo("municipio", 7)
    m.setText("3106200")
    assert m.desc.text() == "3106200 - Belo Horizonte / MG"
    n = CampoCodigo("nbs", 9)
    n.setText("115011000")
    assert "consultoria em tecnologia" in n.desc.text()


def test_nova_empresa_com_cnpj_existente_nao_apaga_cadastro(janela, tmp_path):
    """Regressão: até a 0.6.0, importar o certificado em 'Nova empresa' e salvar
    sobrescrevia a empresa existente com o formulário vazio."""
    from nfse_nacional.interface.dialogo_empresa import DialogoEmpresa
    from .conftest import _pfx
    b = janela.banco
    antes = b.empresa_por_cnpj(CNPJ)
    pfx = tmp_path / "mesmo.pfx"; pfx.write_bytes(_pfx(CNPJ, SENHA, 500))
    d = DialogoEmpresa(b, None, janela)
    assert d.adicionar_certificado(str(pfx), SENHA)
    assert d.e.id == antes.id and d.c_mun.text() == "4115200" and d.c_trib_nac.text() == "010701"
    d._salvar()
    depois = b.empresa_por_cnpj(CNPJ)
    assert (depois.c_mun, depois.reg_ap_trib_sn, depois.c_trib_nac, depois.descricao_padrao) == \
        ("4115200", "1", "010701", "Serviço padrão")
    assert len(b.certificados(antes.id)) == 2 and len(b.empresas()) == 1
    # Salvar direto (CNPJ digitado) também não sobrescreve
    d2 = DialogoEmpresa(b, None, janela)
    d2.cnpj.setText(CNPJ)
    d2._salvar()
    assert b.empresa_por_cnpj(CNPJ).c_trib_nac == "010701"


def test_aliquota_travada_no_simples_sem_retencao(janela):
    a = janela.aba_emitir                      # empresa do fixture: ME/EPP, apuração pelo SN
    assert not a.p_aliq.isEnabled()
    a.ret.setCurrentIndex(a.ret.findData("2"))  # retido pelo tomador: passa a ser obrigatória
    assert a.p_aliq.isEnabled() and "obrigatória" in a.p_aliq.placeholderText()
    a.ret.setCurrentIndex(a.ret.findData("1"))
    a.p_aliq.setText("6")
    a._regra_aliquota()
    assert a.p_aliq.text() == "" and not a.p_aliq.isEnabled()


def test_percentual_simples_por_nota_vira_padrao(janela):
    from PySide6.QtCore import QThreadPool
    from nfse_nacional.config import NS_NFSE
    from lxml import etree
    a = janela.aba_emitir
    assert a.p_sn.isVisibleTo(janela) and a.p_sn.text() in ("0,00", "")
    em = janela.emissor()
    enviado = {}

    def ok(u, k):
        from nfse_nacional import compactacao
        enviado["dps"] = compactacao.de_gzip_b64(k["json"]["dpsXmlGZipB64"])
        return _emissao_ok(u, k)
    s = SessaoFalsa(); s.rota("POST", r"/nfse$", ok); em._sessao = s
    a.t_doc.setText("12345678909"); a.t_nome.setText("Fulano"); a.v_serv.setText("100")
    a.p_sn.setText("8,47")
    a._emitir()
    QThreadPool.globalInstance().waitForDone(10000)
    QApplication.processEvents()
    dps = etree.fromstring(enviado["dps"])
    assert dps.findtext(".//{%s}pTotTribSN" % NS_NFSE) == "8.47"
    assert janela.banco.empresa_por_cnpj(CNPJ).p_tot_sn == "8.47"
    assert a.p_sn.text() == "8,47"                      # próxima nota já vem com o novo padrão


def test_busca_de_tomador_so_da_empresa_selecionada(janela):
    from nfse_nacional.banco import Empresa
    b = janela.banco
    e1 = janela._empresa_atual()
    e2 = b.salvar_empresa(Empresa(cnpj="99888777000166", razao="OUTRA EMPRESA", c_mun="4205407"))
    b.salvar_tomador(Tomador(documento="11111111000191", nome="SÓ DA PRIMEIRA"), e1.id)
    b.salvar_tomador(Tomador(documento="22222222000191", nome="SÓ DA OUTRA"), e2.id)
    janela._carregar_empresas(e1.id)
    a = janela.aba_emitir
    a._atualizar_completer()
    itens = [a.busca_tom.itemText(i) for i in range(a.busca_tom.count())]
    assert any("PRIMEIRA" in x for x in itens) and not any("OUTRA" in x for x in itens)
    janela._carregar_empresas(e2.id)
    a._atualizar_completer()
    itens = [a.busca_tom.itemText(i) for i in range(a.busca_tom.count())]
    assert any("SÓ DA OUTRA" in x for x in itens) and not any("PRIMEIRA" in x for x in itens)


def _esperar():
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(10000)
    QApplication.processEvents()


def test_cep_e_cnpj_preenchem_o_tomador(janela, monkeypatch):
    from nfse_nacional import consultas

    from .test_consultas_email import BRASILAPI, VIACEP, Rede, Resp
    rede = Rede({"brasilapi.com.br/api/cnpj": Resp(200, BRASILAPI), "viacep": Resp(200, VIACEP)})
    monkeypatch.setattr(consultas, "_get", lambda url, sessao=None: rede.get(url))
    a = janela.aba_emitir
    a.t_cep.setText("88020-010"); a.t_cep.editingFinished.emit(); _esperar()
    assert (a.t_lgr.text(), a.t_bairro.text(), a.t_cmun.text()) == ("Rua Emílio Blum", "Centro", "4205407")
    n = len(rede.chamadas)
    a.t_cep.editingFinished.emit(); _esperar()
    assert len(rede.chamadas) == n                     # mesmo CEP não consulta de novo
    a.limpar()
    a.t_doc.setText("11444777000161"); a.t_doc.editingFinished.emit(); _esperar()   # CNPJ novo: automático
    assert a.t_nome.text() == "CLIENTE EXEMPLO SERVICOS LTDA"
    assert (a.t_nro.text(), a.t_fone.text(), a.t_lgr.text()) == ("121", "4830001234", "Rua Emílio Blum")


def test_email_configurado_na_empresa_e_enviado_pela_aba_notas(janela, monkeypatch, tmp_path):
    import smtplib

    from nfse_nacional import email_nfse
    from nfse_nacional.interface.dialogo_empresa import DialogoEmpresa

    from .test_consultas_email import SMTPFalso
    from .test_danfse import _nfse
    SMTPFalso.enviados, SMTPFalso.instancias = [], []
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    b = janela.banco
    e = b.empresas()[0]
    d = DialogoEmpresa(b, e)
    d.provedor.setCurrentIndex(1)                       # Gmail
    assert d.smtp_host.text() == "smtp.gmail.com" and d.smtp_porta.value() == 587
    d.smtp_rem.setText("nfe@exemplo.com.br"); d.smtp_usuario.setText("nfe@exemplo.com.br")
    d.smtp_senha.setText("segredo"); d.smtp_auto.setChecked(True)
    d._salvar()
    cfg = b.config_email(e.id)
    assert cfg.configurado and cfg.enviar_auto and cfg.corpo == ""     # corpo padrão não é gravado
    assert email_nfse.senha_smtp(e.id) == "segredo"
    janela.aba_emitir.preencher_padroes(janela.emissor())
    assert janela.aba_emitir.enviar_email.isEnabled() and janela.aba_emitir.enviar_email.isChecked()

    b.salvar_tomador(Tomador(documento="11444777000161", nome="CLIENTE EXEMPLO",
                             email="cliente@exemplo.com.br"), e.id)
    b.inserir_nota(empresa_id=e.id, ambiente="producao", origem="emitida", situacao="autorizada",
                   chave="4" * 50, numero="17", d_compet="2026-09-01", tomador_doc="11444777000161",
                   tomador_nome="CLIENTE EXEMPLO", v_serv="1500.00", nfse_xml=_nfse())
    notas = janela.aba_notas
    notas.inicio.setDate(notas.inicio.date().addYears(-1))
    notas.recarregar()
    notas.tabela.selectAll()
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    notas._enviar_email()
    _esperar()
    assert SMTPFalso.enviados[-1][1] == ["cliente@exemplo.com.br"]
    from nfse_nacional.interface.aba_notas import COLUNAS
    col = [c[0] for c in COLUNAS].index("E-mail")
    assert notas.tabela.item(0, col).text().startswith("enviado")
