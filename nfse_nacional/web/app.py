"""Versão web interna (FastAPI + Jinja2 + HTMX) sobre o mesmo núcleo do desktop.

Um servidor na rede guarda banco, certificados e numeração; as pessoas entram pelo navegador
com login próprio. Toda regra fiscal continua em servico.Emissor / regras / danfse.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import io
import secrets
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import requests
from fastapi import Depends, FastAPI, Form, Request, UploadFile
from fastapi.responses import (HTMLResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import VERSAO, cofre, exportar, regras, tabelas
from ..banco import Banco, Empresa, Tomador
from ..certificado import Certificado, SenhaCertificadoIncorreta
from ..cliente_http import ErroApi, sessao_mtls
from ..dps import so_digitos
from ..eventos import MOTIVOS_CANCELAMENTO
from ..servico import (DadosNota, Emissor, ErroValidacao, dados_de_xml,
                       tomadores_de_notas)
from . import auth

AQUI = Path(__file__).resolve().parent
INATIVIDADE = dt.timedelta(minutes=60)
SITUACOES = ["autorizada", "cancelada", "rejeitada", "indefinida", "pendente"]


# ====================================================================== infraestrutura

class NaoLogado(Exception):
    pass


class SemPermissao(Exception):
    pass


class Tarefas:
    """Tarefas longas (sincronizar ADN, importar lote) em thread, acompanhadas pela página."""

    def __init__(self):
        self._t: dict[str, dict] = {}
        self._trava = threading.Lock()

    def iniciar(self, titulo: str, usuario: str, funcao: Callable[[Callable[[str], None]], object]) -> str:
        id_ = uuid.uuid4().hex[:12]
        info = {"titulo": titulo, "usuario": usuario, "estado": "rodando", "mensagem": "Iniciando…",
                "resultado": "", "inicio": time.time()}
        with self._trava:
            self._t[id_] = info

        def rodar():
            try:
                r = funcao(lambda m: info.__setitem__("mensagem", m))
                info["resultado"] = str(r) if r is not None else "Concluído."
                info["estado"] = "ok"
            except Exception as erro:      # noqa: BLE001 - vai para a página
                info["resultado"] = texto_erro(erro)
                info["estado"] = "erro"
                info["detalhe"] = traceback.format_exc()
        threading.Thread(target=rodar, daemon=True, name=f"tarefa-{id_}").start()
        return id_

    def ver(self, id_: str) -> dict | None:
        return self._t.get(id_)


def texto_erro(erro: Exception) -> str:
    if isinstance(erro, ErroValidacao):
        return "Corrija antes de enviar: " + "; ".join(erro.erros)
    if isinstance(erro, ErroApi):
        return f"O sistema nacional recusou (HTTP {erro.status}): " + \
            ("; ".join(str(m) for m in erro.mensagens) or erro.corpo[:300])
    if isinstance(erro, requests.exceptions.SSLError):
        return "Conexão recusada: o servidor não aceitou o certificado (precisa ser A1 ICP-Brasil válido)."
    if isinstance(erro, requests.RequestException):
        return f"Falha de comunicação com o sistema nacional: {erro}"
    return str(erro) or erro.__class__.__name__


def _dec(texto: str | None) -> Decimal | None:
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Valor inválido: {texto!r}") from None


def moeda(v) -> str:
    if v in (None, ""):
        return ""
    s = f"{Decimal(str(v)):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(v: str | None) -> str:
    return "/".join(reversed(v[:10].split("-"))) if v else ""


def fmt_doc(d: str | None) -> str:
    d = d or ""
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


# ====================================================================== aplicação

def criar_app(banco: Banco | None = None, sessao_http: Callable[[Certificado], requests.Session] | None = None,
              https: bool = False, chave_sessao: str | None = None,
              ca_crt: Path | None = None) -> FastAPI:
    banco = banco or Banco()
    cofre.usar_cofre_do_servidor(banco)
    fabrica_sessao = sessao_http or sessao_mtls
    app = FastAPI(title="NFS-e Nacional", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.banco = banco
    app.state.tarefas = Tarefas()
    sessoes_mtls: dict[tuple, requests.Session] = {}
    trava_mtls = threading.Lock()

    app.add_middleware(SessionMiddleware, secret_key=chave_sessao or secrets.token_urlsafe(32),
                       session_cookie="nfse_sessao", max_age=12 * 3600, same_site="strict",
                       https_only=https)
    app.mount("/static", StaticFiles(directory=str(AQUI / "static")), name="static")
    tpl = Jinja2Templates(directory=str(AQUI / "templates"))
    tpl.env.globals.update(VERSAO=VERSAO, moeda=moeda, data_br=data_br, fmt_doc=fmt_doc,
                           nome_municipio=tabelas.nome_municipio, PAPEIS=auth.NOMES_PAPEIS,
                           MOTIVOS=MOTIVOS_CANCELAMENTO)

    # ------------------------------------------------------------ dependências
    def ip_de(request: Request) -> str:
        return request.client.host if request.client else ""

    def usuario_logado(request: Request):
        s = request.session
        uid = s.get("uid")
        if not uid:
            raise NaoLogado()
        ultimo = s.get("ultimo", 0)
        if time.time() - ultimo > INATIVIDADE.total_seconds():
            s.clear()
            raise NaoLogado()
        u = banco.usuario_por_id(uid)
        if not u or not u["ativo"]:
            s.clear()
            raise NaoLogado()
        s["ultimo"] = time.time()
        return u

    def exigir(papel: str):
        def dep(u=Depends(usuario_logado)):
            if not auth.pode(u["papel"], papel):
                raise SemPermissao()
            return u
        return dep

    async def csrf(request: Request):
        if request.method != "POST":
            return
        token = request.headers.get("x-csrf-token")
        if not token:
            token = (await request.form()).get("csrf")
        if not token or not secrets.compare_digest(str(token), request.session.get("csrf", "")):
            raise SemPermissao("Sessão expirada ou formulário inválido (CSRF). Recarregue a página.")

    def empresa_atual(request: Request) -> Empresa | None:
        empresas = banco.empresas()
        if not empresas:
            return None
        id_ = request.session.get("empresa_id")
        e = next((x for x in empresas if x.id == id_), empresas[0])
        request.session["empresa_id"] = e.id
        return e

    def emissor(request: Request, u, empresa: Empresa, ambiente: str | None = None) -> Emissor:
        cert = cofre.certificado_ativo(banco, empresa)
        if ambiente and ambiente != empresa.ambiente:
            empresa = dataclasses.replace(empresa, ambiente=ambiente)
        chave = (empresa.id, cert.cert.serial_number)
        with trava_mtls:
            sess = sessoes_mtls.get(chave)
            if sess is None:
                sess = sessoes_mtls[chave] = fabrica_sessao(cert)
        return Emissor(banco, empresa, cert, sessao=sess, usuario=u["login"], ip=ip_de(request))

    def pagina(request: Request, nome: str, u=None, status: int = 200, **ctx):
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(24)
        empresa = empresa_atual(request) if u else None
        ctx.update(request=request, u=u, empresa=empresa, empresas=banco.empresas() if u else [],
                   csrf=request.session["csrf"], pode=lambda p: bool(u) and auth.pode(u["papel"], p),
                   aviso=request.session.pop("aviso", None), erro_flash=request.session.pop("erro", None))
        return tpl.TemplateResponse(request, nome, ctx, status_code=status)

    def flash(request: Request, aviso: str = "", erro: str = ""):
        if aviso:
            request.session["aviso"] = aviso
        if erro:
            request.session["erro"] = erro

    @app.exception_handler(NaoLogado)
    async def _nao_logado(request: Request, _e):
        if request.headers.get("hx-request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse(f"/login?prox={request.url.path}", status_code=303)

    @app.exception_handler(SemPermissao)
    async def _sem_permissao(request: Request, e):
        return HTMLResponse(f"<h3>Sem permissão</h3><p>{e or 'Seu perfil não permite esta ação.'}</p>"
                            "<p><a href='/notas'>Voltar</a></p>", status_code=403)

    @app.middleware("http")
    async def _cabecalhos(request: Request, call_next):
        r = await call_next(request)
        r.headers.setdefault("X-Frame-Options", "DENY")
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("Referrer-Policy", "same-origin")
        r.headers.setdefault("Cache-Control", "no-store")
        return r

    # ------------------------------------------------------------ login
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, prox: str = "/notas"):
        if not banco.ha_usuarios():
            return RedirectResponse("/primeiro-acesso", status_code=303)
        return pagina(request, "login.html", prox=prox)

    @app.post("/login", dependencies=[Depends(csrf)])
    def login(request: Request, login: str = Form(...), senha: str = Form(...), prox: str = Form("/notas")):
        u = auth.autenticar(banco, login, senha, ip_de(request))
        if not u:
            return pagina(request, "login.html", prox=prox, status=401,
                          erro="Usuário ou senha incorretos (5 erros bloqueiam por 15 minutos).")
        request.session.clear()
        request.session.update(uid=u["id"], ultimo=time.time(), csrf=secrets.token_urlsafe(24))
        destino = prox if prox.startswith("/") and not prox.startswith("//") else "/notas"
        return RedirectResponse(destino, status_code=303)

    @app.post("/sair", dependencies=[Depends(csrf)])
    def sair(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/primeiro-acesso", response_class=HTMLResponse)
    def primeiro_form(request: Request):
        if banco.ha_usuarios():
            return RedirectResponse("/login", status_code=303)
        return pagina(request, "primeiro_acesso.html")

    @app.post("/primeiro-acesso", dependencies=[Depends(csrf)])
    def primeiro(request: Request, login: str = Form(...), nome: str = Form(""),
                 senha: str = Form(...), senha2: str = Form(...)):
        if banco.ha_usuarios():
            return RedirectResponse("/login", status_code=303)
        motivo = auth.senha_fraca(senha) or ("As senhas não conferem." if senha != senha2 else "")
        if motivo or not login.strip():
            return pagina(request, "primeiro_acesso.html", erro=motivo or "Informe o login.", status=400)
        banco.criar_usuario(login, nome, auth.gerar_hash(senha), "admin")
        banco.auditar(login, "criar-admin-inicial", ip=ip_de(request))
        flash(request, aviso="Administrador criado. Entre com o login e a senha.")
        return RedirectResponse("/login", status_code=303)

    @app.get("/ca.crt")
    def baixar_ca():
        """Certificado PÚBLICO da AC local do servidor, para os PCs da rede confiarem no HTTPS."""
        if not ca_crt or not Path(ca_crt).exists():
            return Response(status_code=404)
        return Response(Path(ca_crt).read_bytes(), media_type="application/x-x509-ca-cert",
                        headers={"Content-Disposition": 'attachment; filename="NFSe_Nacional_AC.crt"'})

    @app.get("/")
    def raiz():
        return RedirectResponse("/notas", status_code=303)

    @app.post("/empresa/selecionar", dependencies=[Depends(csrf)])
    def selecionar_empresa(request: Request, empresa_id: int = Form(...), u=Depends(usuario_logado)):
        if banco.empresa(empresa_id):
            request.session["empresa_id"] = empresa_id
        return RedirectResponse(request.headers.get("referer") or "/notas", status_code=303)

    # ------------------------------------------------------------ notas
    def _filtros(request: Request, e: Empresa) -> dict:
        q = request.query_params
        hoje = dt.date.today()
        return {"ambiente": q.get("ambiente") or "producao",
                "inicio": q.get("inicio") or f"{hoje.year}-01-01",
                "fim": q.get("fim") or (hoje + dt.timedelta(days=31)).isoformat(),
                "origem": q.get("origem", ""), "situacao": q.get("situacao", ""),
                "q": q.get("q", "").strip()}

    def _linhas(e: Empresa, f: dict):
        return banco.notas(e.id, f["ambiente"], f["inicio"], f["fim"], f["origem"],
                           f["situacao"], f["q"])

    @app.get("/notas", response_class=HTMLResponse)
    def notas(request: Request, u=Depends(usuario_logado)):
        e = empresa_atual(request)
        if not e:
            return RedirectResponse("/empresa", status_code=303)
        f = _filtros(request, e)
        linhas = _linhas(e, f)
        total = sum(Decimal(n["v_serv"] or 0) for n in linhas
                    if n["origem"] == "emitida" and n["situacao"] == "autorizada")
        return pagina(request, "notas.html", u, linhas=linhas, f=f, total=total,
                      situacoes=SITUACOES)

    def _nota(id_: int, e: Empresa):
        n = banco.nota(id_)
        if not n or n["empresa_id"] != e.id:
            raise SemPermissao("Nota não encontrada nesta empresa.")
        return n

    @app.get("/notas/{id_}/danfse")
    def danfse(request: Request, id_: int, u=Depends(usuario_logado)):
        e = empresa_atual(request)
        n = _nota(id_, e)
        try:
            pdf = emissor(request, u, e, n["ambiente"]).danfse(id_)
        except Exception as erro:      # noqa: BLE001
            flash(request, erro=texto_erro(erro))
            return RedirectResponse("/notas", status_code=303)
        nome = f"DANFSe_{n['numero'] or ''}_{n['chave']}.pdf"
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{nome}"'})

    @app.get("/notas/{id_}/xml")
    def xml(request: Request, id_: int, u=Depends(usuario_logado)):
        n = _nota(id_, empresa_atual(request))
        conteudo = n["nfse_xml"] or n["dps_xml"]
        if not conteudo:
            flash(request, erro="Nota sem XML.")
            return RedirectResponse("/notas", status_code=303)
        nome = f"NFSe_{n['numero'] or ''}_{n['chave'] or n['id_dps']}.xml"
        return Response(conteudo, media_type="application/xml",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.post("/notas/{id_}/reconsultar", dependencies=[Depends(csrf)])
    def reconsultar(request: Request, id_: int, u=Depends(exigir("emissor"))):
        e = empresa_atual(request)
        n = _nota(id_, e)
        try:
            r = emissor(request, u, e, n["ambiente"]).reconsultar(id_)
            flash(request, aviso=f"Situação: {r.situacao}. {r.mensagem or ''}")
        except Exception as erro:      # noqa: BLE001
            flash(request, erro=texto_erro(erro))
        return RedirectResponse(request.headers.get("referer") or "/notas", status_code=303)

    @app.get("/notas/{id_}/cancelar", response_class=HTMLResponse)
    def cancelar_form(request: Request, id_: int, u=Depends(exigir("admin"))):
        return pagina(request, "cancelar.html", u, n=_nota(id_, empresa_atual(request)))

    @app.post("/notas/{id_}/cancelar", dependencies=[Depends(csrf)])
    def cancelar(request: Request, id_: int, motivo: str = Form(...), justificativa: str = Form(...),
                 u=Depends(exigir("admin"))):
        e = empresa_atual(request)
        n = _nota(id_, e)
        try:
            emissor(request, u, e, n["ambiente"]).cancelar(id_, motivo, justificativa)
            flash(request, aviso=f"NFS-e nº {n['numero']} cancelada.")
            return RedirectResponse("/notas?ambiente=" + n["ambiente"], status_code=303)
        except Exception as erro:      # noqa: BLE001
            return pagina(request, "cancelar.html", u, n=n, erro=texto_erro(erro), status=400)

    @app.get("/notas/{id_}/duplicar")
    def duplicar(id_: int):
        return RedirectResponse(f"/emitir?duplicar={id_}", status_code=303)

    @app.post("/notas/sincronizar", dependencies=[Depends(csrf)])
    def sincronizar(request: Request, ambiente: str = Form("producao"), u=Depends(usuario_logado)):
        e = empresa_atual(request)
        em = emissor(request, u, e, ambiente)

        def tarefa(avisar):
            n = em.sincronizar(avisar)
            tomadores_de_notas(banco, e.id)
            return f"{n} documento(s) novo(s) baixado(s) do ADN."
        banco.auditar(u["login"], "sincronizar", ambiente, ip=ip_de(request))
        id_ = app.state.tarefas.iniciar(f"Sincronizar ADN ({ambiente})", u["login"], tarefa)
        return RedirectResponse(f"/tarefas/{id_}?voltar=/notas?ambiente={ambiente}", status_code=303)

    @app.post("/notas/importar", dependencies=[Depends(csrf)])
    async def importar(request: Request, arquivos: list[UploadFile], ambiente: str = Form("producao"),
                       u=Depends(exigir("emissor"))):
        e = empresa_atual(request)
        pasta = Path(tempfile.mkdtemp(prefix="nfse_import_"))
        caminhos = []
        for i, a in enumerate(arquivos):
            nome = Path(a.filename or f"arquivo{i}").name
            if Path(nome).suffix.lower() not in (".xml", ".pdf", ".zip"):
                continue
            destino = pasta / f"{i:04d}_{nome}"
            destino.write_bytes(await a.read())
            caminhos.append(destino)
        em = emissor(request, u, e, ambiente)

        def tarefa(avisar):
            try:
                return em.importar_arquivos(caminhos, avisar)
            finally:
                for c in caminhos:
                    c.unlink(missing_ok=True)
                pasta.rmdir()
        banco.auditar(u["login"], "importar", f"{len(caminhos)} arquivo(s)", ip=ip_de(request))
        id_ = app.state.tarefas.iniciar("Importar XML/PDF", u["login"], tarefa)
        return RedirectResponse(f"/tarefas/{id_}?voltar=/notas?ambiente={ambiente}", status_code=303)

    @app.post("/notas/exportar", dependencies=[Depends(csrf)])
    async def exportar_lote(request: Request, u=Depends(usuario_logado)):
        e = empresa_atual(request)
        form = await request.form()
        ids = [int(x) for x in form.getlist("ids") if str(x).isdigit()]
        f = {k: form.get(k, "") for k in ("ambiente", "inicio", "fim", "origem", "situacao", "q")}
        if not ids:
            ids = [n["id"] for n in _linhas(e, f)]
        ids = [i for i in ids if (n := banco.nota(i)) and n["empresa_id"] == e.id]
        com_xml, com_pdf = bool(form.get("xml")), bool(form.get("pdf"))
        if not ids or not (com_xml or com_pdf):
            flash(request, erro="Nada para exportar (escolha notas e XML e/ou PDF).")
            return RedirectResponse("/notas", status_code=303)
        with tempfile.TemporaryDirectory(prefix="nfse_export_") as tmp:
            n_xml, n_pdf, erros = exportar.exportar_notas(banco, ids, tmp, com_xml, com_pdf)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in sorted(Path(tmp).iterdir()):
                    z.write(p, p.name)
                if erros:
                    z.writestr("ERROS.txt", "\n".join(erros))
        banco.auditar(u["login"], "exportar", f"{len(ids)} nota(s): {n_xml} XML, {n_pdf} PDF",
                      ip=ip_de(request))
        buf.seek(0)
        nome = f"NFSe_{dt.date.today():%Y%m%d}_{len(ids)}notas.zip"
        return StreamingResponse(buf, media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{nome}"'})

    @app.get("/notas/planilha")
    def planilha(request: Request, u=Depends(usuario_logado)):
        e = empresa_atual(request)
        f = _filtros(request, e)
        with tempfile.TemporaryDirectory() as tmp:
            arq = exportar.exportar_xlsx(_linhas(e, f), Path(tmp) / "notas.xlsx")
            dados = arq.read_bytes()
        return Response(dados, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="NFSe_{f["inicio"]}_{f["fim"]}.xlsx"'})

    # ------------------------------------------------------------ tarefas
    @app.get("/tarefas/{id_}", response_class=HTMLResponse)
    def tarefa_pagina(request: Request, id_: str, voltar: str = "/notas", u=Depends(usuario_logado)):
        t = app.state.tarefas.ver(id_)
        if not t:
            return RedirectResponse(voltar, status_code=303)
        return pagina(request, "tarefa.html", u, t=t, id_=id_, voltar=voltar)

    @app.get("/fragmentos/tarefa/{id_}", response_class=HTMLResponse)
    def tarefa_frag(request: Request, id_: str, voltar: str = "/notas", u=Depends(usuario_logado)):
        t = app.state.tarefas.ver(id_)
        return tpl.TemplateResponse(request, "_tarefa.html", {"t": t, "id_": id_, "voltar": voltar})

    # ------------------------------------------------------------ emitir
    def _form_vazio(e: Empresa | None) -> dict:
        return {"descricao": e.descricao_padrao if e else "", "compet": dt.date.today().isoformat(),
                "trib_issqn": "1", "tp_ret_issqn": "1", "p_sn": moeda(e.p_tot_sn) if e else "",
                "ibs": "1"}

    def _form_de_dados(d: DadosNota, e: Empresa) -> dict:
        f = _form_vazio(e)
        t = d.tomador
        if t:
            f.update(t_doc=t.documento, t_nome=t.nome, t_im=t.im, t_email=t.email, t_fone=t.fone,
                     t_cmun=t.c_mun, t_cep=t.cep, t_lgr=t.logradouro, t_nro=t.numero,
                     t_cpl=t.complemento, t_bairro=t.bairro)
        f.update(descricao=d.descricao, c_trib_nac=d.c_trib_nac, c_trib_mun=d.c_trib_mun,
                 c_nbs=d.c_nbs, c_loc=d.c_loc_prestacao, info=d.info_complementar,
                 v_serv=moeda(d.v_serv), v_desc=moeda(d.v_desc_incond) if d.v_desc_incond else "",
                 p_aliq=moeda(d.p_aliq) if d.p_aliq is not None else "",
                 trib_issqn=d.trib_issqn, tp_ret_issqn=d.tp_ret_issqn)
        return f

    def _dados_do_form(f: dict) -> DadosNota:
        doc = so_digitos(f.get("t_doc"))
        tomador = None
        if doc:
            if len(doc) not in (11, 14):
                raise ValueError("CPF/CNPJ do tomador inválido.")
            if not f.get("t_nome", "").strip():
                raise ValueError("Informe o nome do tomador.")
            end = [f.get(k, "").strip() for k in ("t_cmun", "t_cep", "t_lgr", "t_bairro")]
            if any(end + [f.get("t_nro", "").strip()]) and not all(end):
                raise ValueError("Endereço do tomador incompleto: município, CEP, logradouro e bairro "
                                 "são obrigatórios (ou deixe todos vazios).")
            tomador = Tomador(documento=doc, nome=f["t_nome"].strip(), im=f.get("t_im", "").strip(),
                              email=f.get("t_email", "").strip(), fone=f.get("t_fone", "").strip(),
                              c_mun=so_digitos(f.get("t_cmun")), cep=so_digitos(f.get("t_cep")),
                              logradouro=f.get("t_lgr", "").strip(), numero=f.get("t_nro", "").strip(),
                              complemento=f.get("t_cpl", "").strip(), bairro=f.get("t_bairro", "").strip())
        v = _dec(f.get("v_serv"))
        if v is None:
            raise ValueError("Informe o valor do serviço.")
        if not f.get("descricao", "").strip():
            raise ValueError("Informe a descrição do serviço.")
        p_aliq = _dec(f.get("p_aliq"))
        return DadosNota(
            descricao=f["descricao"].strip(), v_serv=v, tomador=tomador,
            d_compet=dt.date.fromisoformat(f.get("compet") or dt.date.today().isoformat()),
            c_trib_nac=so_digitos(f.get("c_trib_nac")), c_trib_mun=so_digitos(f.get("c_trib_mun")),
            c_nbs=so_digitos(f.get("c_nbs")), c_loc_prestacao=so_digitos(f.get("c_loc")),
            p_aliq=p_aliq, usar_aliquota_padrao=p_aliq is None,
            tp_ret_issqn=f.get("tp_ret_issqn") or "1", trib_issqn=f.get("trib_issqn") or "1",
            v_desc_incond=_dec(f.get("v_desc")), info_complementar=f.get("info", "").strip(),
            incluir_ibscbs=bool(f.get("ibs")),
            p_tot_trib_sn=_dec(f.get("p_sn")) if f.get("p_sn") not in (None, "") else None)

    def _tela_emitir(request, u, e, f, erros=None, resultado=None, status=200):
        regra = _regra_aliquota(e, f.get("trib_issqn", "1"), f.get("tp_ret_issqn", "1"))
        return pagina(request, "emitir.html", u, f=f, erros=erros or [], resultado=resultado,
                      regra=regra, tomadores=banco.tomadores(empresa_id=e.id), status=status)

    @app.get("/emitir", response_class=HTMLResponse)
    def emitir_form(request: Request, duplicar: int | None = None, repetir: str = "",
                    u=Depends(exigir("emissor"))):
        e = empresa_atual(request)
        if not e:
            return RedirectResponse("/empresa", status_code=303)
        tomadores_de_notas(banco, e.id)
        f = _form_vazio(e)
        origem = None
        if duplicar:
            origem = _nota(duplicar, e)
        elif repetir:
            origem = banco.ultima_nota_do_tomador(e.id, so_digitos(repetir))
            if not origem:
                t = banco.tomador(so_digitos(repetir))
                if t:
                    f = _form_de_dados(DadosNota(descricao=f["descricao"], v_serv=Decimal(0), tomador=t), e)
                    f["v_serv"] = ""
        if origem is not None and (origem["nfse_xml"] or origem["dps_xml"]):
            f = _form_de_dados(dados_de_xml(origem["nfse_xml"] or origem["dps_xml"]), e)
        return _tela_emitir(request, u, e, f)

    @app.post("/emitir", dependencies=[Depends(csrf)])
    async def emitir(request: Request, u=Depends(exigir("emissor"))):
        e = empresa_atual(request)
        f = {k: str(v) for k, v in (await request.form()).items()}
        acao = f.get("acao", "emitir")
        try:
            dados = _dados_do_form(f)
            em = emissor(request, u, e)
            if acao == "validar":
                n = banco.proximo_numero(e.id, e.ambiente, e.serie)
                xml_ = em.preparar(em.montar_dps(dados, n))
                return Response(xml_, media_type="application/xml",
                                headers={"Content-Disposition": f'attachment; filename="DPS_{n}_validada.xml"'})
            if e.ambiente == "producao" and not f.get("confirmo_producao"):
                return _tela_emitir(request, u, e, f, status=400, erros=[
                    "Ambiente de PRODUÇÃO: marque a confirmação de que a nota tem valor fiscal."])
            r = em.emitir(dados)
            if r.situacao == "autorizada" and dados.p_tot_trib_sn is not None:
                novo = f"{dados.p_tot_trib_sn:.2f}"
                if novo != e.p_tot_sn:
                    e.p_tot_sn = novo
                    banco.salvar_empresa(e)
            if r.situacao == "autorizada":
                return _tela_emitir(request, u, e, _form_vazio(banco.empresa(e.id)), resultado=r)
            return _tela_emitir(request, u, e, f, resultado=r, status=400)
        except ErroValidacao as erro:
            return _tela_emitir(request, u, e, f, erros=erro.erros, status=400)
        except Exception as erro:      # noqa: BLE001
            return _tela_emitir(request, u, e, f, erros=[texto_erro(erro)], status=400)

    # ------------------------------------------------------------ fragmentos (HTMX)
    def _regra_aliquota(e: Empresa | None, trib: str, ret: str) -> str:
        if not e:
            return regras.OPCIONAL
        conv = None if e.convenio_ativo is None else bool(e.convenio_ativo)
        return regras.aliquota_exigida(e.op_simp_nac, e.reg_ap_trib_sn, e.reg_esp_trib, trib, ret, conv)

    @app.get("/fragmentos/aliquota", response_class=HTMLResponse)
    def frag_aliquota(request: Request, trib_issqn: str = "1", tp_ret_issqn: str = "1",
                      p_aliq: str = "", u=Depends(usuario_logado)):
        regra = _regra_aliquota(empresa_atual(request), trib_issqn, tp_ret_issqn)
        return tpl.TemplateResponse(request, "_aliquota.html", {"regra": regra, "valor": p_aliq})

    @app.get("/fragmentos/descricao", response_class=HTMLResponse)
    def frag_descricao(tabela: str, codigo: str = "", padrao: str = "", u=Depends(usuario_logado)):
        cod = so_digitos(codigo.split(" - ")[0]) or so_digitos(padrao)
        if tabela not in ("servico", "nbs", "municipio") or not cod:
            return HTMLResponse("")
        desc = tabelas.descrever(tabela, cod.zfill(6) if tabela == "servico" else cod)
        prefixo = "padrão da empresa: " if not so_digitos(codigo) else ""
        if desc:
            return HTMLResponse(f'<span class="desc">{prefixo}{cod} - {_esc(desc)}</span>')
        return HTMLResponse(f'<span class="desc alerta">{cod}: código não encontrado na tabela oficial</span>')

    @app.get("/fragmentos/opcoes", response_class=HTMLResponse)
    def frag_opcoes(tabela: str, q: str = "", u=Depends(usuario_logado)):
        fonte = {"servico": tabelas.servicos, "nbs": tabelas.nbs, "municipio": tabelas.municipios}.get(tabela)
        q = q.split(" - ")[0].strip().lower()
        if not fonte or len(q) < 2:
            return HTMLResponse("")
        achados = [f"{c} - {d}" for c, d in fonte().items() if q in c or q in d.lower()][:40]
        return HTMLResponse("".join(f'<option value="{_esc(x)}">' for x in achados))

    @app.get("/fragmentos/tomador", response_class=HTMLResponse)
    def frag_tomador(request: Request, busca: str = "", u=Depends(usuario_logado)):
        doc = so_digitos(busca.split(" — ")[-1]) if " — " in busca else so_digitos(busca)
        t = banco.tomador(doc) if doc else None
        f = {}
        if t:
            f = dict(t_doc=t.documento, t_nome=t.nome, t_im=t.im, t_email=t.email, t_fone=t.fone,
                     t_cmun=t.c_mun, t_cep=t.cep, t_lgr=t.logradouro, t_nro=t.numero,
                     t_cpl=t.complemento, t_bairro=t.bairro)
        return tpl.TemplateResponse(request, "_tomador.html", {"f": f, "achou": bool(t)})

    # ------------------------------------------------------------ empresa e certificados
    @app.get("/empresa", response_class=HTMLResponse)
    def empresa_form(request: Request, u=Depends(usuario_logado)):
        e = empresa_atual(request)
        certs = banco.certificados(e.id) if e else []
        if e:
            cofre.migrar_certificado_antigo(banco, e)
            certs = banco.certificados(e.id)
        prox = banco.proximo_numero(e.id, e.ambiente, e.serie) if e else 1
        return pagina(request, "empresa.html", u, certs=certs, prox=prox,
                      agora=dt.datetime.now(dt.timezone.utc).isoformat())

    @app.post("/empresa", dependencies=[Depends(csrf)])
    async def empresa_salvar(request: Request, u=Depends(exigir("admin"))):
        e = empresa_atual(request)
        f = {k: str(v) for k, v in (await request.form()).items()}
        if not e:
            return RedirectResponse("/empresa", status_code=303)
        mudou_para_producao = e.ambiente != "producao" and f.get("ambiente") == "producao"
        if mudou_para_producao and not f.get("confirmo_producao"):
            flash(request, erro="Para mudar para PRODUÇÃO, marque a confirmação.")
            return RedirectResponse("/empresa", status_code=303)
        for campo in ("razao", "im", "fone", "email", "p_aliq", "p_tot_fed", "p_tot_est",
                      "p_tot_mun", "p_tot_sn", "descricao_padrao", "ibs_c_ind_op", "ibs_cst",
                      "ibs_c_class_trib", "op_simp_nac", "reg_ap_trib_sn", "reg_esp_trib", "ambiente"):
            if campo in f:
                valor = f[campo].strip()
                if campo.startswith("p_"):
                    valor = valor.replace(".", "").replace(",", ".") if "," in valor else valor
                setattr(e, campo, valor)
        for campo in ("c_mun", "c_trib_nac", "c_trib_mun", "c_nbs", "serie"):
            if campo in f:
                setattr(e, campo, so_digitos(f[campo].split(" - ")[0]))
        e.serie = e.serie or "1"
        if not 1 <= int(e.serie) <= 49999:
            flash(request, erro="Série do aplicativo próprio vai de 1 a 49999 (70000+ é do portal).")
            return RedirectResponse("/empresa", status_code=303)
        if e.op_simp_nac != "3":
            e.reg_ap_trib_sn = ""
        conv = f.get("convenio_ativo", "")
        e.convenio_ativo = None if conv == "" else int(conv)
        banco.salvar_empresa(e)
        prox = f.get("proximo", "")
        if prox.isdigit() and int(prox) != banco.proximo_numero(e.id, e.ambiente, e.serie):
            banco.definir_proximo_numero(e.id, e.ambiente, e.serie, int(prox))
        banco.auditar(u["login"], "empresa", f"cadastro salvo (ambiente {e.ambiente})", ip=ip_de(request))
        flash(request, aviso="Cadastro salvo.")
        return RedirectResponse("/empresa", status_code=303)

    @app.post("/empresa/consultar-municipio", dependencies=[Depends(csrf)])
    def consultar_municipio(request: Request, u=Depends(exigir("admin"))):
        """Convênio ativo e alíquota do ISS do serviço padrão, direto do sistema nacional."""
        e = empresa_atual(request)
        if not e or not e.c_mun:
            flash(request, erro="Informe e salve o município (IBGE) antes de consultar.")
            return RedirectResponse("/empresa", status_code=303)
        try:
            p = emissor(request, u, e).parametros_municipio()
        except Exception as erro:      # noqa: BLE001
            flash(request, erro=texto_erro(erro))
            return RedirectResponse("/empresa", status_code=303)
        e.convenio_ativo = 1 if p.ativo else 0
        if p.aliquota is not None:
            e.p_aliq = f"{p.aliquota:.2f}"
        banco.salvar_empresa(e)
        texto = p.texto(tabelas.nome_municipio(e.c_mun)).replace("\n", " ")
        banco.auditar(u["login"], "consultar-municipio", texto, ip=ip_de(request))
        flash(request, aviso=texto + " Convênio e alíquota padrão atualizados no cadastro.")
        return RedirectResponse("/empresa", status_code=303)

    @app.post("/empresa/certificados", dependencies=[Depends(csrf)])
    async def cert_adicionar(request: Request, pfx: UploadFile, senha: str = Form(...),
                             principal: str = Form(""), u=Depends(exigir("admin"))):
        dados = await pfx.read()
        if len(dados) > 100_000:
            flash(request, erro="Arquivo grande demais para um certificado A1.")
            return RedirectResponse("/empresa", status_code=303)
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "certificado.pfx"
            arq.write_bytes(dados)
            try:
                previa = Certificado.de_arquivo(arq, senha)
                doc = previa.documento[1]
                e = empresa_atual(request)
                existente = banco.empresa_por_cnpj(doc)
                if existente:
                    e = existente
                elif not e or (e.cnpj[:8] != doc[:8]):
                    # Empresa nova a partir do certificado.
                    e = banco.salvar_empresa(Empresa(cnpj=doc, razao=previa.titular.split(":")[0]))
                cofre.migrar_certificado_antigo(banco, e)
                cert, _ = cofre.adicionar_a_empresa(banco, e, arq, senha, principal=bool(principal))
                request.session["empresa_id"] = e.id
                banco.auditar(u["login"], "certificado-adicionar",
                              f"{cert.titular} até {cert.validade:%d/%m/%Y}", ip=ip_de(request))
                flash(request, aviso=f"Certificado de {cert.titular} adicionado (válido até {cert.validade:%d/%m/%Y}).")
            except SenhaCertificadoIncorreta:
                flash(request, erro="Senha do certificado incorreta.")
            except Exception as erro:      # noqa: BLE001
                flash(request, erro=texto_erro(erro))
        return RedirectResponse("/empresa", status_code=303)

    @app.post("/empresa/certificados/{cid}/principal", dependencies=[Depends(csrf)])
    def cert_principal(request: Request, cid: int, u=Depends(exigir("admin"))):
        e = empresa_atual(request)
        if any(r["id"] == cid for r in banco.certificados(e.id)):
            banco.definir_certificado_principal(e.id, cid)
            banco.auditar(u["login"], "certificado-principal", str(cid), ip=ip_de(request))
        return RedirectResponse("/empresa", status_code=303)

    @app.post("/empresa/certificados/{cid}/remover", dependencies=[Depends(csrf)])
    def cert_remover(request: Request, cid: int, u=Depends(exigir("admin"))):
        e = empresa_atual(request)
        cofre.remover_da_empresa(banco, e, cid)
        banco.auditar(u["login"], "certificado-remover", str(cid), ip=ip_de(request))
        flash(request, aviso="Certificado removido.")
        return RedirectResponse("/empresa", status_code=303)

    # ------------------------------------------------------------ usuários e conta
    @app.get("/usuarios", response_class=HTMLResponse)
    def usuarios(request: Request, u=Depends(exigir("admin"))):
        return pagina(request, "usuarios.html", u, lista=banco.usuarios())

    @app.post("/usuarios", dependencies=[Depends(csrf)])
    def usuario_criar(request: Request, login: str = Form(...), nome: str = Form(""),
                      papel: str = Form("consulta"), senha: str = Form(...), u=Depends(exigir("admin"))):
        motivo = auth.senha_fraca(senha)
        if papel not in auth.PAPEIS:
            motivo = "Papel inválido."
        if not motivo and banco.usuario(login):
            motivo = "Já existe um usuário com esse login."
        if motivo:
            flash(request, erro=motivo)
        else:
            banco.criar_usuario(login, nome, auth.gerar_hash(senha), papel)
            banco.auditar(u["login"], "usuario-criar", f"{login} ({papel})", ip=ip_de(request))
            flash(request, aviso=f"Usuário {login} criado.")
        return RedirectResponse("/usuarios", status_code=303)

    @app.post("/usuarios/{uid}", dependencies=[Depends(csrf)])
    def usuario_alterar(request: Request, uid: int, papel: str = Form(None), ativo: str = Form(""),
                        nova_senha: str = Form(""), u=Depends(exigir("admin"))):
        alvo = banco.usuario_por_id(uid)
        if not alvo:
            return RedirectResponse("/usuarios", status_code=303)
        campos = {}
        if papel in auth.PAPEIS:
            campos["papel"] = papel
        campos["ativo"] = 1 if ativo else 0
        if uid == u["id"] and (campos.get("papel", "admin") != "admin" or not campos["ativo"]):
            flash(request, erro="Você não pode tirar o próprio acesso de administrador.")
            return RedirectResponse("/usuarios", status_code=303)
        if nova_senha:
            motivo = auth.senha_fraca(nova_senha)
            if motivo:
                flash(request, erro=motivo)
                return RedirectResponse("/usuarios", status_code=303)
            campos.update(hash_senha=auth.gerar_hash(nova_senha), falhas=0, bloqueado_ate=None)
        banco.atualizar_usuario(uid, **campos)
        banco.auditar(u["login"], "usuario-alterar",
                      f"{alvo['login']}: {', '.join(k for k in campos if k != 'hash_senha')}"
                      + (" + senha" if nova_senha else ""), ip=ip_de(request))
        flash(request, aviso=f"Usuário {alvo['login']} atualizado.")
        return RedirectResponse("/usuarios", status_code=303)

    @app.get("/conta", response_class=HTMLResponse)
    def conta(request: Request, u=Depends(usuario_logado)):
        return pagina(request, "conta.html", u)

    @app.post("/conta", dependencies=[Depends(csrf)])
    def conta_salvar(request: Request, atual: str = Form(...), nova: str = Form(...),
                     nova2: str = Form(...), u=Depends(usuario_logado)):
        motivo = ("Senha atual incorreta." if not auth.conferir(atual, u["hash_senha"]) else
                  auth.senha_fraca(nova) or ("As senhas não conferem." if nova != nova2 else ""))
        if motivo:
            return pagina(request, "conta.html", u, erro=motivo, status=400)
        banco.atualizar_usuario(u["id"], hash_senha=auth.gerar_hash(nova))
        banco.auditar(u["login"], "trocar-senha", ip=ip_de(request))
        flash(request, aviso="Senha alterada.")
        return RedirectResponse("/notas", status_code=303)

    @app.get("/auditoria", response_class=HTMLResponse)
    def auditoria(request: Request, u=Depends(exigir("admin"))):
        return pagina(request, "auditoria.html", u, linhas=banco.auditoria(500))

    return app


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
