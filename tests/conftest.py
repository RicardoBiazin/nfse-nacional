import datetime as dt
import sys
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CNPJ = "11222333000181"
SENHA = "teste123"


def _pfx(cnpj: str = CNPJ, senha: str = SENHA, dias: int = 365) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{cnpj}")])
    # OtherName ICP-Brasil do CNPJ: valor é um OCTET STRING com os 14 dígitos.
    valor = b"\x04" + bytes([len(cnpj)]) + cnpj.encode()
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=dias))
            .add_extension(x509.SubjectAlternativeName([
                x509.OtherName(x509.ObjectIdentifier("2.16.76.1.3.3"), valor)]), critical=False)
            .sign(chave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(
        b"teste", chave, cert, None, serialization.BestAvailableEncryption(senha.encode()))


@pytest.fixture(scope="session")
def pfx_bytes():
    return _pfx()


@pytest.fixture(scope="session")
def certificado(pfx_bytes):
    from nfse_nacional.certificado import Certificado
    return Certificado.de_bytes(pfx_bytes, SENHA)


@pytest.fixture(autouse=True)
def pasta_dados_temporaria(tmp_path, monkeypatch):
    monkeypatch.setenv("NFSE_NACIONAL_DADOS", str(tmp_path / "dados"))
