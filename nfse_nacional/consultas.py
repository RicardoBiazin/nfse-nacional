"""Dados públicos de CNPJ (Receita Federal) e CEP para preencher o tomador.

Não usa o certificado nem fala com o governo da NFS-e: são APIs públicas e gratuitas.
    CNPJ: BrasilAPI (espelho da base da Receita); se falhar, CNPJ.ws.
    CEP:  ViaCEP; se falhar, BrasilAPI.
Para CPF não há fonte pública (LGPD): o tomador pessoa física continua digitado.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import requests

from . import VERSAO
from .dps import so_digitos

TEMPO = 12
CABECALHO = {"User-Agent": f"NFSE_Nacional/{VERSAO} (+https://github.com/RicardoBiazin/nfse-nacional)",
             "Accept": "application/json"}


class ErroConsulta(Exception):
    """CNPJ/CEP inexistente ou serviços fora do ar (mensagem pronta para a tela)."""


@dataclass
class Endereco:
    cep: str = ""
    logradouro: str = ""
    complemento: str = ""
    bairro: str = ""
    c_mun: str = ""          # IBGE, 7 dígitos
    municipio: str = ""      # "Florianópolis / SC"


@dataclass
class Cadastro:
    documento: str
    nome: str = ""
    fantasia: str = ""
    situacao: str = ""       # ATIVA, BAIXADA, INAPTA...
    email: str = ""
    fone: str = ""
    numero: str = ""
    endereco: Endereco | None = None
    fonte: str = ""


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").upper().strip()


def _get(url: str, sessao=None) -> requests.Response:
    return (sessao or requests).get(url, headers=CABECALHO, timeout=TEMPO)


def _ibge_por_nome(cidade: str, uf: str) -> str:
    """Código IBGE a partir de "cidade" + UF (para fontes que não trazem o código)."""
    from .tabelas import municipios
    alvo = f"{_sem_acento(cidade)} / {uf.upper()}"
    for codigo, nome in municipios().items():
        if _sem_acento(nome) == alvo:
            return codigo
    return ""


def _municipio(c_mun: str) -> str:
    from .tabelas import nome_municipio
    return nome_municipio(c_mun) if c_mun else ""


# ------------------------------------------------------------------ CEP

def _cep_viacep(cep: str, sessao=None) -> Endereco | None:
    r = _get(f"https://viacep.com.br/ws/{cep}/json/", sessao)
    if r.status_code == 400:
        return None
    r.raise_for_status()
    d = r.json()
    if d.get("erro"):
        return None
    c_mun = so_digitos(str(d.get("ibge") or ""))
    return Endereco(cep=cep, logradouro=d.get("logradouro") or "", complemento="",
                    bairro=d.get("bairro") or "", c_mun=c_mun, municipio=_municipio(c_mun))


def _cep_brasilapi(cep: str, sessao=None) -> Endereco | None:
    r = _get(f"https://brasilapi.com.br/api/cep/v2/{cep}", sessao)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    c_mun = so_digitos(str((d.get("ibge") or {}).get("city") or "")) if isinstance(d.get("ibge"), dict) \
        else ""
    c_mun = c_mun or _ibge_por_nome(d.get("city") or "", d.get("state") or "")
    return Endereco(cep=cep, logradouro=d.get("street") or "", bairro=d.get("neighborhood") or "",
                    c_mun=c_mun, municipio=_municipio(c_mun))


def consultar_cep(cep: str, sessao=None) -> Endereco:
    cep = so_digitos(cep)
    if len(cep) != 8:
        raise ErroConsulta("CEP precisa ter 8 dígitos.")
    falhas = []
    for fonte in (_cep_viacep, _cep_brasilapi):
        try:
            end = fonte(cep, sessao)
        except (requests.RequestException, ValueError) as erro:
            falhas.append(str(erro))
            continue
        if end is None:
            raise ErroConsulta(f"CEP {cep[:5]}-{cep[5:]} não encontrado.")
        return end
    raise ErroConsulta("Não consegui consultar o CEP agora (sem internet ou serviço fora do ar).\n"
                       + "\n".join(falhas))


# ------------------------------------------------------------------ CNPJ

def _logradouro(tipo: str, nome: str) -> str:
    tipo, nome = (tipo or "").strip(), (nome or "").strip()
    if tipo and not _sem_acento(nome).startswith(_sem_acento(tipo) + " "):
        return f"{tipo} {nome}".strip()
    return nome


def _cnpj_brasilapi(cnpj: str, sessao=None) -> Cadastro | None:
    r = _get(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}", sessao)
    if r.status_code in (400, 404):
        return None
    r.raise_for_status()
    d = r.json()
    c_mun = so_digitos(str(d.get("codigo_municipio_ibge") or "")) or \
        _ibge_por_nome(d.get("municipio") or "", d.get("uf") or "")
    fone = so_digitos(d.get("ddd_telefone_1") or "")
    return Cadastro(
        documento=cnpj, nome=(d.get("razao_social") or "").strip(),
        fantasia=(d.get("nome_fantasia") or "").strip(),
        situacao=(d.get("descricao_situacao_cadastral") or "").upper(),
        email=(d.get("email") or "").strip().lower(), fone=fone, numero=(d.get("numero") or "").strip(),
        endereco=Endereco(cep=so_digitos(d.get("cep") or ""),
                          logradouro=_logradouro(d.get("descricao_tipo_de_logradouro"), d.get("logradouro")),
                          complemento=(d.get("complemento") or "").strip(),
                          bairro=(d.get("bairro") or "").strip(), c_mun=c_mun, municipio=_municipio(c_mun)),
        fonte="BrasilAPI (Receita Federal)")


def _cnpj_cnpjws(cnpj: str, sessao=None) -> Cadastro | None:
    r = _get(f"https://publica.cnpj.ws/cnpj/{cnpj}", sessao)
    if r.status_code in (400, 404):
        return None
    r.raise_for_status()
    d = r.json()
    e = d.get("estabelecimento") or {}
    cidade = e.get("cidade") or {}
    c_mun = so_digitos(str(cidade.get("ibge_id") or "")) or \
        _ibge_por_nome(cidade.get("nome") or "", (e.get("estado") or {}).get("sigla") or "")
    return Cadastro(
        documento=cnpj, nome=(d.get("razao_social") or "").strip(),
        fantasia=(e.get("nome_fantasia") or "").strip(),
        situacao=(e.get("situacao_cadastral") or "").upper(),
        email=(e.get("email") or "").strip().lower(),
        fone=so_digitos(f"{e.get('ddd1') or ''}{e.get('telefone1') or ''}"),
        numero=(e.get("numero") or "").strip(),
        endereco=Endereco(cep=so_digitos(e.get("cep") or ""),
                          logradouro=_logradouro(e.get("tipo_logradouro"), e.get("logradouro")),
                          complemento=(e.get("complemento") or "").strip(),
                          bairro=(e.get("bairro") or "").strip(), c_mun=c_mun, municipio=_municipio(c_mun)),
        fonte="CNPJ.ws (Receita Federal)")


def _acentuar(cad: Cadastro, sessao=None):
    """A Receita grava tudo em maiúsculas sem acento; se o CEP trouxer a mesma rua escrita
    direito ("Rua Emílio Blum"), usa a grafia do CEP."""
    end = cad.endereco
    if not end or len(end.cep) != 8:
        return
    try:
        pelo_cep = _cep_viacep(end.cep, sessao)
    except (requests.RequestException, ValueError):
        return
    if not pelo_cep:
        return
    if pelo_cep.logradouro and _sem_acento(end.logradouro) in _sem_acento(pelo_cep.logradouro):
        end.logradouro = pelo_cep.logradouro
    if pelo_cep.bairro and _sem_acento(end.bairro) == _sem_acento(pelo_cep.bairro):
        end.bairro = pelo_cep.bairro
    if not end.c_mun and pelo_cep.c_mun:
        end.c_mun, end.municipio = pelo_cep.c_mun, pelo_cep.municipio


def cnpj_valido(cnpj: str) -> bool:
    cnpj = so_digitos(cnpj)
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    for tam in (12, 13):
        pesos = list(range(tam - 7, 1, -1)) + list(range(9, 1, -1))
        dv = sum(int(c) * p for c, p in zip(cnpj[:tam], pesos)) % 11
        if int(cnpj[tam]) != (0 if dv < 2 else 11 - dv):
            return False
    return True


def consultar_cnpj(cnpj: str, sessao=None) -> Cadastro:
    cnpj = so_digitos(cnpj)
    if not cnpj_valido(cnpj):
        raise ErroConsulta("CNPJ inválido (confira os dígitos).")
    falhas = []
    for fonte in (_cnpj_brasilapi, _cnpj_cnpjws):
        try:
            cad = fonte(cnpj, sessao)
        except (requests.RequestException, ValueError) as erro:
            falhas.append(str(erro))
            continue
        if cad is None:
            raise ErroConsulta(f"CNPJ {cnpj} não encontrado na base da Receita.")
        _acentuar(cad, sessao)
        return cad
    raise ErroConsulta("Não consegui consultar o CNPJ agora (sem internet ou serviço fora do ar).\n"
                       + "\n".join(falhas))
