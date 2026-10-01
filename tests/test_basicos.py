import os
import tempfile
from decimal import Decimal

import pytest

from nfse_nacional import compactacao, regras
from nfse_nacional.certificado import Certificado, SenhaCertificadoIncorreta
from nfse_nacional.dps import dec2, montar_id_dps

from .conftest import CNPJ, SENHA


def test_gzip_b64_ida_e_volta():
    xml = "<a>ação</a>".encode()
    assert compactacao.de_gzip_b64(compactacao.para_gzip_b64(xml)) == xml


def test_de_gzip_b64_aceita_base64_puro():
    import base64
    assert compactacao.de_gzip_b64(base64.b64encode(b"<x/>").decode()) == b"<x/>"


def test_id_dps_cnpj_e_cpf():
    i = montar_id_dps("4115200", "11.222.333/0001-81", "1", 42)
    assert i == "DPS" + "4115200" + "2" + "11222333000181" + "00001" + "0" * 13 + "42"
    assert len(i) == 45
    j = montar_id_dps("4115200", "123.456.789-09", 900, 1)
    assert j[10] == "1" and j[11:25] == "00012345678909"


def test_dec2():
    assert dec2(0) == "0.00"
    assert dec2("10.005") == "10.01"
    assert dec2(Decimal("1500")) == "1500.00"


def test_certificado_cnpj_e_validade(certificado):
    assert certificado.cnpj == CNPJ
    assert certificado.documento == ("CNPJ", CNPJ)
    assert not certificado.vencido
    assert certificado.dias_para_vencer() >= 360


def test_certificado_senha_errada(pfx_bytes):
    with pytest.raises(SenhaCertificadoIncorreta):
        Certificado.de_bytes(pfx_bytes, "errada")


def test_contexto_ssl_nao_deixa_arquivo(certificado):
    antes = set(os.listdir(tempfile.gettempdir()))
    ctx = certificado.contexto_ssl()
    depois = set(os.listdir(tempfile.gettempdir()))
    assert ctx is not None
    assert not [n for n in depois - antes if n.startswith("nfse_")]


@pytest.mark.parametrize("op,reg_ap,reg_esp,trib,ret,conv,esperado", [
    ("2", "", "0", "1", "1", True, regras.PROIBIDA),        # MEI
    ("1", "", "0", "2", "1", False, regras.PROIBIDA),       # imunidade
    ("1", "", "6", "1", "1", False, regras.PROIBIDA),       # regime especial
    ("1", "", "0", "1", "1", True, regras.PROIBIDA),        # convênio ativo
    ("1", "", "0", "1", "1", False, regras.OBRIGATORIA),    # convênio inativo
    ("1", "", "0", "1", "1", None, regras.OPCIONAL),
    ("3", "1", "0", "1", "2", True, regras.OBRIGATORIA),    # SN com retenção
    ("3", "1", "0", "1", "1", True, regras.PROIBIDA),       # SN sem retenção
    ("3", "2", "0", "1", "1", False, regras.OBRIGATORIA),   # ISS fora do SN, convênio inativo
])
def test_aliquota_exigida(op, reg_ap, reg_esp, trib, ret, conv, esperado):
    assert regras.aliquota_exigida(op, reg_ap, reg_esp, trib, ret, conv) == esperado
