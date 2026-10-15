"""Fluxos do Emissor contra uma API simulada (sem rede)."""
import datetime as dt
import json
import re
from decimal import Decimal

import pytest
import requests
from lxml import etree

from nfse_nacional import compactacao
from nfse_nacional.banco import Banco, Empresa, Tomador
from nfse_nacional.config import NS_NFSE
from nfse_nacional.servico import DadosNota, Emissor, ErroValidacao

from .conftest import CNPJ

CHAVE = "4115200" + "1" * 43
N = {"n": NS_NFSE}


def resposta(status=200, corpo=None, conteudo: bytes | None = None):
    r = requests.Response()
    r.status_code = status
    if conteudo is not None:
        r._content = conteudo
    else:
        r._content = json.dumps(corpo or {}).encode()
        r.headers["Content-Type"] = "application/json"
    return r


def nfse_de(dps_xml: bytes, chave=CHAVE, numero="15", emitente=CNPJ) -> bytes:
    dps = etree.fromstring(dps_xml)
    nfse = etree.Element(f"{{{NS_NFSE}}}NFSe", nsmap={None: NS_NFSE}, versao="1.01")
    inf = etree.SubElement(nfse, f"{{{NS_NFSE}}}infNFSe", Id=f"NFS{chave}")
    for nome, valor in (("xLocEmi", "Maringá"), ("nNFSe", numero), ("cStat", "100"),
                        ("dhProc", "2026-10-01T10:00:00-03:00")):
        etree.SubElement(inf, f"{{{NS_NFSE}}}{nome}").text = valor
    emit = etree.SubElement(inf, f"{{{NS_NFSE}}}emit")
    etree.SubElement(emit, f"{{{NS_NFSE}}}CNPJ").text = emitente
    etree.SubElement(emit, f"{{{NS_NFSE}}}xNome").text = "EMPRESA TESTE LTDA"
    val = etree.SubElement(inf, f"{{{NS_NFSE}}}valores")
    etree.SubElement(val, f"{{{NS_NFSE}}}vISSQN").text = "30.00"
    etree.SubElement(val, f"{{{NS_NFSE}}}vLiq").text = "1500.00"
    inf.append(dps)
    return etree.tostring(nfse)


def evento_cancelamento(chave=CHAVE) -> bytes:
    return f"""<evento xmlns="{NS_NFSE}" versao="1.01"><infEvento Id="EVT{chave}101101001">
<dhProc>2026-10-01T11:00:00-03:00</dhProc><pedRegEvento versao="1.01"><infPedReg Id="PRE{chave}101101">
<chNFSe>{chave}</chNFSe><e101101><xDesc>Cancelamento de NFS-e</xDesc><cMotivo>1</cMotivo>
<xMotivo>Erro na emissão da nota fiscal</xMotivo></e101101></infPedReg></pedRegEvento></infEvento></evento>""".encode()


class SessaoFalsa:
    """Responde por (método, regex do caminho); grava as chamadas."""

    def __init__(self):
        self.rotas = []
        self.chamadas = []

    def rota(self, metodo, padrao, funcao):
        self.rotas.append((metodo, re.compile(padrao), funcao))

    def _req(self, metodo, url, **kw):
        self.chamadas.append((metodo, url, kw))
        for m, p, f in self.rotas:
            if m == metodo and p.search(url):
                return f(url, kw)
        return resposta(404, {"erros": [{"codigo": "404", "descricao": "rota não simulada"}]})

    def post(self, url, **kw): return self._req("POST", url, **kw)
    def get(self, url, **kw): return self._req("GET", url, **kw)
    def head(self, url, **kw): return self._req("HEAD", url, **kw)


@pytest.fixture
def banco(tmp_path):
    b = Banco(tmp_path / "t.db")
    yield b
    b.fechar()


@pytest.fixture
def empresa(banco):
    return banco.salvar_empresa(Empresa(
        cnpj=CNPJ, razao="EMPRESA TESTE LTDA", im="12345", c_mun="4115200",
        op_simp_nac="3", reg_ap_trib_sn="1", c_trib_nac="010701", c_nbs="115013000",
        p_tot_sn="6.00"))


def dados(**kw):
    base = dict(descricao="Suporte técnico", v_serv=Decimal("1500.00"),
                tomador=Tomador(documento="12345678909", nome="Fulano de Tal"),
                d_compet=dt.date(2026, 9, 30))
    base.update(kw)
    return DadosNota(**base)


def _emissao_ok(url, kw):
    dps = compactacao.de_gzip_b64(kw["json"]["dpsXmlGZipB64"])
    return resposta(201, {"chaveAcesso": CHAVE, "idDps": "x",
                          "nfseXmlGZipB64": compactacao.para_gzip_b64(nfse_de(dps)),
                          "alertas": [{"codigo": "A1", "descricao": "aviso"}]})


def test_emissao_autorizada(banco, empresa, certificado):
    s = SessaoFalsa()
    s.rota("POST", r"/nfse$", _emissao_ok)
    r = Emissor(banco, empresa, certificado, sessao=s).emitir(dados())
    assert (r.situacao, r.chave, r.numero) == ("autorizada", CHAVE, "15")
    nota = banco.nota(r.nota_id)
    assert nota["n_dps"] == 1 and nota["v_issqn"] == "30.00" and b"<DPS" in nota["dps_xml"]
    assert "A1" in nota["mensagem"]
    assert banco.tomador("12345678909").nome == "Fulano de Tal"
    # a URL é a da Produção Restrita
    assert s.chamadas[0][1].startswith("https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse")


def test_numeracao_sequencial_e_erro_de_validacao_nao_queima_numero(banco, empresa, certificado):
    s = SessaoFalsa()
    s.rota("POST", r"/nfse$", _emissao_ok)
    em = Emissor(banco, empresa, certificado, sessao=s)
    em.emitir(dados())
    with pytest.raises(ErroValidacao):
        em.emitir(dados(v_serv=Decimal("0")))
    s.rotas.clear()
    s.rota("POST", r"/nfse$", lambda u, k: resposta(201, {
        "chaveAcesso": "4115200" + "2" * 43,
        "nfseXmlGZipB64": compactacao.para_gzip_b64(
            nfse_de(compactacao.de_gzip_b64(k["json"]["dpsXmlGZipB64"]),
                    chave="4115200" + "2" * 43, numero="16"))}))
    r = em.emitir(dados())
    assert banco.nota(r.nota_id)["n_dps"] == 2


def test_rejeicao(banco, empresa, certificado):
    s = SessaoFalsa()
    s.rota("POST", r"/nfse$", lambda u, k: resposta(400, {"erros": [
        {"codigo": "E0312", "descricao": "Código de tributação nacional inexistente"}]}))
    r = Emissor(banco, empresa, certificado, sessao=s).emitir(dados())
    assert r.situacao == "rejeitada" and "E0312" in r.mensagem


def test_timeout_recupera_pela_dps(banco, empresa, certificado):
    s = SessaoFalsa()
    enviado = {}

    def timeout(u, k):
        enviado["dps"] = compactacao.de_gzip_b64(k["json"]["dpsXmlGZipB64"])
        raise requests.ReadTimeout("demorou")
    s.rota("POST", r"/nfse$", timeout)
    s.rota("GET", r"/dps/DPS\d{42}$", lambda u, k: resposta(200, {"chaveAcesso": CHAVE}))
    s.rota("GET", rf"/nfse/{CHAVE}$", lambda u, k: resposta(200, {
        "nfseXmlGZipB64": compactacao.para_gzip_b64(nfse_de(enviado["dps"]))}))
    r = Emissor(banco, empresa, certificado, sessao=s).emitir(dados())
    assert r.situacao == "autorizada" and r.chave == CHAVE
    assert [c[0] for c in s.chamadas] == ["POST", "GET", "GET"]


def test_indefinida_e_reconsulta_reenvia_a_mesma_dps(banco, empresa, certificado):
    s = SessaoFalsa()
    s.rota("POST", r"/nfse$", lambda u, k: (_ for _ in ()).throw(requests.ConnectionError("caiu")))
    s.rota("GET", r"/dps/", lambda u, k: (_ for _ in ()).throw(requests.ConnectionError("caiu")))
    em = Emissor(banco, empresa, certificado, sessao=s)
    r = em.emitir(dados())
    assert r.situacao == "indefinida"
    dps_original = banco.nota(r.nota_id)["dps_xml"]

    s.rotas.clear()
    s.rota("GET", r"/dps/", lambda u, k: resposta(404, {}))
    reenvios = []

    def ok(u, k):
        reenvios.append(compactacao.de_gzip_b64(k["json"]["dpsXmlGZipB64"]))
        return _emissao_ok(u, k)
    s.rota("POST", r"/nfse$", ok)
    r2 = em.reconsultar(r.nota_id)
    assert r2.situacao == "autorizada"
    assert reenvios == [dps_original]          # mesma DPS, mesmo número


def test_cancelamento(banco, empresa, certificado):
    s = SessaoFalsa()
    s.rota("POST", r"/nfse$", _emissao_ok)
    recebido = {}

    def evento(u, k):
        recebido["xml"] = compactacao.de_gzip_b64(k["json"]["pedidoRegistroEventoXmlGZipB64"])
        return resposta(201, {"eventoXmlGZipB64": compactacao.para_gzip_b64(evento_cancelamento())})
    s.rota("POST", rf"/nfse/{CHAVE}/eventos$", evento)
    em = Emissor(banco, empresa, certificado, sessao=s)
    r = em.emitir(dados())
    em.cancelar(r.nota_id, "1", "Erro na emissão da nota fiscal")
    assert banco.nota(r.nota_id)["situacao"] == "cancelada"
    assert banco.eventos(CHAVE)[0]["tipo"] == "101101"
    assert b"<CNPJAutor>" + CNPJ.encode() in recebido["xml"]


def test_sincronizacao_adn(banco, empresa, certificado):
    from nfse_nacional.dps import gerar_xml, para_bytes
    em = Emissor(banco, empresa, certificado, sessao=SessaoFalsa())
    dps = para_bytes(gerar_xml(em.montar_dps(dados(), 99)))
    dps_rec = para_bytes(gerar_xml(em.montar_dps(dados(), 100))).replace(
        CNPJ.encode(), b"99888777000166")
    chave_rec = "4115200" + "9" * 43
    lotes = {
        1: [{"NSU": 1, "ChaveAcesso": CHAVE, "TipoDocumento": "NFSE",
             "ArquivoXml": compactacao.para_gzip_b64(nfse_de(dps))},
            {"NSU": 2, "ChaveAcesso": chave_rec, "TipoDocumento": "NFSE",
             "ArquivoXml": compactacao.para_gzip_b64(
                 nfse_de(dps_rec, chave=chave_rec, numero="7", emitente="99888777000166"))}],
        3: [{"NSU": 3, "ChaveAcesso": CHAVE, "TipoDocumento": "EVENTO",
             "ArquivoXml": compactacao.para_gzip_b64(evento_cancelamento())}],
    }

    def dfe(u, k):
        nsu = int(re.search(r"/DFe/(\d+)", u).group(1))
        assert k["params"]["cnpjConsulta"] == CNPJ
        if nsu in lotes:
            return resposta(200, {"StatusProcessamento": "DOCUMENTOS_LOCALIZADOS",
                                  "LoteDFe": lotes[nsu], "MaiorNSU": 3})
        return resposta(404, {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO"})
    em._sessao.rota("GET", r"/contribuintes/DFe/", dfe)

    assert em.sincronizar() == 3
    assert banco.ultimo_nsu(empresa.id, empresa.ambiente) == 3
    emitida = banco.nota_por_chave(CHAVE)
    recebida = banco.nota_por_chave(chave_rec)
    assert (emitida["origem"], emitida["situacao"]) == ("emitida", "cancelada")
    assert (recebida["origem"], recebida["situacao"]) == ("recebida", "autorizada")
    # Segunda rodada não baixa nada de novo.
    assert em.sincronizar() == 0


def test_reserva_de_numero_e_definir_proximo(banco, empresa):
    assert banco.reservar_numero(empresa.id, "producao", "1") == 1
    assert banco.reservar_numero(empresa.id, "producao", "1") == 2
    assert banco.reservar_numero(empresa.id, "producao_restrita", "1") == 1
    banco.definir_proximo_numero(empresa.id, "producao", "1", 500)
    assert banco.reservar_numero(empresa.id, "producao", "1") == 500


def test_me_epp_vai_com_piscofins_como_o_portal(banco, empresa, certificado):
    """Nota real do Emissor Web (ME/EPP): tribFed/piscofins CST 00 e tpRetPisCofins 0."""
    em = Emissor(banco, empresa, certificado, sessao=SessaoFalsa())
    raiz = etree.fromstring(em.preparar(em.montar_dps(dados(), 1)))
    pc = raiz.find(".//n:tribFed/n:piscofins", N)
    assert pc.findtext("n:CST", namespaces=N) == "00"
    assert pc.findtext("n:tpRetPisCofins", namespaces=N) == "0"


def test_tomadores_separados_por_empresa(banco, empresa, certificado):
    """Regressão (0.7.1): a busca de tomador listava os tomadores de todas as empresas."""
    from nfse_nacional.banco import Empresa
    outra = banco.salvar_empresa(Empresa(cnpj="99888777000166", razao="OUTRA"))
    banco.salvar_tomador(Tomador(documento="11111111000191", nome="CLIENTE DA PRIMEIRA"), empresa.id)
    banco.salvar_tomador(Tomador(documento="22222222000191", nome="CLIENTE DA OUTRA"), outra.id)
    banco.salvar_tomador(Tomador(documento="33333333000191", nome="CLIENTE DAS DUAS"), empresa.id)
    banco.ligar_tomador(outra.id, "33333333000191")
    nomes = lambda e: [t.nome for t in banco.tomadores(empresa_id=e.id)]   # noqa: E731
    assert nomes(empresa) == ["CLIENTE DA PRIMEIRA", "CLIENTE DAS DUAS"]
    assert nomes(outra) == ["CLIENTE DA OUTRA", "CLIENTE DAS DUAS"]
    assert len(banco.tomadores()) == 3                     # sem empresa: todos (uso interno)
    # emitir liga o tomador à empresa que emitiu
    s = SessaoFalsa(); s.rota("POST", r"/nfse$", _emissao_ok)
    Emissor(banco, empresa, certificado, sessao=s).emitir(dados())
    assert "Fulano de Tal" in nomes(empresa) and "Fulano de Tal" not in nomes(outra)


def test_ligacao_recuperada_das_notas_antigas(tmp_path):
    """Banco da 0.7.1 (sem empresa_tomadores): ao abrir, liga pelos tomadores das notas emitidas."""
    from nfse_nacional.banco import Banco, Empresa
    b = Banco(tmp_path / "antigo.db")
    e = b.salvar_empresa(Empresa(cnpj=CNPJ))
    b.salvar_tomador(Tomador(documento="11444777000161", nome="CLIENTE"))      # sem empresa
    b.inserir_nota(empresa_id=e.id, ambiente="producao", origem="emitida", situacao="autorizada",
                   tomador_doc="11444777000161", tomador_nome="CLIENTE")
    b.con.execute("DELETE FROM empresa_tomadores")
    b.fechar()
    b2 = Banco(tmp_path / "antigo.db")
    assert [t.nome for t in b2.tomadores(empresa_id=e.id)] == ["CLIENTE"]
    b2.fechar()
