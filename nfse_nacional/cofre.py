"""Guarda do certificado: .pfx na pasta de dados com ACL restrita, senha no keyring."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

from .certificado import Certificado
from .config import pasta_dados

SERVICO_KEYRING = "NFSE_Nacional"


def _restringir_acl(caminho: Path):
    """Só o usuário atual lê o arquivo (no Windows a herança da pasta é larga)."""
    if os.name != "nt":
        os.chmod(caminho, 0o600)
        return
    usuario = os.environ.get("USERNAME", "")
    if not usuario:
        return
    subprocess.run(["icacls", str(caminho), "/inheritance:r",
                    "/grant:r", f"{usuario}:(R,W,D)"],
                   check=False, capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def importar_certificado(origem: str | os.PathLike, senha: str) -> tuple[Certificado, Path]:
    """Valida o .pfx, copia para a pasta de dados e guarda a senha no keyring."""
    cert = Certificado.de_arquivo(origem, senha)
    doc = cert.documento[1]
    if not doc:
        raise ValueError("Não encontrei CNPJ/CPF no certificado (não parece ICP-Brasil).")
    destino_dir = pasta_dados() / "certificados"
    destino_dir.mkdir(exist_ok=True)
    destino = destino_dir / f"{doc}.pfx"
    if Path(origem).resolve() != destino.resolve():
        shutil.copyfile(origem, destino)
    _restringir_acl(destino)
    keyring.set_password(SERVICO_KEYRING, doc, senha)
    return cert, destino


def senha_guardada(documento: str) -> str | None:
    return keyring.get_password(SERVICO_KEYRING, documento)


def esquecer_senha(documento: str):
    try:
        keyring.delete_password(SERVICO_KEYRING, documento)
    except PasswordDeleteError:
        pass


def abrir_certificado(caminho: str, documento: str, senha: str | None = None) -> Certificado:
    senha = senha if senha is not None else senha_guardada(documento)
    if senha is None:
        raise ValueError("Senha do certificado não encontrada no cofre. Reimporte o certificado.")
    return Certificado.de_arquivo(caminho, senha)
