"""Exportação: XMLs em pasta e planilha .xlsx das notas."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .banco import Banco

COLUNAS = [
    ("Origem", "origem"), ("Situação", "situacao"), ("Número", "numero"),
    ("Série", "serie"), ("nDPS", "n_dps"), ("Competência", "d_compet"),
    ("Emissão", "dh_emissao"), ("Prestador CNPJ/CPF", "prestador_doc"),
    ("Prestador", "prestador_nome"), ("Tomador CNPJ/CPF", "tomador_doc"),
    ("Tomador", "tomador_nome"), ("Descrição", "descricao"),
    ("Valor serviço", "v_serv"), ("Valor líquido", "v_liq"), ("ISSQN", "v_issqn"),
    ("Chave de acesso", "chave"), ("Mensagem", "mensagem"),
]
NUMERICAS = {"v_serv", "v_liq", "v_issqn"}


def exportar_xlsx(linhas, destino: str | Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Notas"
    ws.append([c[0] for c in COLUNAS])
    for c in ws[1]:
        c.font = Font(bold=True)
    for ln in linhas:
        linha = []
        for _, campo in COLUNAS:
            v = ln[campo]
            if campo in NUMERICAS and v not in (None, ""):
                v = float(Decimal(v))
            linha.append(v)
        ws.append(linha)
    for i, (titulo, campo) in enumerate(COLUNAS, 1):
        if campo in NUMERICAS:
            for cel in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                for c in cel:
                    c.number_format = "#,##0.00"
        ws.column_dimensions[get_column_letter(i)].width = 48 if campo == "chave" else max(12, len(titulo) + 4)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    destino = Path(destino)
    wb.save(destino)
    return destino


def _nome_base(nota) -> str:
    if nota["chave"]:
        return f"NFSe_{nota['numero'] or 's-n'}_{nota['chave']}"
    return nota["id_dps"] or f"nota_{nota['id']}"


def exportar_notas(banco: Banco, ids: list[int], pasta: str | Path, xml: bool = True,
                   pdf: bool = True, progresso=None) -> tuple[int, int, list[str]]:
    """XML (+ eventos) e/ou DANFSe em PDF de várias notas. Devolve (n_xml, n_pdf, erros)."""
    from .danfse import gerar_pdf
    from .servico import marca_dagua
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    avisar = progresso or (lambda _m: None)
    n_xml = n_pdf = 0
    erros: list[str] = []
    for i, id_ in enumerate(ids, 1):
        nota = banco.nota(id_)
        if not nota:
            continue
        base = _nome_base(nota)
        avisar(f"Exportando {i}/{len(ids)}: {base}")
        if xml:
            conteudo = nota["nfse_xml"] or nota["dps_xml"]
            if conteudo:
                (pasta / f"{base}.xml").write_bytes(conteudo)
                n_xml += 1
            if nota["chave"]:
                for ev in banco.eventos(nota["chave"]):
                    (pasta / f"{base}_evento_{ev['tipo']}.xml").write_bytes(ev["xml"])
        if pdf:
            if not nota["nfse_xml"]:
                erros.append(f"{base}: sem XML da NFS-e (nota não autorizada) — PDF não gerado")
                continue
            try:
                (pasta / f"{base}.pdf").write_bytes(gerar_pdf(nota["nfse_xml"], marca_dagua(banco, nota)))
                n_pdf += 1
            except Exception as erro:      # noqa: BLE001
                erros.append(f"{base}: {erro}")
    return n_xml, n_pdf, erros
