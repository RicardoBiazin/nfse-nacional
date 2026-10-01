"""API do ADN (Ambiente de Dados Nacional) para contribuintes: distribuição e DANFSe."""
from __future__ import annotations

from dataclasses import dataclass, field

import requests

from .cliente_http import TIMEOUT, ErroApi, Mensagem, campo, json_ou_erro, mensagens
from .compactacao import de_gzip_b64
from .config import Ambiente


@dataclass
class DocumentoDistribuido:
    nsu: int
    chave: str
    tipo: str          # "NFSE", "EVENTO", ...
    xml: bytes
    dh_geracao: str = ""


@dataclass
class LoteDistribuicao:
    documentos: list[DocumentoDistribuido]
    ultimo_nsu: int | None = None
    maior_nsu: int | None = None
    status: str = ""
    alertas: list[Mensagem] = field(default_factory=list)


class ClienteADN:
    def __init__(self, sessao: requests.Session, ambiente: Ambiente):
        self.s = sessao
        self.base = ambiente.adn.rstrip("/")

    def distribuicao(self, nsu: int, cnpj_consulta: str | None = None,
                     lote: bool = True) -> LoteDistribuicao:
        """GET /contribuintes/DFe/{NSU}: documentos a partir do NSU (até 50 em lote)."""
        params = {"lote": "true" if lote else "false"}
        if cnpj_consulta:
            params["cnpjConsulta"] = cnpj_consulta
        r = self.s.get(f"{self.base}/contribuintes/DFe/{nsu}", params=params, timeout=TIMEOUT)
        if r.status_code == 404:
            # "Nenhum documento localizado" chega como 404 com corpo JSON.
            try:
                dados = r.json()
            except ValueError:
                dados = {}
            return LoteDistribuicao([], status=str(campo(dados, "StatusProcessamento", padrao="")),
                                    alertas=mensagens(campo(dados, "Alertas", padrao=[])))
        dados = json_ou_erro(r)
        erros = mensagens(campo(dados, "Erros", padrao=[]))
        if erros:
            raise ErroApi(r.status_code, erros, r.text)
        docs = []
        for it in campo(dados, "LoteDFe", padrao=[]) or []:
            b64 = campo(it, "ArquivoXml", "dfeXmlGZipB64")
            if not b64:
                continue
            docs.append(DocumentoDistribuido(
                nsu=int(campo(it, "NSU")),
                chave=str(campo(it, "ChaveAcesso", padrao="") or ""),
                tipo=str(campo(it, "TipoDocumento", padrao="") or ""),
                xml=de_gzip_b64(b64),
                dh_geracao=str(campo(it, "DataHoraGeracao", padrao="") or "")))
        ult = campo(dados, "UltimoNSU")
        maior = campo(dados, "MaiorNSU")
        return LoteDistribuicao(
            docs,
            ultimo_nsu=int(ult) if ult not in (None, "") else (max((d.nsu for d in docs), default=None)),
            maior_nsu=int(maior) if maior not in (None, "") else None,
            status=str(campo(dados, "StatusProcessamento", padrao="")),
            alertas=mensagens(campo(dados, "Alertas", padrao=[])))

    def eventos(self, chave: str) -> list[bytes]:
        r = self.s.get(f"{self.base}/contribuintes/NFSe/{chave}/Eventos", timeout=TIMEOUT)
        if r.status_code == 404:
            return []
        dados = json_ou_erro(r)
        itens = campo(dados, "LoteDFe", padrao=None) if isinstance(dados, dict) else dados
        return [de_gzip_b64(b) for it in (itens or [])
                if (b := campo(it, "ArquivoXml", "eventoXmlGZipB64"))]

    def danfse(self, chave: str) -> bytes:
        """PDF do DANFSe gerado pelo ADN."""
        r = self.s.get(f"{self.base}/danfse/{chave}", timeout=TIMEOUT,
                       headers={"Accept": "application/pdf"})
        if not r.ok or not r.content.startswith(b"%PDF"):
            json_ou_erro(r)   # levanta ErroApi com as mensagens se não for 2xx
            raise ErroApi(r.status_code, [Mensagem(descricao="DANFSe não retornou PDF")], r.text[:500])
        return r.content
