"""Importação e exportação em lote (XML, PDF de DANFSe, ZIP, pastas)."""
import zipfile

import pytest

from nfse_nacional import compactacao, exportar
from nfse_nacional.danfse import gerar_pdf
from nfse_nacional.dps import gerar_xml, para_bytes
from nfse_nacional.servico import Emissor

from .test_servico import (CHAVE, SessaoFalsa, banco, dados, empresa,  # noqa: F401
                           evento_cancelamento, nfse_de, resposta)

pytest.importorskip("pypdf")
CHAVE2 = "4205407" + "5" * 43


def _nfse(em, n, chave):
    return nfse_de(para_bytes(gerar_xml(em.montar_dps(dados(), n))), chave=chave, numero=str(n))


def test_importar_xml_zip_pasta_e_pdf(banco, empresa, certificado, tmp_path):
    s = SessaoFalsa()
    em = Emissor(banco, empresa, certificado, sessao=s)
    x1, x2 = _nfse(em, 1, CHAVE), _nfse(em, 2, CHAVE2)
    pasta = tmp_path / "entrada"; (pasta / "sub").mkdir(parents=True)
    (pasta / "sub" / "nota1.xml").write_bytes(x1)
    (pasta / "ignorado.txt").write_text("x")
    with zipfile.ZipFile(tmp_path / "lote.zip", "w") as z:
        z.writestr("dentro/nota1.xml", x1)                      # repetida: já existe
        z.writestr("evento.xml", evento_cancelamento(CHAVE))
    r = em.importar_arquivos([pasta, tmp_path / "lote.zip"])
    assert (r.importados, r.ja_existiam, r.erros) == (2, 1, [])
    assert banco.nota_por_chave(CHAVE)["situacao"] == "cancelada"

    # PDF: lê a chave no DANFSe e baixa o XML oficial na Sefin
    pdf = tmp_path / "danfse.pdf"
    pdf.write_bytes(gerar_pdf(x2))
    s.rota("GET", rf"/nfse/{CHAVE2}$", lambda u, k: resposta(200, {
        "nfseXmlGZipB64": compactacao.para_gzip_b64(x2)}))
    r = em.importar_arquivos([pdf])
    assert (r.importados, r.erros) == (1, [])
    assert banco.nota_por_chave(CHAVE2)["numero"] == "2"
    r = em.importar_arquivos([pdf])                             # de novo: já existe
    assert (r.importados, r.ja_existiam) == (0, 1)


def test_pdf_sem_chave_vira_erro(banco, empresa, certificado, tmp_path):
    from reportlab.pdfgen import canvas
    arq = tmp_path / "qualquer.pdf"
    c = canvas.Canvas(str(arq)); c.drawString(100, 700, "boleto 123"); c.save()
    r = Emissor(banco, empresa, certificado, sessao=SessaoFalsa()).importar_arquivos([arq])
    assert r.importados == 0 and "chave de acesso" in r.erros[0]


def test_exportar_xml_e_pdf(banco, empresa, certificado, tmp_path):
    em = Emissor(banco, empresa, certificado, sessao=SessaoFalsa())
    em.importar_xml(_nfse(em, 1, CHAVE))
    em.importar_xml(evento_cancelamento(CHAVE))
    em.importar_xml(_nfse(em, 2, CHAVE2))
    pendente = banco.inserir_nota(empresa_id=empresa.id, ambiente=empresa.ambiente,
                                  situacao="indefinida", id_dps="DPS" + "0" * 42, dps_xml=b"<DPS/>")
    ids = [banco.nota_por_chave(CHAVE)["id"], banco.nota_por_chave(CHAVE2)["id"], pendente]
    n_xml, n_pdf, erros = exportar.exportar_notas(banco, ids, tmp_path / "saida")
    nomes = sorted(p.name for p in (tmp_path / "saida").iterdir())
    assert (n_xml, n_pdf) == (3, 2) and len(erros) == 1
    assert f"NFSe_1_{CHAVE}.pdf" in nomes and f"NFSe_1_{CHAVE}_evento_101101.xml" in nomes
    import pypdf
    texto = pypdf.PdfReader(tmp_path / "saida" / f"NFSe_1_{CHAVE}.pdf").pages[0].extract_text()
    assert "CANCELADA" in texto
    so_pdf = tmp_path / "pdf"
    assert exportar.exportar_notas(banco, ids[:2], so_pdf, xml=False)[:2] == (0, 2)
