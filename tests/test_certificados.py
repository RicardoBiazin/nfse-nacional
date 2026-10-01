"""Vários certificados por empresa: principal, troca automática, CNPJ raiz e migração."""
import keyring
import pytest

from nfse_nacional import cofre
from nfse_nacional.banco import Banco, Empresa
from nfse_nacional.certificado import Certificado

from .conftest import CNPJ, SENHA, _pfx
from .test_cli import CofreMemoria


@pytest.fixture(autouse=True)
def cofre_falso():
    anterior = keyring.get_keyring()
    keyring.set_keyring(CofreMemoria())
    yield
    keyring.set_keyring(anterior)


@pytest.fixture
def ctx(tmp_path):
    b = Banco(tmp_path / "c.db")
    e = b.salvar_empresa(Empresa(cnpj=CNPJ, razao="EMPRESA"))

    def arquivo(nome, cnpj=CNPJ, dias=365):
        p = tmp_path / nome
        p.write_bytes(_pfx(cnpj, SENHA, dias))
        return p
    yield b, e, arquivo
    b.fechar()


def test_varios_certificados_e_principal(ctx):
    b, e, arq = ctx
    c1, id1 = cofre.adicionar_a_empresa(b, e, arq("a.pfx", dias=100), SENHA)
    c2, id2 = cofre.adicionar_a_empresa(b, e, arq("b.pfx", dias=400), SENHA)
    linhas = b.certificados(e.id)
    assert len(linhas) == 2
    assert [r["id"] for r in linhas if r["principal"]] == [id1]       # o primeiro vira principal
    assert cofre.certificado_ativo(b, e).cert.serial_number == c1.cert.serial_number
    b.definir_certificado_principal(e.id, id2)
    assert cofre.certificado_ativo(b, e).cert.serial_number == c2.cert.serial_number
    assert b.empresa(e.id).cert_arquivo == next(r["arquivo"] for r in b.certificados(e.id) if r["principal"])


def test_principal_vencido_usa_o_valido(ctx):
    b, e, arq = ctx
    _, id_venc = cofre.adicionar_a_empresa(b, e, arq("v.pfx", dias=-1), SENHA)
    c_ok, _ = cofre.adicionar_a_empresa(b, e, arq("ok.pfx", dias=300), SENHA)
    b.definir_certificado_principal(e.id, id_venc)
    assert cofre.certificado_ativo(b, e).cert.serial_number == c_ok.cert.serial_number


def test_todos_vencidos_e_sem_certificado(ctx):
    b, e, arq = ctx
    with pytest.raises(ValueError, match="não tem certificado"):
        cofre.certificado_ativo(b, e)
    cofre.adicionar_a_empresa(b, e, arq("v.pfx", dias=-1), SENHA)
    with pytest.raises(ValueError, match="vencidos"):
        cofre.certificado_ativo(b, e)


def test_cnpj_raiz_aceito_e_outro_cnpj_recusado(ctx):
    b, e, arq = ctx
    filial = CNPJ[:8] + "000262"
    cofre.adicionar_a_empresa(b, e, arq("filial.pfx", cnpj=filial), SENHA)
    with pytest.raises(ValueError, match="não pertence"):
        cofre.adicionar_a_empresa(b, e, arq("outra.pfx", cnpj="99888777000166"), SENHA)
    assert len(b.certificados(e.id)) == 1


def test_remover_principal_promove_outro(ctx):
    b, e, arq = ctx
    _, id1 = cofre.adicionar_a_empresa(b, e, arq("a.pfx"), SENHA)
    _, id2 = cofre.adicionar_a_empresa(b, e, arq("b.pfx"), SENHA)
    arquivo1 = b.certificados(e.id)[0]["arquivo"]
    cofre.remover_da_empresa(b, e, id1)
    restantes = b.certificados(e.id)
    assert [(r["id"], r["principal"]) for r in restantes] == [(id2, 1)]
    import os
    assert not os.path.exists(arquivo1)
    cofre.remover_da_empresa(b, e, id2)
    assert b.empresa(e.id).cert_arquivo == ""


def test_migracao_do_formato_antigo(ctx, tmp_path):
    """Até a 0.3.0: um .pfx por empresa e a senha no keyring sob o próprio CNPJ."""
    b, e, arq = ctx
    antigo = arq("antigo.pfx")
    keyring.set_password(cofre.SERVICO_KEYRING, CNPJ, SENHA)
    e.cert_arquivo = str(antigo)
    e = b.salvar_empresa(e)
    cert = cofre.certificado_ativo(b, e)
    assert cert.cnpj == CNPJ
    linhas = b.certificados(e.id)
    assert len(linhas) == 1 and linhas[0]["principal"] == 1
    assert keyring.get_password(cofre.SERVICO_KEYRING, linhas[0]["chave_cofre"]) == SENHA
