import datetime as dt
from decimal import Decimal

import pytest

from nfse_nacional.danfse import gerar_pdf, nome_municipio
from nfse_nacional.dps import (DPS, IBSCBS, Endereco, Pessoa, Prestador, Servico, Valores,
                               gerar_xml, para_bytes)

from .conftest import CNPJ
from .test_servico import nfse_de

pypdf = pytest.importorskip("pypdf")


def _texto(pdf: bytes) -> str:
    import io
    leitor = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(leitor.pages) == 1                      # NT 008: página única
    return leitor.pages[0].extract_text()


def _nfse(tp_amb="1", tomador=True, ibs=False) -> bytes:
    d = DPS(c_loc_emi="4205407", serie="1", n_dps=3, tp_amb=tp_amb,
            d_compet=dt.date(2026, 9, 1),
            prestador=Prestador(documento=CNPJ, op_simp_nac="3", reg_ap_trib_sn="1"),
            tomador=Pessoa(documento="11444777000161", nome="CLIENTE EXEMPLO",
                           endereco=Endereco(c_mun="3106200", cep="30110000",
                                             logradouro="RUA DOS EXEMPLOS", numero="6627",
                                             bairro="CENTRO")) if tomador else None,
            servico=Servico("010601", "Gestão de projeto ERP " * 30, c_nbs="115011000",
                            info_complementar="Contrato 12/2026"),
            valores=Valores(v_serv=Decimal("1500"), p_tot_trib_sn=Decimal("6")),
            ibscbs=IBSCBS("030101", "000", "000001") if ibs else None)
    return nfse_de(para_bytes(gerar_xml(d)), numero="17")


def test_danfse_campos_principais():
    t = _texto(gerar_pdf(_nfse()))
    for esperado in ("DANFSe v2.0", "Documento Auxiliar da NFS-e", "11.222.333/0001-81",
                     "11.444.777/0001-61", "Belo Horizonte / MG", "3106200 / 30.110-000",
                     "01.06.01", "1.1501.10.00", "R$ 1.500,00", "01/09/2026",
                     "Inf. Cont.: Contrato 12/2026", "12.741/2012"):
        assert esperado in t, esperado
    assert "SEM VALIDADE" not in t


def test_danfse_homologacao_e_sem_tomador():
    t = _texto(gerar_pdf(_nfse(tp_amb="2", tomador=False, ibs=True)))
    assert "NFS-e SEM VALIDADE JURÍDICA" in t
    assert "TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO" in t
    assert "O DESTINATÁRIO É O PRÓPRIO TOMADOR" in t
    assert "000 / 000001" in t


def test_danfse_marca_dagua():
    assert "CANCELADA" in _texto(gerar_pdf(_nfse(), "CANCELADA"))


def test_nome_municipio():
    assert nome_municipio("4205407") == "Florianópolis / SC"
    assert nome_municipio("3106200") == "Belo Horizonte / MG"
