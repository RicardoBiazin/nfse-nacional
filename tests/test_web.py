"""Versão web: primeiro acesso, login, papéis, CSRF, empresa/certificado, emissão, notas, lote."""
import io
import re
import time
import zipfile

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from nfse_nacional import cofre, compactacao, dpapi  # noqa: E402
from nfse_nacional.banco import Banco  # noqa: E402
from nfse_nacional.web.app import criar_app  # noqa: E402

from .conftest import CNPJ, SENHA, _pfx  # noqa: E402
from .test_servico import (CHAVE, SessaoFalsa, _emissao_ok, evento_cancelamento,  # noqa: E402
                           nfse_de, resposta)

pytestmark = pytest.mark.skipif(not dpapi.disponivel(), reason="cofre do servidor usa DPAPI (Windows)")


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def ctx(tmp_path):
    banco = Banco(tmp_path / "web.db")
    sessao = SessaoFalsa()
    app = criar_app(banco, sessao_http=lambda cert: sessao)
    c = TestClient(app, base_url="http://testserver")
    yield c, banco, sessao, tmp_path
    cofre.usar_keyring()
    banco.fechar()


def _login(c, login="admin", senha="Senha123"):
    r = c.get("/login")
    return c.post("/login", data={"login": login, "senha": senha, "csrf": _csrf(r.text), "prox": "/notas"},
                  follow_redirects=False)


def _preparar(c, banco, tmp_path):
    r = c.get("/notas")                                         # sem usuários -> primeiro acesso
    assert "Criar o administrador" in r.text
    c.post("/primeiro-acesso", data={"login": "admin", "nome": "Admin", "senha": "Senha123",
                                     "senha2": "Senha123", "csrf": _csrf(r.text)})
    assert _login(c).status_code == 303
    r = c.get("/empresa")
    pfx = _pfx(CNPJ, SENHA, 400)
    r = c.post("/empresa/certificados", data={"senha": SENHA, "csrf": _csrf(r.text)},
               files={"pfx": ("empresa.pfx", pfx, "application/x-pkcs12")})
    assert r.status_code == 200 and "adicionado" in r.text
    r = c.post("/empresa", data={"csrf": _csrf(r.text), "razao": "EMPRESA TESTE", "c_mun": "4205407",
                                 "op_simp_nac": "3", "reg_ap_trib_sn": "1", "reg_esp_trib": "0",
                                 "c_trib_nac": "010601", "c_nbs": "115011000", "serie": "1",
                                 "proximo": "1", "ambiente": "producao_restrita", "p_tot_sn": "5,50",
                                 "descricao_padrao": "Consultoria ERP", "convenio_ativo": ""})
    assert "Cadastro salvo" in r.text
    e = banco.empresa_por_cnpj(CNPJ)
    assert (e.c_mun, e.p_tot_sn) == ("4205407", "5.50")
    # senha do certificado cifrada no banco (DPAPI), não no keyring
    assert banco.con.execute("SELECT count(*) FROM segredos").fetchone()[0] == 1
    return e


def test_fluxo_completo(ctx):
    c, banco, sessao, tmp = ctx
    _preparar(c, banco, tmp)
    sessao.rota("POST", r"/nfse$", _emissao_ok)
    r = c.get("/emitir")
    assert "Consultoria ERP" in r.text and "5,50" in r.text
    r = c.post("/emitir", data={"csrf": _csrf(r.text), "acao": "emitir", "t_doc": "11444777000161",
                                "t_nome": "CLIENTE EXEMPLO", "descricao": "Consultoria ERP",
                                "compet": "2026-09-01", "v_serv": "1.500,00", "trib_issqn": "1",
                                "tp_ret_issqn": "1", "p_sn": "7,10", "ibs": ""})
    assert "autorizada" in r.text, r.text[:2000]
    nota = banco.nota_por_chave(CHAVE)
    assert nota["situacao"] == "autorizada" and nota["v_serv"] == "1500.00"
    assert banco.empresa_por_cnpj(CNPJ).p_tot_sn == "7.10"
    aud = [a["acao"] for a in banco.auditoria()]
    assert "emitir" in aud and "login" in aud

    r = c.get("/notas?ambiente=producao_restrita")
    assert "CLIENTE EXEMPLO" in r.text and "1.500,00" in r.text
    pdf = c.get(f"/notas/{nota['id']}/danfse")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    xml = c.get(f"/notas/{nota['id']}/xml")
    assert xml.content.startswith(b"<") and CHAVE.encode() in xml.content
    z = c.post("/notas/exportar", data={"csrf": _csrf(r.text), "ids": str(nota["id"]), "xml": "1",
                                        "pdf": "1", "ambiente": "producao_restrita"})
    nomes = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert any(n.endswith(".pdf") for n in nomes) and any(n.endswith(".xml") for n in nomes)
    assert c.get("/notas/planilha?ambiente=producao_restrita").content[:2] == b"PK"

    # duplicar preenche a emissão
    r = c.get(f"/notas/{nota['id']}/duplicar")
    assert 'value="11444777000161"' in r.text and "1.500,00" in r.text

    # cancelar (admin)
    sessao.rota("POST", rf"/nfse/{CHAVE}/eventos$", lambda u, k: resposta(
        201, {"eventoXmlGZipB64": compactacao.para_gzip_b64(evento_cancelamento())}))
    r = c.get(f"/notas/{nota['id']}/cancelar")
    r = c.post(f"/notas/{nota['id']}/cancelar", data={"csrf": _csrf(r.text), "motivo": "1",
                                                     "justificativa": "Valor digitado errado na nota"})
    assert banco.nota(nota["id"])["situacao"] == "cancelada"


def test_validacao_e_alíquota_proibida(ctx):
    c, banco, sessao, tmp = ctx
    _preparar(c, banco, tmp)
    r = c.get("/fragmentos/aliquota?trib_issqn=1&tp_ret_issqn=1")
    assert "disabled" in r.text
    r = c.get("/fragmentos/aliquota?trib_issqn=1&tp_ret_issqn=2")
    assert "Obrigatória" in r.text
    r = c.get("/emitir")
    r = c.post("/emitir", data={"csrf": _csrf(r.text), "acao": "emitir", "descricao": "x",
                                "v_serv": "10", "p_aliq": "6", "trib_issqn": "1", "tp_ret_issqn": "1"})
    assert r.status_code == 400 and "E0595" in r.text
    assert not banco.notas(banco.empresa_por_cnpj(CNPJ).id, "producao_restrita")


def test_fragmentos_de_codigo(ctx):
    c, banco, sessao, tmp = ctx
    _preparar(c, banco, tmp)
    assert "Assessoria e consultoria" in c.get("/fragmentos/descricao?tabela=servico&codigo=010601").text
    assert "não encontrado" in c.get("/fragmentos/descricao?tabela=servico&codigo=999999").text
    assert "Belo Horizonte" in c.get("/fragmentos/opcoes?tabela=municipio&q=belo hori").text


def test_papeis_csrf_e_bloqueio(ctx):
    c, banco, sessao, tmp = ctx
    _preparar(c, banco, tmp)
    r = c.get("/usuarios")
    c.post("/usuarios", data={"csrf": _csrf(r.text), "login": "contab", "nome": "Contabilidade",
                              "papel": "consulta", "senha": "Contab2026"})
    # sem token CSRF: recusado
    assert c.post("/usuarios", data={"login": "x", "senha": "Abcdefg12"}).status_code == 403
    c.post("/sair", data={"csrf": _csrf(c.get("/notas").text)})
    assert _login(c, "contab", "Contab2026").status_code == 303
    assert c.get("/notas").status_code == 200
    assert c.get("/emitir").status_code == 403
    assert c.get("/usuarios").status_code == 403
    r = c.get("/notas")
    assert c.post("/emitir", data={"csrf": _csrf(r.text), "descricao": "x", "v_serv": "1"}).status_code == 403
    c.post("/sair", data={"csrf": _csrf(r.text)})
    for _ in range(5):
        assert _login(c, "contab", "errada000").status_code == 401
    assert _login(c, "contab", "Contab2026").status_code == 401      # bloqueado 15 min
    assert banco.usuario("contab")["bloqueado_ate"]


def test_sincronizar_e_importar_em_tarefa(ctx):
    c, banco, sessao, tmp = ctx
    e = _preparar(c, banco, tmp)
    sessao.rota("GET", r"/contribuintes/DFe/", lambda u, k: resposta(
        404, {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO"}))
    r = c.get("/notas")
    r = c.post("/notas/sincronizar", data={"csrf": _csrf(r.text), "ambiente": "producao"},
               follow_redirects=False)
    tarefa = r.headers["location"].split("/tarefas/")[1].split("?")[0]
    for _ in range(50):
        frag = c.get(f"/fragmentos/tarefa/{tarefa}").text
        if "every 1s" not in frag:
            break
        time.sleep(0.1)
    assert "0 documento(s)" in frag

    from nfse_nacional.dps import gerar_xml, para_bytes
    from nfse_nacional.servico import DadosNota, Emissor
    from decimal import Decimal
    em = Emissor(banco, e, cofre.certificado_ativo(banco, e), sessao=sessao)
    x = nfse_de(para_bytes(gerar_xml(em.montar_dps(DadosNota("Serviço", Decimal("50")), 9))),
                chave="4205407" + "8" * 43, numero="9")
    r = c.get("/notas")
    r = c.post("/notas/importar", data={"csrf": _csrf(r.text), "ambiente": "producao"},
               files=[("arquivos", ("nota9.xml", x, "application/xml"))], follow_redirects=False)
    tarefa = r.headers["location"].split("/tarefas/")[1].split("?")[0]
    for _ in range(50):
        frag = c.get(f"/fragmentos/tarefa/{tarefa}").text
        if "every 1s" not in frag:
            break
        time.sleep(0.1)
    assert "1 documento(s) importado(s)" in frag
    assert banco.nota_por_chave("4205407" + "8" * 43)


def test_inatividade_e_redirecionamento(ctx):
    c, banco, sessao, tmp = ctx
    _preparar(c, banco, tmp)
    assert c.get("/notas", follow_redirects=False).status_code == 200
    r = c.get("/conta")
    c.post("/sair", data={"csrf": _csrf(r.text)})
    r = c.get("/notas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
