"""Leitura dos XMLs devolvidos pelo sistema (NFS-e e eventos) para resumos."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from lxml import etree

from .config import NS_NFSE

N = {"n": NS_NFSE}


@dataclass
class ResumoNFSe:
    chave: str
    numero: str
    dh_proc: str
    d_compet: str
    id_dps: str
    emitente_doc: str
    emitente_nome: str
    tomador_doc: str
    tomador_nome: str
    descricao: str
    v_serv: Decimal
    v_liq: Decimal
    v_issqn: Decimal | None
    c_stat: str
    municipio: str


@dataclass
class ResumoEvento:
    chave: str
    tipo: str           # ex.: "101101"
    descricao: str
    dh_proc: str


def _parse(xml: bytes | str | etree._Element) -> etree._Element:
    if isinstance(xml, etree._Element):
        return xml
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))


def _t(el, caminho: str) -> str:
    return (el.findtext(caminho, namespaces=N) or "").strip() if el is not None else ""


def _doc(el) -> str:
    if el is None:
        return ""
    return _t(el, "n:CNPJ") or _t(el, "n:CPF") or _t(el, "n:NIF")


def tipo_documento(xml) -> str:
    """'NFSe', 'evento' ou o nome local da raiz."""
    return etree.QName(_parse(xml)).localname


def ler_nfse(xml) -> ResumoNFSe:
    raiz = _parse(xml)
    inf = raiz.find("n:infNFSe", N)
    if inf is None:
        raise ValueError("XML não é uma NFS-e (infNFSe ausente).")
    inf_dps = inf.find("n:DPS/n:infDPS", N)
    toma = inf_dps.find("n:toma", N) if inf_dps is not None else None
    emit = inf.find("n:emit", N)
    v_iss = _t(inf, "n:valores/n:vISSQN")
    return ResumoNFSe(
        chave=inf.get("Id", "")[3:],
        numero=_t(inf, "n:nNFSe"),
        dh_proc=_t(inf, "n:dhProc"),
        d_compet=_t(inf_dps, "n:dCompet"),
        id_dps=inf_dps.get("Id", "") if inf_dps is not None else "",
        emitente_doc=_doc(emit),
        emitente_nome=_t(emit, "n:xNome"),
        tomador_doc=_doc(toma),
        tomador_nome=_t(toma, "n:xNome"),
        descricao=_t(inf_dps, "n:serv/n:cServ/n:xDescServ"),
        v_serv=Decimal(_t(inf_dps, "n:valores/n:vServPrest/n:vServ") or "0"),
        v_liq=Decimal(_t(inf, "n:valores/n:vLiq") or "0"),
        v_issqn=Decimal(v_iss) if v_iss else None,
        c_stat=_t(inf, "n:cStat"),
        municipio=_t(inf, "n:xLocEmi"),
    )


def ler_evento(xml) -> ResumoEvento:
    raiz = _parse(xml)
    inf_ped = raiz.find(".//n:infPedReg", N)
    if inf_ped is None:
        raise ValueError("XML não é um evento de NFS-e.")
    tipo, desc = "", ""
    for filho in inf_ped:
        nome = etree.QName(filho).localname
        if len(nome) == 7 and nome.startswith("e") and nome[1:].isdigit():
            tipo, desc = nome[1:], _t(filho, "n:xDesc")
    return ResumoEvento(
        chave=_t(inf_ped, "n:chNFSe"), tipo=tipo, descricao=desc,
        dh_proc=_t(raiz, ".//n:infEvento/n:dhProc") or _t(inf_ped, "n:dhEvento"))


def chaves_em_pdf(pdf: bytes) -> list[str]:
    """Chaves de acesso (50 dígitos) encontradas no texto de um DANFSe em PDF."""
    import io
    import re

    from pypdf import PdfReader

    from .tabelas import UF_POR_CODIGO
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    # 1º: a chave inteira, isolada (DANFSe do app e do portal).
    achadas = re.findall(r"(?<!\d)\d{50}(?!\d)", texto)
    if not achadas:
        # PDFs de outros sistemas às vezes quebram a chave com espaços (blocos de 4).
        for bloco in re.findall(r"(?<![\d])(?:\d{4}\s){12}\d{2}(?![\d])", texto):
            achadas.append(re.sub(r"\s", "", bloco))
    chaves: list[str] = []
    for c in achadas:
        # Chave de NFS-e começa pelo código IBGE do município emissor.
        if c[:2] in UF_POR_CODIGO and c not in chaves:
            chaves.append(c)
    return chaves
