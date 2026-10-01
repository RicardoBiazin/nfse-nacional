"""XML <-> GZip + Base64, o formato dos campos *XmlGZipB64 da API."""
from __future__ import annotations

import base64
import gzip


def para_gzip_b64(xml: bytes | str) -> str:
    if isinstance(xml, str):
        xml = xml.encode("utf-8")
    return base64.b64encode(gzip.compress(xml)).decode("ascii")


def de_gzip_b64(dado: str) -> bytes:
    bruto = base64.b64decode(dado)
    # Alguns retornos vêm só em Base64, sem GZip; o cabeçalho 1f 8b decide.
    if bruto[:2] == b"\x1f\x8b":
        return gzip.decompress(bruto)
    return bruto
