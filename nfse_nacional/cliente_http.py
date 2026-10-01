"""Sessão HTTP com mTLS (certificado A1) e tratamento das respostas da API."""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter

from . import VERSAO
from .certificado import Certificado

TIMEOUT = (15, 60)   # conexão, leitura


class _AdaptadorMTLS(HTTPAdapter):
    def __init__(self, contexto, **kw):
        self._contexto = contexto
        super().__init__(**kw)

    def init_poolmanager(self, *args, **kw):
        kw["ssl_context"] = self._contexto
        return super().init_poolmanager(*args, **kw)

    def proxy_manager_for(self, *args, **kw):
        kw["ssl_context"] = self._contexto
        return super().proxy_manager_for(*args, **kw)


def sessao_mtls(cert: Certificado) -> requests.Session:
    s = requests.Session()
    s.mount("https://", _AdaptadorMTLS(cert.contexto_ssl()))
    s.headers.update({"Accept": "application/json",
                      "User-Agent": f"NFSE_Nacional/{VERSAO}"})
    return s


@dataclass
class Mensagem:
    codigo: str = ""
    descricao: str = ""
    complemento: str = ""

    def __str__(self) -> str:
        texto = f"{self.codigo} - {self.descricao}".strip(" -")
        return f"{texto} ({self.complemento})" if self.complemento else texto


class ErroApi(Exception):
    def __init__(self, status: int, mensagens: list[Mensagem], corpo: str = ""):
        self.status = status
        self.mensagens = mensagens
        self.corpo = corpo
        detalhe = "; ".join(str(m) for m in mensagens) or corpo[:500] or "sem detalhes"
        super().__init__(f"HTTP {status}: {detalhe}")


def campo(d: dict, *nomes, padrao=None):
    """Lê um campo ignorando maiúsculas (Sefin usa camelCase, ADN usa PascalCase)."""
    if not isinstance(d, dict):
        return padrao
    baixo = {k.lower(): v for k, v in d.items()}
    for n in nomes:
        if n.lower() in baixo:
            return baixo[n.lower()]
    return padrao


def mensagens(lista) -> list[Mensagem]:
    if isinstance(lista, dict):
        lista = [lista]
    saida = []
    for m in lista or []:
        if isinstance(m, str):
            saida.append(Mensagem(descricao=m))
            continue
        saida.append(Mensagem(
            codigo=str(campo(m, "codigo", padrao="") or ""),
            descricao=str(campo(m, "descricao", "mensagem", padrao="") or ""),
            complemento=str(campo(m, "complemento", padrao="") or "")))
    return saida


def json_ou_erro(resp: requests.Response) -> dict:
    """Devolve o JSON de uma resposta 2xx; senão levanta ErroApi com as mensagens."""
    try:
        dados = resp.json() if resp.content else {}
    except (ValueError, json.JSONDecodeError):
        dados = None
    if resp.ok and isinstance(dados, (dict, list)):
        return dados
    msgs = []
    if isinstance(dados, dict):
        msgs = mensagens(campo(dados, "erros", "erro", padrao=[]))
        if not msgs and campo(dados, "mensagem", "title"):
            msgs = [Mensagem(descricao=str(campo(dados, "mensagem", "title")))]
    if resp.ok and dados is None:
        raise ErroApi(resp.status_code, [Mensagem(descricao="Resposta não é JSON")], resp.text)
    if not msgs and resp.status_code in (401, 403):
        msgs = [Mensagem(descricao="Acesso negado: o servidor não aceitou o certificado "
                         "(precisa ser ICP-Brasil, válido, do CNPJ da empresa).")]
    raise ErroApi(resp.status_code, msgs, resp.text)
