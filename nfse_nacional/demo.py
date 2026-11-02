"""Empresa de teste fictícia: conhecer as telas sem certificado real e sem risco.

Tudo é inventado: CNPJ 99.888.777/0001-00 (dígitos válidos; diferente do usado nos testes), tomadores
fictícios e um certificado autoassinado gerado na hora (não é ICP-Brasil). O Emissor recusa
falar com o sistema nacional por ela; "Validar e salvar XML" funciona (valida e assina).
"""
from __future__ import annotations

import datetime as dt
import secrets
import tempfile
from decimal import Decimal
from pathlib import Path

from lxml import etree

from . import cofre
from .banco import Banco, Empresa, Tomador
from .config import NS_NFSE

CNPJ_TESTE = "99888777000100"
RAZAO_TESTE = "EMPRESA DE TESTE LTDA (FICTÍCIA)"
MENSAGEM_TESTE = ("Empresa de teste (fictícia): ela não fala com o sistema nacional. Use "
                  "\"Validar e salvar XML\" para ver o XML assinado; para emitir de verdade, use "
                  "uma empresa com o certificado A1 dela.")

TOMADORES = [
    Tomador(documento="11444777000161", nome="CLIENTE EXEMPLO LTDA (FICTÍCIO)", c_mun="4205407",
            cep="88000000", logradouro="RUA DOS EXEMPLOS", numero="100", bairro="CENTRO",
            email="cliente@exemplo.com"),
    Tomador(documento="12345678909", nome="FULANO DE TAL (FICTÍCIO)", c_mun="4205407",
            cep="88000000", logradouro="AVENIDA DE TESTE", numero="200", bairro="CENTRO"),
]


def eh_teste(empresa) -> bool:
    return empresa is not None and empresa.cnpj == CNPJ_TESTE


def _pfx(senha: str) -> bytes:
    """Certificado autoassinado com o CNPJ no OtherName ICP-Brasil (2.16.76.1.3.3)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{RAZAO_TESTE}:{CNPJ_TESTE}")])
    valor = b"\x04" + bytes([len(CNPJ_TESTE)]) + CNPJ_TESTE.encode()
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=5 * 365))
            .add_extension(x509.SubjectAlternativeName([
                x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), valor)]), critical=False)
            .sign(chave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(
        b"teste", chave, cert, None, serialization.BestAvailableEncryption(senha.encode()))


def _nfse_ficticia(dps_xml: bytes, chave: str, numero: str, dh: str) -> bytes:
    """Embrulha a DPS assinada numa NFS-e de mentira, para a aba Notas e o DANFSe."""
    n = lambda nome: f"{{{NS_NFSE}}}{nome}"        # noqa: E731
    nfse = etree.Element(n("NFSe"), nsmap={None: NS_NFSE}, versao="1.01")
    inf = etree.SubElement(nfse, n("infNFSe"), Id=f"NFS{chave}")
    for nome, valor in (("xLocEmi", "Florianópolis"), ("xLocPrestacao", "Florianópolis"),
                        ("nNFSe", numero), ("cLocIncid", "4205407"), ("xLocIncid", "Florianópolis"),
                        ("verAplic", "TESTE"), ("ambGer", "2"), ("tpEmis", "1"), ("procEmi", "1"),
                        ("cStat", "100"), ("dhProc", dh), ("nDFSe", "0")):
        etree.SubElement(inf, n(nome)).text = valor
    emit = etree.SubElement(inf, n("emit"))
    etree.SubElement(emit, n("CNPJ")).text = CNPJ_TESTE
    etree.SubElement(emit, n("xNome")).text = RAZAO_TESTE
    dps = etree.fromstring(dps_xml)
    v_serv = dps.findtext(f".//{n('vServ')}") or "0"
    val = etree.SubElement(inf, n("valores"))
    etree.SubElement(val, n("vLiq")).text = v_serv
    inf.append(dps)
    return etree.tostring(nfse, xml_declaration=True, encoding="utf-8")


def criar_empresa_teste(banco: Banco) -> Empresa:
    """Cria (ou devolve, se já existir) a empresa fictícia com certificado, tomadores e 2 notas."""
    from .servico import DadosNota, Emissor
    existente = banco.empresa_por_cnpj(CNPJ_TESTE)
    if existente:
        return existente
    e = banco.salvar_empresa(Empresa(
        cnpj=CNPJ_TESTE, razao=RAZAO_TESTE, c_mun="4205407", op_simp_nac="3", reg_ap_trib_sn="1",
        fone="4800000000", email="teste@exemplo.com", serie="1", ambiente="producao_restrita",
        p_tot_sn="6.00", c_trib_nac="010601", c_nbs="115011000",
        descricao_padrao="Consultoria em tecnologia da informação (nota de teste, fictícia)"))
    senha = secrets.token_urlsafe(16)
    with tempfile.TemporaryDirectory() as pasta:
        arq = Path(pasta) / "teste.pfx"
        arq.write_bytes(_pfx(senha))
        cofre.adicionar_a_empresa(banco, e, arq, senha, principal=True)
    for t in TOMADORES:
        if banco.tomador(t.documento):      # nunca sobrescreve um cadastro que já existia
            banco.ligar_tomador(e.id, t.documento)
        else:
            banco.salvar_tomador(t, e.id)

    em = Emissor(banco, e, cofre.certificado_ativo(banco, e))
    hoje = dt.date.today()
    for numero, (tom, valor, desc) in enumerate((
            (TOMADORES[0], "2500.00", "Consultoria em sistemas (nota de exemplo, fictícia)"),
            (TOMADORES[1], "800.00", "Suporte técnico (nota de exemplo, fictícia)")), start=1):
        n_dps = banco.reservar_numero(e.id, e.ambiente, e.serie)
        dps = em.montar_dps(DadosNota(descricao=desc, v_serv=Decimal(valor), tomador=tom,
                                      d_compet=hoje), n_dps)
        xml_dps = em.preparar(dps)
        # cMun + ambGer + tpInsc + CNPJ + nNFSe + AAMM + código + DV = 50 dígitos (inventada)
        chave = f"420540722{CNPJ_TESTE}{numero:013d}{hoje:%y%m}{numero:09d}0"
        dh = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        banco.inserir_nota(
            empresa_id=e.id, ambiente=e.ambiente, origem="emitida", situacao="autorizada",
            serie=e.serie, n_dps=n_dps, id_dps=dps.id, chave=chave, numero=str(numero),
            d_compet=hoje.isoformat(), dh_emissao=dh[:19], prestador_doc=CNPJ_TESTE,
            prestador_nome=RAZAO_TESTE, tomador_doc=tom.documento, tomador_nome=tom.nome,
            descricao=desc, v_serv=valor, v_liq=valor, dps_xml=xml_dps,
            nfse_xml=_nfse_ficticia(xml_dps, chave, str(numero), dh))
    return e


def remover_empresa_teste(banco: Banco) -> bool:
    """Apaga a empresa fictícia e tudo dela (notas, certificado, numeração). Só ela."""
    e = banco.empresa_por_cnpj(CNPJ_TESTE)
    if not e:
        return False
    for c in banco.certificados(e.id):
        cofre.esquecer_senha(c["chave_cofre"])
        Path(c["arquivo"]).unlink(missing_ok=True)
    con = banco.con
    with con.trava:
        ids = [r[0] for r in con.execute("SELECT id FROM notas WHERE empresa_id=?", (e.id,))]
        for i in ids:
            con.execute("DELETE FROM envios_email WHERE nota_id=?", (i,))
        con.execute("DELETE FROM eventos WHERE chave IN (SELECT chave FROM notas WHERE empresa_id=?)",
                    (e.id,))
        for tabela in ("notas", "certificados", "numeracao", "controle_nsu", "empresa_tomadores",
                       "config_email"):
            con.execute(f"DELETE FROM {tabela} WHERE empresa_id=?", (e.id,))
        for t in TOMADORES:                 # os fictícios, se nenhuma outra empresa os usa
            con.execute("DELETE FROM tomadores WHERE documento=? AND NOT EXISTS "
                        "(SELECT 1 FROM empresa_tomadores WHERE documento=?)",
                        (t.documento, t.documento))
        banco.excluir_empresa(e.id)
    return True
