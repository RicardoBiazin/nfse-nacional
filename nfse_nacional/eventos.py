"""Pedido de Registro de Evento (pedRegEvento): cancelamento de NFS-e."""
from __future__ import annotations

import datetime as dt

from lxml import etree

from . import VERSAO
from .config import NS_NFSE, VERSAO_LEIAUTE
from .dps import agora_brasilia, so_digitos, texto

TIPO_CANCELAMENTO = "101101"
MOTIVOS_CANCELAMENTO = {
    "1": "Erro na Emissão",
    "2": "Serviço não Prestado",
    "9": "Outros",
}


def montar_id_ped_reg(chave: str, tipo_evento: str) -> str:
    # TSIdPedRegEvt: "PRE" + chave (50) + tipo (6). O nPedRegEvento saiu do Id em 2026.
    return f"PRE{chave}{tipo_evento}"


def _sub(pai, nome, valor=None):
    el = etree.SubElement(pai, f"{{{NS_NFSE}}}{nome}")
    if valor is not None:
        el.text = str(valor)
    return el


def pedido_cancelamento(chave: str, documento_autor: str, c_motivo: str, x_motivo: str,
                        tp_amb: str = "2", dh_evento: dt.datetime | None = None
                        ) -> etree._Element:
    if len(chave) != 50 or not chave.isdigit():
        raise ValueError("Chave de acesso deve ter 50 dígitos.")
    if c_motivo not in MOTIVOS_CANCELAMENTO:
        raise ValueError("Motivo de cancelamento deve ser 1, 2 ou 9.")
    x_motivo = texto(x_motivo)
    if not 15 <= len(x_motivo) <= 255:
        raise ValueError("A justificativa deve ter entre 15 e 255 caracteres.")

    raiz = etree.Element(f"{{{NS_NFSE}}}pedRegEvento", nsmap={None: NS_NFSE})
    raiz.set("versao", VERSAO_LEIAUTE)
    inf = _sub(raiz, "infPedReg")
    inf.set("Id", montar_id_ped_reg(chave, TIPO_CANCELAMENTO))
    _sub(inf, "tpAmb", tp_amb)
    _sub(inf, "verAplic", f"NFSE_Nacional {VERSAO}"[:20])
    _sub(inf, "dhEvento", (dh_evento or agora_brasilia()).isoformat(timespec="seconds"))
    doc = so_digitos(documento_autor)
    _sub(inf, "CNPJAutor" if len(doc) == 14 else "CPFAutor", doc)
    _sub(inf, "chNFSe", chave)
    ev = _sub(inf, f"e{TIPO_CANCELAMENTO}")
    _sub(ev, "xDesc", "Cancelamento de NFS-e")
    _sub(ev, "cMotivo", c_motivo)
    _sub(ev, "xMotivo", x_motivo)
    return raiz
