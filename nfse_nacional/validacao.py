"""Validação local contra os XSDs oficiais (pasta schemas/)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from lxml import etree

from .config import VERSAO_LEIAUTE, pasta_schemas

XS = "http://www.w3.org/2001/XMLSchema"


class ErroSchema(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("XML fora do schema:\n" + "\n".join(erros))


def _corrigir_padroes(doc: etree._ElementTree) -> None:
    """Os XSDs oficiais usam '^...$' em alguns xs:pattern (ex.: TSSerieDPS).

    Em regex de XML Schema '^' e '$' são caracteres literais (o validador .NET da
    Sefin os trata como âncoras, o libxml2 não). Como todo xs:pattern já é
    ancorado, removê-los preserva o significado pretendido.
    """
    for p in doc.iter(f"{{{XS}}}pattern"):
        v = p.get("value", "")
        nv = re.sub(r"^\^", "", v)
        nv = re.sub(r"(?<!\\)\$$", "", nv)
        if nv != v:
            p.set("value", nv)


class _Resolvedor(etree.Resolver):
    def __init__(self, pasta: Path):
        super().__init__()
        self.pasta = pasta

    def resolve(self, url, pubid, contexto):
        nome = Path(url.replace("file:///", "").replace("file://", "")).name
        caminho = self.pasta / nome
        if caminho.exists():
            return self.resolve_string(_xsd_corrigido(str(caminho)), contexto,
                                       base_url=caminho.as_uri())
        return None


@lru_cache(maxsize=None)
def _xsd_corrigido(caminho: str) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    doc = etree.parse(caminho, parser)
    _corrigir_padroes(doc)
    return etree.tostring(doc)


@lru_cache(maxsize=None)
def _schema(nome: str) -> etree.XMLSchema:
    pasta = pasta_schemas()
    parser = etree.XMLParser(no_network=True, load_dtd=False)
    parser.resolvers.add(_Resolvedor(pasta))
    raiz = etree.fromstring(_xsd_corrigido(str(pasta / nome)), parser,
                            base_url=(pasta / nome).as_uri())
    return etree.XMLSchema(etree.ElementTree(raiz))


def _validar(raiz: etree._Element, arquivo: str) -> None:
    schema = _schema(arquivo)
    if not schema.validate(raiz):
        erros = [f"linha {e.line}: {e.message}" for e in schema.error_log]
        raise ErroSchema(erros)


def validar_dps(raiz: etree._Element) -> None:
    _validar(raiz, f"DPS_v{VERSAO_LEIAUTE}.xsd")


def validar_ped_reg_evento(raiz: etree._Element) -> None:
    _validar(raiz, f"pedRegEvento_v{VERSAO_LEIAUTE}.xsd")


def validar_nfse(raiz: etree._Element) -> None:
    _validar(raiz, f"NFSe_v{VERSAO_LEIAUTE}.xsd")
