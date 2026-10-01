"""Fumaça da interface em modo offscreen (sem rede, sem diálogos modais)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PySide6 = pytest.importorskip("PySide6")

import keyring  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from nfse_nacional import cofre  # noqa: E402
from nfse_nacional.banco import Banco, Empresa  # noqa: E402

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
    _, destino = cofre.importar_certificado(pfx, SENHA)
    banco = Banco(tmp_path / "ui.db")
    banco.salvar_empresa(Empresa(cnpj=CNPJ, razao="EMPRESA TESTE", c_mun="4115200",
                                 op_simp_nac="3", reg_ap_trib_sn="1", c_trib_nac="010701",
                                 descricao_padrao="Serviço padrão", cert_arquivo=str(destino)))
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


def test_dados_invalidos_nao_enviam(janela):
    a = janela.aba_emitir
    a.descricao.clear()
    a.v_serv.setText("10")
    with pytest.raises(ValueError):
        a._dados()
