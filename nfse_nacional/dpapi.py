"""DPAPI do Windows (CryptProtectData) via ctypes, escopo da MÁQUINA.

Usado no modo servidor: o serviço roda com outra conta e não enxerga o keyring (Cofre de
Credenciais) de quem importou o certificado. Com escopo de máquina, qualquer processo deste
computador decifra — por isso o servidor deve ser uma máquina de confiança, e o segredo
cifrado não serve em outro computador (copiar o banco não vaza a senha).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x1
CRYPTPROTECT_LOCAL_MACHINE = 0x4
_ENTROPIA = b"NFSE_Nacional/certificados"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def disponivel() -> bool:
    return sys.platform == "win32"


def _blob(dados: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(dados, len(dados))
    return _Blob(len(dados), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _bytes(b: _Blob) -> bytes:
    try:
        return ctypes.string_at(b.pbData, b.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(b.pbData)


def cifrar(dados: bytes) -> bytes:
    if not disponivel():
        raise OSError("DPAPI só existe no Windows.")
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(entrada), "NFSE_Nacional", ctypes.byref(entropia), None, None,
        CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE, ctypes.byref(saida))
    if not ok:
        raise ctypes.WinError()
    return _bytes(saida)


def decifrar(dados: bytes) -> bytes:
    if not disponivel():
        raise OSError("DPAPI só existe no Windows.")
    entrada, entropia, saida = _blob(dados), _blob(_ENTROPIA), _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(saida))
    if not ok:
        raise ctypes.WinError()
    return _bytes(saida)
