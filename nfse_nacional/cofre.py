"""Guarda dos certificados: .pfx na pasta de dados com ACL restrita, senha no keyring.

Uma empresa pode ter vários certificados (renovação, matriz/filial com o mesmo CNPJ raiz).
Um é o principal; se ele vencer, o app usa o válido com maior validade.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from pathlib import Path

import keyring
from keyring.errors import PasswordDeleteError

from .certificado import Certificado
from .config import pasta_dados

SERVICO_KEYRING = "NFSE_Nacional"

# Onde ficam as senhas dos certificados:
#   None  -> keyring do usuário do Windows (desktop)
#   Banco -> tabela `segredos`, cifrada com DPAPI de máquina (servidor web / serviço)
_BANCO_SEGREDOS = None


def usar_cofre_do_servidor(banco):
    """Modo servidor: senhas no banco, cifradas com DPAPI (o serviço não vê o keyring)."""
    global _BANCO_SEGREDOS
    _BANCO_SEGREDOS = banco


def usar_keyring():
    global _BANCO_SEGREDOS
    _BANCO_SEGREDOS = None


def _guardar(chave: str, senha: str):
    if _BANCO_SEGREDOS is not None:
        from . import dpapi
        _BANCO_SEGREDOS.gravar_segredo(chave, dpapi.cifrar(senha.encode("utf-8")))
    else:
        keyring.set_password(SERVICO_KEYRING, chave, senha)


def guardar_senha(chave: str, senha: str):
    """Outras senhas do app (ex.: SMTP, chave "smtp:<empresa_id>") no mesmo cofre."""
    _guardar(chave, senha)


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


def chave_cofre(cert: Certificado) -> str:
    """Usuário do keyring: documento + número de série (um registro por certificado)."""
    return f"{cert.documento[1]}:{cert.cert.serial_number:x}"


def importar_certificado(origem: str | os.PathLike, senha: str) -> tuple[Certificado, Path]:
    """Valida o .pfx, copia para a pasta de dados e guarda a senha no keyring."""
    cert = Certificado.de_arquivo(origem, senha)
    doc = cert.documento[1]
    if not doc:
        raise ValueError("Não encontrei CNPJ/CPF no certificado (não parece ICP-Brasil).")
    destino_dir = pasta_dados() / "certificados"
    destino_dir.mkdir(exist_ok=True)
    destino = destino_dir / f"{doc}_{cert.cert.serial_number:x}.pfx"
    if Path(origem).resolve() != destino.resolve():
        shutil.copyfile(origem, destino)
    if _BANCO_SEGREDOS is None:
        _restringir_acl(destino)        # no servidor a pasta inteira já é protegida
    _guardar(chave_cofre(cert), senha)
    return cert, destino


def senha_guardada(chave: str) -> str | None:
    if _BANCO_SEGREDOS is not None:
        from . import dpapi
        cifrado = _BANCO_SEGREDOS.ler_segredo(chave)
        if cifrado is not None:
            return dpapi.decifrar(cifrado).decode("utf-8")
        # Certificado importado antes pelo desktop neste mesmo usuário: tenta o keyring.
        try:
            return keyring.get_password(SERVICO_KEYRING, chave)
        except Exception:      # noqa: BLE001 - serviço sem keyring utilizável
            return None
    return keyring.get_password(SERVICO_KEYRING, chave)


def esquecer_senha(chave: str):
    if _BANCO_SEGREDOS is not None:
        _BANCO_SEGREDOS.apagar_segredo(chave)
    try:
        keyring.delete_password(SERVICO_KEYRING, chave)
    except PasswordDeleteError:
        pass


def abrir_certificado(caminho: str, chave: str, senha: str | None = None) -> Certificado:
    senha = senha if senha is not None else senha_guardada(chave)
    if senha is None:
        raise ValueError("Senha do certificado não encontrada no cofre. Reimporte o certificado.")
    return Certificado.de_arquivo(caminho, senha)


# ------------------------------------------------------------------ vários por empresa

def _raiz(doc: str) -> str:
    return doc[:8] if len(doc) == 14 else doc


def adicionar_a_empresa(banco, empresa, origem: str | os.PathLike, senha: str,
                        principal: bool = False) -> tuple[Certificado, int]:
    """Importa um certificado para a empresa. Aceita o mesmo CNPJ ou o mesmo CNPJ raiz."""
    cert = Certificado.de_arquivo(origem, senha)
    doc = cert.documento[1]
    if empresa.cnpj and _raiz(doc) != _raiz(empresa.cnpj):
        raise ValueError(f"O certificado é do documento {doc}, que não pertence à empresa "
                         f"{empresa.cnpj} (precisa ser o mesmo CNPJ ou o mesmo CNPJ raiz).")
    cert, destino = importar_certificado(origem, senha)
    id_ = banco.adicionar_certificado(
        empresa.id, str(destino), chave_cofre(cert), doc, cert.titular,
        f"{cert.cert.serial_number:x}", cert.validade.isoformat())
    if principal:
        banco.definir_certificado_principal(empresa.id, id_)
    return cert, id_


def migrar_certificado_antigo(banco, empresa):
    """Até a 0.3.0 havia um certificado por empresa (empresas.cert_arquivo, senha no keyring
    sob o CNPJ). Registra-o na tabela de certificados com a nova chave."""
    if not empresa.cert_arquivo or banco.certificados(empresa.id):
        return
    senha = senha_guardada(empresa.cnpj)
    if senha is None or not Path(empresa.cert_arquivo).exists():
        return
    try:
        cert = Certificado.de_arquivo(empresa.cert_arquivo, senha)
    except Exception:      # noqa: BLE001 - deixa o usuário reimportar
        return
    _guardar(chave_cofre(cert), senha)
    banco.adicionar_certificado(empresa.id, empresa.cert_arquivo, chave_cofre(cert),
                                cert.documento[1], cert.titular,
                                f"{cert.cert.serial_number:x}", cert.validade.isoformat())


def remover_da_empresa(banco, empresa, cert_id: int):
    linha = next((r for r in banco.certificados(empresa.id) if r["id"] == cert_id), None)
    if not linha:
        return
    banco.remover_certificado(empresa.id, cert_id)
    esquecer_senha(linha["chave_cofre"])
    usado = any(r["arquivo"] == linha["arquivo"] for e in banco.empresas()
                for r in banco.certificados(e.id))
    if not usado:
        try:
            os.remove(linha["arquivo"])
        except OSError:
            pass


def _vencido(validade_iso: str) -> bool:
    try:
        return dt.datetime.fromisoformat(validade_iso) < dt.datetime.now(dt.timezone.utc)
    except ValueError:
        return False


def certificado_ativo(banco, empresa) -> Certificado:
    """O principal; se estiver vencido, o válido com maior validade."""
    migrar_certificado_antigo(banco, empresa)
    linhas = banco.certificados(empresa.id)
    if not linhas:
        raise ValueError("A empresa não tem certificado. Importe um em 'Configurar empresa'.")
    validos = [r for r in linhas if not _vencido(r["validade"])]
    if not validos:
        raise ValueError("Todos os certificados da empresa estão vencidos. Importe um novo.")
    principal = next((r for r in validos if r["principal"]), None)
    escolhido = principal or max(validos, key=lambda r: r["validade"])
    return abrir_certificado(escolhido["arquivo"], escolhido["chave_cofre"])
