"""Ambientes, caminhos e constantes do Sistema Nacional NFS-e."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Versão do leiaute da DPS/pedRegEvento. A 1.01 é a primeira que aceita o
# grupo IBSCBS (RN E0854); os XSDs da pasta schemas/ são os desta versão.
VERSAO_LEIAUTE = "1.01"

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"


@dataclass(frozen=True)
class Ambiente:
    nome: str
    tp_amb: str          # 1 = Produção, 2 = Homologação (Produção Restrita)
    sefin: str
    adn: str


PRODUCAO_RESTRITA = Ambiente(
    nome="producao_restrita", tp_amb="2",
    sefin="https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    adn="https://adn.producaorestrita.nfse.gov.br",
)
PRODUCAO = Ambiente(
    nome="producao", tp_amb="1",
    sefin="https://sefin.nfse.gov.br/SefinNacional",
    adn="https://adn.nfse.gov.br",
)
AMBIENTES = {a.nome: a for a in (PRODUCAO_RESTRITA, PRODUCAO)}


def ambiente(nome: str) -> Ambiente:
    try:
        return AMBIENTES[nome]
    except KeyError:
        raise ValueError(f"Ambiente desconhecido: {nome!r}") from None


def pasta_base() -> Path:
    """Raiz do projeto (ou do bundle do PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def pasta_schemas() -> Path:
    return pasta_base() / "schemas"


def pasta_dados() -> Path:
    """Banco, certificados e XMLs do usuário. NFSE_NACIONAL_DADOS sobrepõe (testes)."""
    alvo = os.environ.get("NFSE_NACIONAL_DADOS")
    if alvo:
        p = Path(alvo)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        p = Path(base) / "NFSE_Nacional"
    p.mkdir(parents=True, exist_ok=True)
    return p
