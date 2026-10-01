import datetime as dt
from decimal import Decimal

import pytest
from lxml import etree

from nfse_nacional import assinatura, eventos, validacao
from nfse_nacional.config import NS_DS, NS_NFSE
from nfse_nacional.dps import (DPS, IBSCBS, Endereco, Pessoa, Prestador, Servico,
                               TributosFederais, Valores, gerar_xml, para_bytes)

from .conftest import CNPJ

N = {"n": NS_NFSE, "ds": NS_DS}


def _dps(op="1", **kw) -> DPS:
    valores = kw.pop("valores", None) or Valores(v_serv=Decimal("1500.00"))
    return DPS(
        c_loc_emi="4115200", serie="1", n_dps=7,
        d_compet=dt.date(2026, 9, 30),
        prestador=Prestador(documento=CNPJ, op_simp_nac=op,
                            reg_ap_trib_sn="1" if op == "3" else "", im="12345"),
        tomador=Pessoa(documento="12345678909", nome="  Fulano   de Tal ",
                       endereco=Endereco(c_mun="4115200", cep="87000-000", logradouro="Rua A",
                                         numero="10", bairro="Centro"),
                       email="fulano@exemplo.com"),
        servico=Servico(c_trib_nac="010701", descricao="Suporte técnico em informática",
                        c_nbs="115013000"),
        valores=valores, **kw)


@pytest.mark.parametrize("op", ["1", "2", "3"])
def test_dps_valida_no_xsd_por_regime(op):
    raiz = gerar_xml(_dps(op))
    validacao.validar_dps(raiz)
    tot = raiz.find(".//n:totTrib", N)
    filho = etree.QName(tot[0]).localname
    assert filho == {"1": "pTotTrib", "2": "indTotTrib", "3": "pTotTribSN"}[op]


def test_dps_campos_e_limpeza_de_texto():
    raiz = gerar_xml(_dps())
    inf = raiz.find("n:infDPS", N)
    assert inf.get("Id").startswith("DPS4115200211222333000181")
    assert raiz.get("versao") == "1.01"
    assert inf.findtext("n:toma/n:xNome", namespaces=N) == "Fulano de Tal"
    assert inf.findtext("n:toma/n:end/n:endNac/n:CEP", namespaces=N) == "87000000"
    assert inf.findtext("n:valores/n:vServPrest/n:vServ", namespaces=N) == "1500.00"
    # tpEmit = 1: nome do prestador não vai (E0121)
    assert inf.find("n:prest/n:xNome", N) is None
    assert inf.findtext("n:dhEmi", namespaces=N).endswith("-03:00")


def test_dps_completa_com_ibscbs_retencoes_e_aliquota():
    v = Valores(v_serv=Decimal("2000"), v_desc_incond=Decimal("100"), tp_ret_issqn="2",
                p_aliq=Decimal("2"),
                trib_fed=TributosFederais(cst_pis_cofins="01", v_bc_pis_cofins=Decimal("1900"),
                                          p_aliq_pis=Decimal("0.65"), p_aliq_cofins=Decimal("3"),
                                          v_pis=Decimal("12.35"), v_cofins=Decimal("57"),
                                          tp_ret_pis_cofins="1", v_ret_irrf=Decimal("28.5")))
    d = _dps("1", valores=v,
             ibscbs=IBSCBS(c_ind_op="030101", cst="000", c_class_trib="000001"))
    raiz = gerar_xml(d)
    validacao.validar_dps(raiz)
    assert raiz.find(".//n:IBSCBS/n:valores/n:trib/n:gIBSCBS/n:cClassTrib", N).text == "000001"


def test_schema_rejeita_dps_quebrada():
    raiz = gerar_xml(_dps())
    raiz.find(".//n:cTribNac", N).text = "12"
    with pytest.raises(validacao.ErroSchema) as e:
        validacao.validar_dps(raiz)
    assert "cTribNac" in str(e.value)


@pytest.mark.parametrize("alg", ["sha1", "sha256"])
def test_assinatura_dps_valida_e_detecta_alteracao(certificado, alg):
    raiz = gerar_xml(_dps())
    assinatura.assinar(raiz, "infDPS", certificado, alg)
    validacao.validar_dps(raiz)                      # Signature no lugar certo do XSD
    sig = raiz.find("ds:Signature", N)
    assert sig is not None and sig.getprevious().tag == f"{{{NS_NFSE}}}infDPS"
    assert sig.find("ds:SignedInfo/ds:Reference", N).get("URI") == "#" + raiz[0].get("Id")

    # Ida e volta pelos bytes enviados, como o servidor verá.
    recebido = etree.fromstring(para_bytes(raiz))
    cert = assinatura.verificar(recebido)
    assert cert.serial_number == certificado.cert.serial_number

    recebido.find(".//n:vServ", N).text = "1.00"
    with pytest.raises(assinatura.AssinaturaInvalida):
        assinatura.verificar(recebido)


@pytest.mark.parametrize("alg", ["sha1", "sha256"])
@pytest.mark.parametrize("tag,montar", [
    ("infDPS", lambda: gerar_xml(_dps())),
    ("infPedReg", lambda: eventos.pedido_cancelamento(
        "4115200" + "3" * 43, CNPJ, "2", "Serviço não foi prestado ao tomador")),
])
def test_assinatura_confere_com_xmlsec(certificado, alg, tag, montar):
    """Verificação independente (libxmlsec1, C14N própria) do nosso assinador.

    Pega o bug de C14N do lxml em subelemento: com ele o xmlsec rejeitava.
    """
    xmlsec = pytest.importorskip("xmlsec")
    from cryptography.hazmat.primitives import serialization

    raiz = montar()
    assinatura.assinar(raiz, tag, certificado, alg)
    doc = etree.fromstring(para_bytes(raiz))
    xmlsec.tree.add_ids(doc, ["Id"])
    ctx = xmlsec.SignatureContext()
    ctx.key = xmlsec.Key.from_memory(
        certificado.cert.public_bytes(serialization.Encoding.PEM),
        xmlsec.constants.KeyDataFormatCertPem)
    no = xmlsec.tree.find_node(doc, xmlsec.constants.NodeSignature)
    ctx.verify(no)
    folha = next(e for e in doc[0].iter() if len(e) == 0 and e.text)
    folha.text += "0"
    with pytest.raises(xmlsec.Error):
        ctx.verify(no)


def test_pedido_cancelamento(certificado):
    chave = "4115200" + "2" * 43
    raiz = eventos.pedido_cancelamento(chave, CNPJ, "1", "Erro na emissão do valor da nota")
    validacao.validar_ped_reg_evento(raiz)
    assinatura.assinar(raiz, "infPedReg", certificado)
    validacao.validar_ped_reg_evento(raiz)
    inf = raiz.find("n:infPedReg", N)
    assert inf.get("Id") == f"PRE{chave}101101"
    assert inf.findtext("n:e101101/n:xDesc", namespaces=N) == "Cancelamento de NFS-e"
    assinatura.verificar(etree.fromstring(para_bytes(raiz)))


def test_cancelamento_exige_justificativa_longa():
    with pytest.raises(ValueError):
        eventos.pedido_cancelamento("1" * 50, CNPJ, "1", "curta")
