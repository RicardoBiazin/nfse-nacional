"""Certificado A1 (.pfx/.p12): leitura, identificação do titular e contexto TLS.

Leitura do .pfx adaptada de EditPDFree (assinatura_digital.carregar_certificado).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import ssl
import tempfile
from dataclasses import dataclass, field

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

# OtherName da ICP-Brasil (RN do Anexo I: o certificado precisa ter um deles).
OID_CNPJ = x509.ObjectIdentifier("2.16.76.1.3.3")
OID_CPF_PF = x509.ObjectIdentifier("2.16.76.1.3.1")


class SenhaCertificadoIncorreta(ValueError):
    pass


def carregar_pfx(pfx: bytes, senha: str):
    """(chave, certificado, cadeia). Senha errada vira SenhaCertificadoIncorreta."""
    try:
        chave, cert, cadeia = pkcs12.load_key_and_certificates(
            pfx, senha.encode("utf-8") if senha else None)
    except ValueError as erro:
        texto = str(erro).lower()
        if "password" in texto or "mac" in texto or "decrypt" in texto:
            raise SenhaCertificadoIncorreta("Senha do certificado incorreta.") from None
        raise ValueError(f"Arquivo de certificado inválido: {erro}") from None
    if chave is None or cert is None:
        raise ValueError("O arquivo não contém chave privada e certificado.")
    return chave, cert, list(cadeia or [])


def _documento_icp(cert: x509.Certificate) -> tuple[str, str]:
    """('CNPJ'|'CPF', número) pelo OtherName da ICP-Brasil; cai para o CN."""
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for nome in san.get_values_for_type(x509.OtherName):
            texto = nome.value.decode("latin-1", "ignore")
            digitos = re.sub(r"\D", "", texto)
            if nome.type_id == OID_CNPJ and len(digitos) >= 14:
                return "CNPJ", digitos[-14:]
            if nome.type_id == OID_CPF_PF and len(digitos) >= 19:
                # dtNasc(8) + CPF(11) + NIS(11) + RG...
                return "CPF", digitos[8:19]
    except x509.ExtensionNotFound:
        pass
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn:
        m = re.search(r":(\d{14}|\d{11})\s*$", cn[0].value)
        if m:
            num = m.group(1)
            return ("CNPJ" if len(num) == 14 else "CPF"), num
    return "", ""


@dataclass
class Certificado:
    chave: object
    cert: x509.Certificate
    cadeia: list = field(default_factory=list)

    @classmethod
    def de_arquivo(cls, caminho: str | os.PathLike, senha: str) -> "Certificado":
        with open(caminho, "rb") as f:
            return cls.de_bytes(f.read(), senha)

    @classmethod
    def de_bytes(cls, pfx: bytes, senha: str) -> "Certificado":
        return cls(*carregar_pfx(pfx, senha))

    @property
    def titular(self) -> str:
        cn = self.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return cn[0].value if cn else self.cert.subject.rfc4514_string()

    @property
    def documento(self) -> tuple[str, str]:
        return _documento_icp(self.cert)

    @property
    def cnpj(self) -> str:
        tipo, num = self.documento
        return num if tipo == "CNPJ" else ""

    @property
    def validade(self) -> dt.datetime:
        return self.cert.not_valid_after_utc

    @property
    def vencido(self) -> bool:
        return self.validade < dt.datetime.now(dt.timezone.utc)

    def dias_para_vencer(self) -> int:
        return (self.validade - dt.datetime.now(dt.timezone.utc)).days

    def cert_base64(self) -> str:
        """X509Certificate da assinatura: DER em Base64, sem cabeçalhos PEM."""
        import base64
        return base64.b64encode(self.cert.public_bytes(serialization.Encoding.DER)).decode()

    def contexto_ssl(self) -> ssl.SSLContext:
        """SSLContext com o A1 para mTLS.

        O ssl do Python só carrega certificado de arquivo. A chave vai para o
        disco cifrada com senha aleatória de uso único e os dois arquivos são
        apagados logo após o carregamento; a chave em claro nunca toca o disco.
        """
        ctx = ssl.create_default_context()
        senha = secrets.token_urlsafe(32).encode()
        pem_cert = self.cert.public_bytes(serialization.Encoding.PEM) + b"".join(
            c.public_bytes(serialization.Encoding.PEM) for c in self.cadeia)
        pem_chave = self.chave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(senha))
        arquivos = []
        try:
            for conteudo in (pem_cert, pem_chave):
                fd, caminho = tempfile.mkstemp(suffix=".pem", prefix="nfse_")
                arquivos.append(caminho)
                with os.fdopen(fd, "wb") as f:
                    f.write(conteudo)
            ctx.load_cert_chain(arquivos[0], arquivos[1], password=senha)
        finally:
            for caminho in arquivos:
                try:
                    os.remove(caminho)
                except OSError:
                    pass
        return ctx
