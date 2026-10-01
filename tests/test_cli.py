import json

import keyring
import pytest
from keyring.backend import KeyringBackend
from lxml import etree

from nfse_nacional import assinatura, cli, validacao

from .conftest import CNPJ, SENHA


class CofreMemoria(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.d = {}

    def set_password(self, s, u, p): self.d[(s, u)] = p
    def get_password(self, s, u): return self.d.get((s, u))
    def delete_password(self, s, u): self.d.pop((s, u), None)


@pytest.fixture(autouse=True)
def cofre_falso():
    anterior = keyring.get_keyring()
    keyring.set_keyring(CofreMemoria())
    yield
    keyring.set_keyring(anterior)


def test_fluxo_cli_importar_configurar_simular(tmp_path, pfx_bytes, capsys):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(pfx_bytes)
    db = str(tmp_path / "cli.db")
    assert cli.main(["--banco", db, "empresa-importar", "--pfx", str(pfx), "--senha", SENHA]) == 0
    cofre_ = keyring.get_keyring().d
    assert [v for (srv, u), v in cofre_.items() if u.startswith(CNPJ + ":")] == [SENHA]
    assert cli.main(["--banco", db, "empresa-config", CNPJ, "c_mun=4115200", "op_simp_nac=3",
                     "reg_ap_trib_sn=1", "c_trib_nac=010701", "p_tot_sn=6"]) == 0

    nota = tmp_path / "nota.json"
    nota.write_text(json.dumps({
        "descricao": "Consultoria", "v_serv": "250.5", "d_compet": "2026-09-01",
        "tomador": {"documento": "12345678909", "nome": "Fulano"}}), encoding="utf-8")
    saida = tmp_path / "dps.xml"
    assert cli.main(["--banco", db, "simular", CNPJ, str(nota), "--saida", str(saida)]) == 0
    raiz = etree.fromstring(saida.read_bytes())
    validacao.validar_dps(raiz)
    assinatura.verificar(raiz)
    assert "250.50" in saida.read_text(encoding="utf-8")


def test_cli_validacao_retorna_codigo_2(tmp_path, pfx_bytes, capsys):
    pfx = tmp_path / "cert.pfx"
    pfx.write_bytes(pfx_bytes)
    db = str(tmp_path / "cli.db")
    cli.main(["--banco", db, "empresa-importar", "--pfx", str(pfx), "--senha", SENHA])
    nota = tmp_path / "nota.json"
    nota.write_text(json.dumps({"descricao": "X", "v_serv": "10"}), encoding="utf-8")
    # sem município nem cTribNac cadastrados
    assert cli.main(["--banco", db, "simular", CNPJ, str(nota)]) == 2
    assert "município" in capsys.readouterr().err
