"""API da Sefin Nacional: emissão (DPS), consultas e eventos."""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .cliente_http import (TIMEOUT, ErroApi, Mensagem, campo, json_ou_erro,
                           mensagens)
from .compactacao import de_gzip_b64, para_gzip_b64
from .config import Ambiente


@dataclass
class RespostaEmissao:
    chave: str
    id_dps: str
    nfse_xml: bytes
    alertas: list[Mensagem] = field(default_factory=list)


class ClienteSefin:
    def __init__(self, sessao: requests.Session, ambiente: Ambiente):
        self.s = sessao
        self.base = ambiente.sefin.rstrip("/")

    def _url(self, caminho: str) -> str:
        return f"{self.base}/{caminho.lstrip('/')}"

    # ------------------------------------------------------------ NFS-e
    def emitir(self, dps_assinada: bytes) -> RespostaEmissao:
        """POST /nfse. Exceções de rede sobem: o chamador decide consultar a DPS."""
        r = self.s.post(self._url("nfse"), json={"dpsXmlGZipB64": para_gzip_b64(dps_assinada)},
                        timeout=TIMEOUT)
        dados = json_ou_erro(r)
        erros = mensagens(campo(dados, "erros", padrao=[]))
        b64 = campo(dados, "nfseXmlGZipB64")
        if erros or not b64:
            raise ErroApi(r.status_code, erros or [Mensagem(descricao="Resposta sem NFS-e")], r.text)
        return RespostaEmissao(
            chave=campo(dados, "chaveAcesso", padrao=""),
            id_dps=campo(dados, "idDps", padrao=""),
            nfse_xml=de_gzip_b64(b64),
            alertas=mensagens(campo(dados, "alertas", padrao=[])))

    def consultar_nfse(self, chave: str) -> bytes:
        dados = json_ou_erro(self.s.get(self._url(f"nfse/{chave}"), timeout=TIMEOUT))
        return de_gzip_b64(campo(dados, "nfseXmlGZipB64"))

    # ------------------------------------------------------------ DPS
    def chave_por_dps(self, id_dps: str) -> str | None:
        """GET /dps/{id}: chave da NFS-e gerada pela DPS, ou None se não houver."""
        r = self.s.get(self._url(f"dps/{id_dps}"), timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        return campo(json_ou_erro(r), "chaveAcesso") or None

    def dps_existe(self, id_dps: str) -> bool:
        r = self.s.head(self._url(f"dps/{id_dps}"), timeout=TIMEOUT)
        if r.status_code == 404:
            return False
        if r.ok:
            return True
        raise ErroApi(r.status_code, [], r.text)

    # ------------------------------------------------------------ eventos
    def registrar_evento(self, chave: str, pedido_assinado: bytes) -> bytes:
        r = self.s.post(self._url(f"nfse/{chave}/eventos"),
                        json={"pedidoRegistroEventoXmlGZipB64": para_gzip_b64(pedido_assinado)},
                        timeout=TIMEOUT)
        dados = json_ou_erro(r)
        erros = mensagens(campo(dados, "erros", padrao=[]))
        b64 = campo(dados, "eventoXmlGZipB64")
        if erros or not b64:
            raise ErroApi(r.status_code, erros or [Mensagem(descricao="Resposta sem evento")], r.text)
        return de_gzip_b64(b64)

    def eventos(self, chave: str, tipo: str | None = None) -> list[bytes]:
        caminho = f"nfse/{chave}/eventos" + (f"/{tipo}" if tipo else "")
        r = self.s.get(self._url(caminho), timeout=TIMEOUT)
        if r.status_code == 404:
            return []
        dados = json_ou_erro(r)
        itens = dados if isinstance(dados, list) else (
            campo(dados, "eventos", padrao=None) or [dados])
        saida = []
        for it in itens:
            b64 = campo(it, "eventoXmlGZipB64", "arquivoXml")
            if b64:
                saida.append(de_gzip_b64(b64))
        return saida
