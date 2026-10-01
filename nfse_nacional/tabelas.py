"""Tabelas oficiais para descrever códigos: lista de serviços nacional, NBS e municípios IBGE.

Fontes (gov.br/nfse, documentação técnica): Anexo B (lista de serviços e NBS 2.0) e
Anexo A (municípios IBGE), gravados em recursos/*.csv no formato "código;descrição".
"""
from __future__ import annotations

from functools import lru_cache

from .config import pasta_base

UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


@lru_cache(maxsize=None)
def _ler(nome: str) -> dict[str, str]:
    try:
        with open(pasta_base() / "recursos" / nome, encoding="utf-8") as f:
            return dict(ln.rstrip("\r\n").split(";", 1) for ln in f if ";" in ln)
    except OSError:
        return {}


def servicos() -> dict[str, str]:
    """cTribNac (6 dígitos) -> descrição."""
    return _ler("servicos_nacionais.csv")


def nbs() -> dict[str, str]:
    """NBS (9 dígitos) -> descrição."""
    return _ler("nbs.csv")


@lru_cache(maxsize=None)
def municipios() -> dict[str, str]:
    """IBGE (7 dígitos) -> "Município / UF"."""
    return {c: f"{n} / {UF_POR_CODIGO[c[:2]]}" if c[:2] in UF_POR_CODIGO else n
            for c, n in _ler("municipios_ibge.csv").items()}


def nome_municipio(c_mun: str) -> str:
    if not c_mun:
        return ""
    return municipios().get(c_mun) or c_mun


def descrever(tabela: str, codigo: str) -> str:
    """Descrição do código, ou "" se não existir. tabela: servico | nbs | municipio."""
    fonte = {"servico": servicos, "nbs": nbs, "municipio": municipios}[tabela]()
    return fonte.get(codigo, "")
