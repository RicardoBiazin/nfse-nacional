"""HTTPS do servidor: AC local + certificado do site assinado por ela."""
import ssl
import sys
import threading
from pathlib import Path

import pytest
from cryptography import x509

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import servidor  # noqa: E402


def test_cadeia_valida_e_servidor_tls(tmp_path):
    crt, key = servidor.certificado_https(tmp_path)
    ca = tmp_path / "ca.crt"
    certs = x509.load_pem_x509_certificates(crt.read_bytes())
    assert len(certs) == 2                                    # site + AC
    site, ac = certs
    assert site.issuer == ac.subject
    assert ac.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not site.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    # handshake real com verificação estrita de cadeia e nome (como o navegador faz)
    srv = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.load_cert_chain(crt, key)
    cli = ssl.create_default_context(cafile=str(ca))
    import socket
    l = socket.socket(); l.bind(("127.0.0.1", 0)); l.listen(1)
    porta = l.getsockname()[1]

    def aceitar():
        c, _ = l.accept()
        try:
            srv.wrap_socket(c, server_side=True).close()
        except ssl.SSLError:
            pass
    th = threading.Thread(target=aceitar, daemon=True); th.start()
    with socket.create_connection(("127.0.0.1", porta)) as s:
        with cli.wrap_socket(s, server_hostname=socket.gethostname()) as t:
            assert t.version().startswith("TLS")
    l.close()


def test_substitui_autoassinado_antigo_e_mantem_ac(tmp_path):
    crt, _ = servidor.certificado_https(tmp_path)
    ac_antes = (tmp_path / "ca.crt").read_bytes()
    # certificado antigo (autoassinado, sem AC) é trocado na próxima partida
    antigo = x509.load_pem_x509_certificates(crt.read_bytes())[1]   # qualquer cert que não seja da AC atual... usa a própria AC
    crt.write_bytes(b"lixo")
    servidor.certificado_https(tmp_path)
    assert x509.load_pem_x509_certificates(crt.read_bytes())[0].issuer == antigo.subject
    assert (tmp_path / "ca.crt").read_bytes() == ac_antes      # AC preservada: PCs continuam confiando


def test_renova_quando_ip_muda(tmp_path, monkeypatch):
    crt, _ = servidor.certificado_https(tmp_path)
    serie = x509.load_pem_x509_certificates(crt.read_bytes())[0].serial_number
    assert not servidor._precisa_renovar(crt, tmp_path / "ca.crt")
    nomes, ips = servidor._nomes_e_ips()
    monkeypatch.setattr(servidor, "_nomes_e_ips", lambda: (nomes, ips | {"10.99.99.99"}))
    assert servidor._precisa_renovar(crt, tmp_path / "ca.crt")
    servidor.certificado_https(tmp_path)
    novo = x509.load_pem_x509_certificates(crt.read_bytes())[0]
    assert novo.serial_number != serie
    san = novo.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "10.99.99.99" in {str(i) for i in san.get_values_for_type(x509.IPAddress)}


def test_rota_publica_da_ac(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from nfse_nacional import cofre, dpapi
    from nfse_nacional.banco import Banco
    from nfse_nacional.web.app import criar_app
    if not dpapi.disponivel():
        pytest.skip("DPAPI")
    servidor.certificado_https(tmp_path / "https")
    b = Banco(tmp_path / "w.db")
    try:
        c = TestClient(criar_app(b, ca_crt=tmp_path / "https" / "ca.crt"))
        r = c.get("/ca.crt")                                     # sem login: certificado público
        assert r.status_code == 200 and b"BEGIN CERTIFICATE" in r.content
        assert b"PRIVATE KEY" not in r.content
    finally:
        cofre.usar_keyring()
        b.fechar()
