"""Consulta de CNPJ/CEP (APIs públicas, simuladas) e envio da NFS-e por e-mail (SMTP falso)."""
import email
import email.policy
import smtplib

import keyring
import pytest

from nfse_nacional import consultas, email_nfse
from nfse_nacional.banco import Banco, ConfigEmail, Empresa, Tomador

from .conftest import CNPJ
from .test_cli import CofreMemoria
from .test_danfse import _nfse

CNPJ_TOMADOR = "11444777000161"


class Resp:
    def __init__(self, status, dados=None):
        self.status_code = status
        self._dados = dados

    def json(self):
        return self._dados

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


class Rede:
    """Sessão falsa: url -> Resp (ou exceção). Registra as chamadas."""

    def __init__(self, rotas):
        self.rotas = rotas
        self.chamadas = []

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(url)
        for trecho, r in self.rotas.items():
            if trecho in url:
                if isinstance(r, Exception):
                    raise r
                return r
        return Resp(404, {})


BRASILAPI = {"razao_social": "CLIENTE EXEMPLO SERVICOS LTDA", "nome_fantasia": "EXEMPLO",
             "cep": "88020010", "logradouro": "DOS EXEMPLOS", "descricao_tipo_de_logradouro": "RUA",
             "numero": "100", "complemento": "", "bairro": "CENTRO", "municipio": "FLORIANOPOLIS",
             "uf": "SC", "codigo_municipio_ibge": 4205407, "ddd_telefone_1": "4830001234",
             "email": None, "descricao_situacao_cadastral": "ATIVA"}
VIACEP = {"cep": "88020-010", "logradouro": "Rua dos Exemplos", "bairro": "Centro",
          "localidade": "Florianópolis", "uf": "SC", "ibge": "4205407"}


def test_cnpj_valido():
    assert consultas.cnpj_valido(CNPJ_TOMADOR)
    assert consultas.cnpj_valido("11.222.333/0001-81")
    assert not consultas.cnpj_valido("11444777000162")
    assert not consultas.cnpj_valido("00000000000000")


def test_cnpj_pela_brasilapi_com_grafia_do_cep():
    rede = Rede({"brasilapi.com.br/api/cnpj": Resp(200, BRASILAPI), "viacep": Resp(200, VIACEP)})
    c = consultas.consultar_cnpj(CNPJ_TOMADOR, rede)
    assert c.nome == "CLIENTE EXEMPLO SERVICOS LTDA" and c.situacao == "ATIVA"
    assert c.fone == "4830001234" and c.numero == "100" and c.email == ""
    e = c.endereco
    assert (e.cep, e.c_mun, e.logradouro, e.bairro) == ("88020010", "4205407", "Rua dos Exemplos", "Centro")
    assert e.municipio.startswith("Florian")


def test_cnpj_cai_para_cnpjws_quando_brasilapi_falha():
    import requests
    ws = {"razao_social": "CLIENTE EXEMPLO SERVICOS LTDA",
          "estabelecimento": {"tipo_logradouro": "RUA", "logradouro": "DOS EXEMPLOS", "numero": "100",
                              "bairro": "CENTRO", "cep": "88020010", "ddd1": "48", "telefone1": "30001234",
                              "email": "Financeiro@Exemplo.com.br", "situacao_cadastral": "Ativa",
                              "cidade": {"ibge_id": 4205407}, "estado": {"sigla": "SC"}}}
    rede = Rede({"brasilapi.com.br/api/cnpj": requests.ConnectionError("fora do ar"),
                 "publica.cnpj.ws": Resp(200, ws), "viacep": Resp(200, {"erro": "true"})})
    c = consultas.consultar_cnpj(CNPJ_TOMADOR, rede)
    assert c.email == "financeiro@exemplo.com.br" and c.fone == "4830001234"
    assert c.endereco.logradouro == "RUA DOS EXEMPLOS" and c.endereco.c_mun == "4205407"
    assert "CNPJ.ws" in c.fonte


def test_cnpj_inexistente_e_invalido():
    with pytest.raises(consultas.ErroConsulta, match="não encontrado"):
        consultas.consultar_cnpj(CNPJ_TOMADOR, Rede({"brasilapi": Resp(404, {})}))
    with pytest.raises(consultas.ErroConsulta, match="inválido"):
        consultas.consultar_cnpj("11444777000162", Rede({}))


def test_cep_viacep_e_fallback_brasilapi():
    end = consultas.consultar_cep("88020-010", Rede({"viacep": Resp(200, VIACEP)}))
    assert (end.logradouro, end.bairro, end.c_mun) == ("Rua dos Exemplos", "Centro", "4205407")
    v2 = {"cep": "88020010", "state": "SC", "city": "Florianópolis", "neighborhood": "Centro",
          "street": "Rua dos Exemplos"}               # sem o código IBGE: sai pelo nome
    end = consultas.consultar_cep("88020010", Rede({"viacep": Resp(503), "brasilapi.com.br/api/cep": Resp(200, v2)}))
    assert end.c_mun == "4205407"
    with pytest.raises(consultas.ErroConsulta, match="não encontrado"):
        consultas.consultar_cep("99999999", Rede({"viacep": Resp(200, {"erro": "true"})}))


def test_sem_rede_mensagem_clara():
    with pytest.raises(consultas.ErroConsulta, match="sem internet"):
        consultas.consultar_cep("88020010")         # conftest bloqueia a rede


# ------------------------------------------------------------------ e-mail

class SMTPFalso:
    enviados: list = []
    instancias: list = []

    def __init__(self, host, porta, timeout=None, context=None):
        self.host, self.porta, self.tls, self.login_feito = host, porta, False, None
        SMTPFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.tls = True

    def login(self, usuario, senha):
        if senha != "segredo":
            raise smtplib.SMTPAuthenticationError(535, b"senha errada")
        self.login_feito = usuario

    def send_message(self, msg, to_addrs=None):
        SMTPFalso.enviados.append((msg, to_addrs))


@pytest.fixture
def smtp(monkeypatch):
    SMTPFalso.enviados, SMTPFalso.instancias = [], []
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTPFalso)
    anterior = keyring.get_keyring()
    keyring.set_keyring(CofreMemoria())
    yield SMTPFalso
    keyring.set_keyring(anterior)


@pytest.fixture
def banco_com_nota(tmp_path):
    b = Banco(tmp_path / "e.db")
    e = b.salvar_empresa(Empresa(cnpj=CNPJ, razao="EMPRESA EXEMPLO"))
    b.salvar_tomador(Tomador(documento=CNPJ_TOMADOR, nome="CLIENTE EXEMPLO",
                             email="cliente@exemplo.com.br"), e.id)
    nid = b.inserir_nota(empresa_id=e.id, ambiente="producao", origem="emitida", situacao="autorizada",
                         chave="4" * 50, numero="17", d_compet="2026-09-01", prestador_nome="EMPRESA EXEMPLO",
                         tomador_doc=CNPJ_TOMADOR, tomador_nome="CLIENTE EXEMPLO", v_serv="1500.00",
                         nfse_xml=_nfse())
    yield b, e, nid
    b.fechar()


def test_separar_enderecos():
    assert email_nfse.separar_enderecos("a@x.com; b@y.com.br , c@z.io") == ["a@x.com", "b@y.com.br", "c@z.io"]
    assert email_nfse.separar_enderecos("") == []
    with pytest.raises(ValueError, match="inválido"):
        email_nfse.separar_enderecos("a@x.com, sem-arroba")


def test_enviar_nota_ao_tomador_com_pdf_e_xml(smtp, banco_com_nota):
    b, e, nid = banco_com_nota
    b.salvar_config_email(ConfigEmail(empresa_id=e.id, host="smtp.exemplo.com", porta=587,
                                      usuario="nfe@exemplo.com.br", remetente="nfe@exemplo.com.br",
                                      nome_remetente="Empresa Exemplo", copia="arquivo@exemplo.com.br"))
    email_nfse.guardar_senha_smtp(e.id, "segredo")
    assert email_nfse.enviar_nota(b, nid) == ["cliente@exemplo.com.br"]
    conexao = smtp.instancias[-1]
    assert conexao.tls and conexao.login_feito == "nfe@exemplo.com.br"
    msg, destinos = smtp.enviados[-1]
    assert destinos == ["cliente@exemplo.com.br", "arquivo@exemplo.com.br"]   # cópia oculta
    assert "arquivo@" not in str(msg)                                        # não vaza no cabeçalho
    assert msg["Subject"] == "NFS-e nº 17 - EMPRESA EXEMPLO"
    lida = email.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    anexos = {p.get_filename(): p.get_content_type() for p in lida.walk() if p.get_filename()}
    assert anexos == {f"NFSe_17_{'4' * 50}.pdf": "application/pdf",
                      f"NFSe_17_{'4' * 50}.xml": "application/xml"}
    corpo = next(p for p in lida.walk() if p.get_content_type() == "text/plain").get_content()
    assert "R$ 1.500,00" in corpo and "01/09/2026" in corpo and "ConsultaPublica" in corpo
    linhas = b.notas(e.id, "producao")
    assert linhas[0]["email_enviado"]


def test_falha_de_envio_fica_registrada(smtp, banco_com_nota):
    b, e, nid = banco_com_nota
    b.salvar_config_email(ConfigEmail(empresa_id=e.id, host="smtp.exemplo.com", seguranca="ssl", porta=465,
                                      usuario="nfe@exemplo.com.br", remetente="nfe@exemplo.com.br"))
    email_nfse.guardar_senha_smtp(e.id, "errada")
    with pytest.raises(smtplib.SMTPAuthenticationError):
        email_nfse.enviar_nota(b, nid, "outro@exemplo.com")
    envio = b.envios(nid)[0]
    assert envio["ok"] == 0 and "senha errada" in envio["erro"] and envio["para"] == "outro@exemplo.com"
    assert not b.notas(e.id, "producao")[0]["email_enviado"]


def test_enviar_sem_configuracao_ou_sem_email(smtp, banco_com_nota):
    b, e, nid = banco_com_nota
    with pytest.raises(ValueError, match="Configure o envio"):
        email_nfse.enviar_nota(b, nid)
    b.salvar_config_email(ConfigEmail(empresa_id=e.id, host="smtp.exemplo.com", remetente="nfe@exemplo.com.br",
                                      assunto="Sua nota {numero} {campo_que_nao_existe}"))
    b.salvar_tomador(Tomador(documento=CNPJ_TOMADOR, nome="CLIENTE EXEMPLO", email=""), e.id)
    with pytest.raises(ValueError, match="não tem e-mail"):
        email_nfse.enviar_nota(b, nid)
    email_nfse.enviar_nota(b, nid, "x@exemplo.com")              # sem usuário: SMTP sem login
    msg, _ = smtp.enviados[-1]
    assert msg["Subject"] == "Sua nota 17 {campo_que_nao_existe}"
    assert smtp.instancias[-1].login_feito is None
