"""Servidor web interno da NFS-e Nacional.

    NFSE_Servidor.exe rodar [--porta 8443] [--sem-https]
    NFSE_Servidor.exe importar-dados-desktop      (traz banco, certificados e senhas do app desktop)
    NFSE_Servidor.exe instalar-servico [--porta 8443]   (como administrador: inicia com o Windows)
    NFSE_Servidor.exe remover-servico
    NFSE_Servidor.exe criar-admin LOGIN           (redefine/cria administrador pelo terminal)

Dados em C:\\ProgramData\\NFSE_Nacional (variável NFSE_NACIONAL_DADOS muda).
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import ipaddress
import logging
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

PASTA_SERVIDOR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "NFSE_Nacional"

from nfse_nacional import VERSAO, cofre  # noqa: E402
from nfse_nacional.banco import Banco  # noqa: E402
from nfse_nacional.config import pasta_dados  # noqa: E402

NOME_TAREFA = "NFSE_Nacional Servidor"
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
log = logging.getLogger("nfse.servidor")


def _cmd(*args) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), capture_output=True, text=True, creationflags=SEM_JANELA)


def _proteger_pasta(p: Path):
    """Só SYSTEM e Administradores acessam a pasta do servidor (banco, .pfx, chave HTTPS)."""
    if os.name == "nt":
        concessoes = ["*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
        usuario = os.environ.get("USERNAME", "")
        if usuario and not usuario.endswith("$"):      # rodando no terminal de um usuário
            concessoes.append(f"{usuario}:(OI)(CI)F")
        _cmd("icacls", str(p), "/inheritance:r", "/grant:r", *concessoes)


def _executavel() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


# ------------------------------------------------------------------ HTTPS autoassinado

def _nomes_e_ips() -> tuple[set[str], set[str]]:
    host = socket.gethostname()
    nomes = {host, host.lower(), "localhost"}
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(host)[2])
    except OSError:
        pass
    return nomes, ips


def _autoridade(pasta: Path):
    """Autoridade certificadora própria do servidor (ca.crt é o que cada PC passa a confiar).

    Um certificado autoassinado direto faz o Chrome/Edge mostrar "Sua conexão não é
    particular" (CertificateAuthorityInvalid) e, com políticas de empresa, nem deixa seguir.
    Com uma AC local instalada em "Autoridades de Certificação Raiz Confiáveis", o site abre
    com cadeado. A chave da AC fica só na pasta protegida do servidor.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    ca_crt, ca_key = pasta / "ca.crt", pasta / "ca.key"
    if ca_crt.exists() and ca_key.exists():
        return (x509.load_pem_x509_certificate(ca_crt.read_bytes()),
                serialization.load_pem_private_key(ca_key.read_bytes(), None))
    chave = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                         f"NFS-e Nacional - AC local de {socket.gethostname()}"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NFS-e Nacional (uso interno)")])
    agora = dt.datetime.now(dt.timezone.utc)
    ski = x509.SubjectKeyIdentifier.from_public_key(chave.public_key())
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(days=1)).not_valid_after(agora + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(ski, critical=False)
            .sign(chave, hashes.SHA256()))
    ca_key.write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    ca_crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, chave


def _precisa_renovar(crt: Path, ca_crt: Path) -> bool:
    """Novo certificado se não existe, não foi emitido pela AC atual, vence em 30 dias ou
    não cobre mais o nome/IP desta máquina (IP mudou)."""
    from cryptography import x509
    if not crt.exists():
        return True
    try:
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        ca = x509.load_pem_x509_certificate(ca_crt.read_bytes())
    except (OSError, ValueError):
        return True
    if cert.issuer != ca.subject:
        return True
    if cert.not_valid_after_utc - dt.datetime.now(dt.timezone.utc) < dt.timedelta(days=30):
        return True
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return True
    nomes, ips = _nomes_e_ips()
    tem_nomes = set(san.get_values_for_type(x509.DNSName))
    tem_ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    return not (nomes <= tem_nomes and ips <= tem_ips)


def certificado_https(pasta: Path) -> tuple[Path, Path]:
    """(servidor.crt, servidor.key) assinados pela AC local; renova sozinho quando preciso."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    pasta.mkdir(parents=True, exist_ok=True)
    ca, ca_chave = _autoridade(pasta)
    crt, key = pasta / "servidor.crt", pasta / "servidor.key"
    if not _precisa_renovar(crt, pasta / "ca.crt") and key.exists():
        return crt, key
    nomes, ips = _nomes_e_ips()
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agora = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName(n) for n in sorted(nomes)] + \
        [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, socket.gethostname())]))
            .issuer_name(ca.subject).public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=True, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_chave.public_key()),
                           critical=False)
            .sign(ca_chave, hashes.SHA256()))
    key.write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    # cadeia: certificado do servidor + AC (o navegador recebe as duas)
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
    log.info("certificado HTTPS emitido para %s", ", ".join(sorted(nomes | ips)))
    return crt, key


def confiar_neste_pc(pasta: Path) -> int:
    """Instala a AC local em Raiz Confiável do usuário atual (o Windows pede confirmação)."""
    certificado_https(pasta)
    r = subprocess.run(["certutil", "-user", "-addstore", "Root", str(pasta / "ca.crt")])
    return r.returncode


def chave_sessao(pasta: Path) -> str:
    arq = pasta / "chave_sessao"
    if not arq.exists():
        arq.write_text(secrets.token_urlsafe(48), encoding="ascii")
    return arq.read_text(encoding="ascii").strip()


# ------------------------------------------------------------------ rotinas em segundo plano

def backup(banco_arq: Path, destinos: list[Path], manter: int = 14):
    nome = f"nfse_{dt.datetime.now():%Y%m%d_%H%M}.db"
    for d in destinos:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(banco_arq) as origem, sqlite3.connect(d / nome) as copia:
                origem.backup(copia)
            antigos = sorted(d.glob("nfse_*.db"))[:-manter]
            for a in antigos:
                a.unlink(missing_ok=True)
            log.info("backup gravado em %s", d / nome)
        except Exception:      # noqa: BLE001
            log.exception("falha no backup para %s", d)


def sincronizar_todas(banco: Banco):
    from nfse_nacional.servico import Emissor, tomadores_de_notas
    import dataclasses
    for e in banco.empresas():
        try:
            cert = cofre.certificado_ativo(banco, e)
            em = Emissor(banco, dataclasses.replace(e, ambiente="producao"), cert, usuario="agendador")
            n = em.sincronizar()
            tomadores_de_notas(banco, e.id)
            log.info("sincronização automática %s: %s documento(s)", e.cnpj, n)
        except Exception:      # noqa: BLE001
            log.exception("sincronização automática falhou para %s", e.cnpj)


def iniciar_rotinas(banco: Banco):
    horas_sync = float(os.environ.get("NFSE_SYNC_HORAS", "4"))
    destinos = [pasta_dados() / "backups"]
    if os.environ.get("NFSE_BACKUP_DESTINO"):
        destinos.append(Path(os.environ["NFSE_BACKUP_DESTINO"]))

    def laco():
        proximo_backup = proximo_sync = time.time() + 60
        while True:
            agora = time.time()
            if agora >= proximo_backup:
                backup(banco.caminho, destinos)
                proximo_backup = agora + 24 * 3600
            if horas_sync > 0 and agora >= proximo_sync:
                sincronizar_todas(banco)
                proximo_sync = agora + horas_sync * 3600
            time.sleep(30)
    threading.Thread(target=laco, daemon=True, name="rotinas").start()


# ------------------------------------------------------------------ comandos

def rodar(porta: int, https: bool):
    import uvicorn

    from nfse_nacional.web.app import criar_app
    pasta = pasta_dados()
    _proteger_pasta(pasta)
    (pasta / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(pasta / "logs" / "servidor.log", encoding="utf-8"),
                                  logging.StreamHandler()])
    banco = Banco()
    app = criar_app(banco, https=https, chave_sessao=chave_sessao(pasta),
                    ca_crt=(pasta / "https" / "ca.crt") if https else None)
    iniciar_rotinas(banco)
    kw = {}
    if https:
        crt, key = certificado_https(pasta / "https")
        kw = {"ssl_certfile": str(crt), "ssl_keyfile": str(key)}
    esquema = "https" if https else "http"
    log.info("NFS-e Nacional %s em %s://%s:%s (dados em %s)", VERSAO, esquema, socket.gethostname(), porta, pasta)
    uvicorn.run(app, host="0.0.0.0", port=porta, log_config=None, access_log=False, **kw)


def importar_dados_desktop():
    """Copia o banco e os certificados do app desktop deste usuário para o servidor e
    passa as senhas do keyring para o cofre do servidor (DPAPI)."""
    origem = Path(os.environ.get("LOCALAPPDATA", "")) / "NFSE_Nacional"
    destino = pasta_dados()
    if not (origem / "nfse_nacional.db").exists():
        raise SystemExit(f"Não achei o banco do desktop em {origem}.")
    if (destino / "nfse_nacional.db").exists():
        raise SystemExit(f"Já existe banco no servidor ({destino}). Apague-o antes, se quiser substituir.")
    (destino / "certificados").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(origem / "nfse_nacional.db") as o, sqlite3.connect(destino / "nfse_nacional.db") as d:
        o.backup(d)
    banco = Banco(destino / "nfse_nacional.db")
    import keyring
    n = 0
    for e in banco.empresas():
        cofre.usar_keyring()
        cofre.migrar_certificado_antigo(banco, e)          # garante a tabela de certificados
        for c in banco.certificados(e.id):
            novo = destino / "certificados" / Path(c["arquivo"]).name
            if Path(c["arquivo"]).exists() and not novo.exists():
                shutil.copyfile(c["arquivo"], novo)
            senha = keyring.get_password(cofre.SERVICO_KEYRING, c["chave_cofre"]) or \
                keyring.get_password(cofre.SERVICO_KEYRING, c["documento"])
            if senha is None:
                print(f"  ! sem senha no cofre para {c['titular']}: reenvie o .pfx pela tela Empresa")
                continue
            cofre.usar_cofre_do_servidor(banco)
            cofre._guardar(c["chave_cofre"], senha)
            banco.con.execute("UPDATE certificados SET arquivo=? WHERE id=?", (str(novo), c["id"]))
            n += 1
        principal = next((c for c in banco.certificados(e.id) if c["principal"]), None)
        if principal:
            banco.definir_certificado_principal(e.id, principal["id"])
    banco.fechar()
    _proteger_pasta(destino)
    print(f"Dados copiados para {destino}: {n} certificado(s) com senha no cofre do servidor.")


def instalar_servico(porta: int):
    exe = " ".join(f'"{p}"' for p in _executavel())
    r = _cmd("schtasks", "/Create", "/TN", NOME_TAREFA, "/SC", "ONSTART", "/RU", "SYSTEM",
             "/RL", "HIGHEST", "/F", "/TR", f"{exe} rodar --porta {porta}")
    if r.returncode != 0:
        raise SystemExit(f"Falhou ao criar a tarefa (rode como administrador): {r.stderr or r.stdout}")
    _cmd("netsh", "advfirewall", "firewall", "delete", "rule", f"name={NOME_TAREFA}")
    f = _cmd("netsh", "advfirewall", "firewall", "add", "rule", f"name={NOME_TAREFA}", "dir=in",
             "action=allow", "protocol=TCP", f"localport={porta}", "profile=private,domain")
    _cmd("schtasks", "/Run", "/TN", NOME_TAREFA)
    print(f"Servidor instalado: inicia com o Windows (conta SYSTEM) na porta {porta}.")
    print("Firewall:", "liberado (redes privada/domínio)" if f.returncode == 0 else f"falhou: {f.stdout}")
    print(f"Acesse: https://{socket.gethostname()}:{porta}")


def remover_servico():
    _cmd("schtasks", "/End", "/TN", NOME_TAREFA)
    r = _cmd("schtasks", "/Delete", "/TN", NOME_TAREFA, "/F")
    _cmd("netsh", "advfirewall", "firewall", "delete", "rule", f"name={NOME_TAREFA}")
    print("Removido." if r.returncode == 0 else f"Nada removido: {r.stderr or r.stdout}")


def criar_admin(login: str):
    from nfse_nacional.web import auth
    banco = Banco()
    senha = getpass.getpass("Senha (mín. 8, letras e números): ")
    motivo = auth.senha_fraca(senha)
    if motivo:
        raise SystemExit(motivo)
    u = banco.usuario(login)
    if u:
        banco.atualizar_usuario(u["id"], hash_senha=auth.gerar_hash(senha), papel="admin", ativo=1,
                                falhas=0, bloqueado_ate=None)
    else:
        banco.criar_usuario(login, login, auth.gerar_hash(senha), "admin")
    banco.auditar("terminal", "criar-admin", login)
    print(f"Administrador {login} pronto.")


def main(argv=None) -> int:
    # Servidor guarda tudo em ProgramData (não no perfil do usuário), salvo se a variável mandar.
    os.environ.setdefault("NFSE_NACIONAL_DADOS", str(PASTA_SERVIDOR))
    ap = argparse.ArgumentParser(prog="NFSE_Servidor", description=f"NFS-e Nacional {VERSAO} — servidor web interno")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("rodar")
    p.add_argument("--porta", type=int, default=8443)
    p.add_argument("--sem-https", action="store_true")
    p = sub.add_parser("instalar-servico")
    p.add_argument("--porta", type=int, default=8443)
    sub.add_parser("remover-servico")
    sub.add_parser("importar-dados-desktop")
    sub.add_parser("confiar-certificado", help="faz este PC confiar no HTTPS do servidor")
    p = sub.add_parser("criar-admin")
    p.add_argument("login")
    a = ap.parse_args(argv)
    if a.cmd in (None, "rodar"):
        rodar(getattr(a, "porta", 8443), not getattr(a, "sem_https", False))
    elif a.cmd == "instalar-servico":
        instalar_servico(a.porta)
    elif a.cmd == "remover-servico":
        remover_servico()
    elif a.cmd == "importar-dados-desktop":
        importar_dados_desktop()
    elif a.cmd == "confiar-certificado":
        return confiar_neste_pc(pasta_dados() / "https")
    elif a.cmd == "criar-admin":
        criar_admin(a.login)
    return 0


if __name__ == "__main__":
    sys.exit(main())
