"""Empresa de teste fictícia: cria, não fala com o sistema nacional e remove só ela."""
from decimal import Decimal

import keyring
import pytest

from nfse_nacional import cofre, demo
from nfse_nacional.banco import Banco, Empresa, Tomador
from nfse_nacional.danfse import gerar_pdf
from nfse_nacional.servico import DadosNota, Emissor

from .test_cli import CofreMemoria


@pytest.fixture
def banco(tmp_path):
    anterior = keyring.get_keyring()
    keyring.set_keyring(CofreMemoria())
    b = Banco(tmp_path / "demo.db")
    yield b
    b.fechar()
    keyring.set_keyring(anterior)


def test_cria_empresa_com_notas_e_nao_fala_com_o_sistema(banco):
    real = banco.salvar_empresa(Empresa(cnpj="11222333000181", razao="REAL"))
    banco.salvar_tomador(Tomador(documento="11444777000161", nome="CADASTRO QUE JÁ EXISTIA"), real.id)
    e = demo.criar_empresa_teste(banco)
    assert demo.eh_teste(e) and e.ambiente == "producao_restrita"
    assert demo.criar_empresa_teste(banco).id == e.id              # não duplica
    notas = banco.con.execute("SELECT * FROM notas WHERE empresa_id=?", (e.id,)).fetchall()
    assert [n["situacao"] for n in notas] == ["autorizada", "autorizada"]
    assert all(len(n["chave"]) == 50 for n in notas)
    assert gerar_pdf(notas[0]["nfse_xml"]).startswith(b"%PDF")
    assert banco.tomador("11444777000161").nome == "CADASTRO QUE JÁ EXISTIA"   # não sobrescreve

    em = Emissor(banco, e, cofre.certificado_ativo(banco, e))
    dados = DadosNota(descricao="x", v_serv=Decimal("10"), tomador=demo.TOMADORES[1])
    assert em.preparar(em.montar_dps(dados, 99)).startswith(b"<")     # validar/assinar funciona
    proximo = banco.proximo_numero(e.id, e.ambiente, e.serie)
    with pytest.raises(ValueError, match="Empresa de teste"):
        em.emitir(dados)
    with pytest.raises(ValueError, match="Empresa de teste"):
        em.sincronizar()
    assert banco.proximo_numero(e.id, e.ambiente, e.serie) == proximo  # não queimou número
    assert len(banco.con.execute("SELECT id FROM notas WHERE empresa_id=?", (e.id,)).fetchall()) == 2

    assert demo.remover_empresa_teste(banco)
    assert banco.empresa_por_cnpj(demo.CNPJ_TESTE) is None
    assert not banco.con.execute("SELECT 1 FROM notas WHERE empresa_id=?", (e.id,)).fetchall()
    assert banco.empresa(real.id) and banco.tomador("11444777000161")    # o resto fica
    assert banco.tomador("12345678909") is None                          # fictício só dela: sai
    assert not demo.remover_empresa_teste(banco)
