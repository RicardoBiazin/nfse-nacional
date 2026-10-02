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

    # ------------------------------------------------------------ parâmetros municipais
    # Ficam no ADN (/parametrizacao), não na Sefin: os caminhos /parametros_municipais do
    # manual respondem 404 (conferido em 01/10/2026 com certificado real).
    def parametros_convenio(self, c_mun: str) -> dict:
        r = self.s.get(f"{self.base}/parametrizacao/{c_mun}/convenio", timeout=TIMEOUT)
        return json_ou_erro(r)

    def aliquotas(self, c_mun: str, c_trib_nac: str, c_trib_mun: str = "",
                  competencia: str = "") -> list[dict]:
        """Alíquotas do ISS do serviço no município. O código vai como "01.06.01.000"
        (tributação nacional + 3 dígitos da municipal, "000" se não houver)."""
        from urllib.parse import quote
        n = c_trib_nac.zfill(6)
        codigo = f"{n[:2]}.{n[2:4]}.{n[4:6]}.{(c_trib_mun or '000').zfill(3)}"
        url = f"{self.base}/parametrizacao/{c_mun}/{quote(codigo, safe='')}/{competencia}/aliquota"
        r = self.s.get(url, timeout=TIMEOUT)
        if r.status_code == 404:
            return []
        dados = json_ou_erro(r)
        return [a for lista in (campo(dados, "aliquotas", padrao=None) or {}).values() for a in lista]

    def eventos(self, chave: str) -> list[bytes]:
        r = self.s.get(f"{self.base}/contribuintes/NFSe/{chave}/Eventos", timeout=TIMEOUT)
        if r.status_code == 404:
            return []
        dados = json_ou_erro(r)
        itens = campo(dados, "LoteDFe", padrao=None) if isinstance(dados, dict) else dados
        return [de_gzip_b64(b) for it in (itens or [])
                if (b := campo(it, "ArquivoXml", "eventoXmlGZipB64"))]

    def danfse(self, chave: str) -> bytes:
        """PDF do DANFSe pelo ADN. API suspensa em 07/2026 (NT 008): responde 503.

        Mantido só para o caso de voltar; o app usa danfse.gerar_pdf().
        """
        r = self.s.get(f"{self.base}/danfse/{chave}", timeout=TIMEOUT,
                       headers={"Accept": "application/pdf"})
        if not r.ok or not r.content.startswith(b"%PDF"):
            json_ou_erro(r)   # levanta ErroApi com as mensagens se não for 2xx
            raise ErroApi(r.status_code, [Mensagem(descricao="DANFSe não retornou PDF")], r.text[:500])
        return r.content
