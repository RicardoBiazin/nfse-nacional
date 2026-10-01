"""DANFSe v2.0 gerado localmente a partir do XML da NFS-e (NT SE/CGNFS-e 008/2026).

A API de DANFSe do ADN foi suspensa em 1º/07/2026 (a própria NT 008 determina que os
emissores gerem o documento). Layout: Anexo I da NT, A4 retrato, página única, medidas
em cm a partir da margem superior esquerda, como na tabela do item 2.4.5.
"""
from __future__ import annotations

import io
import os
import textwrap
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from lxml import etree
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .config import NS_NFSE, pasta_base

N = {"n": NS_NFSE}
URL_CONSULTA = "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave="

X0, LARG = 0.30, 20.40                     # corpo do DANFSe
COLS = [0.30, 5.41, 10.51, 15.62]          # quatro colunas de 5,09 cm
LCOL = 5.09
ALT_LINHA = 0.63
CINZA = Color(0.95, 0.95, 0.95)            # sombreamento 5 %
CINZA_MARCA = Color(0.65, 0.65, 0.65, alpha=0.45)
VERMELHO = Color(0.85, 0, 0)

UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}

TP_EMIT = {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}
C_STAT = {"100": "NFS-e Gerada", "101": "NFS-e de Substituição Gerada",
          "102": "NFS-e de Decisão Judicial", "103": "NFS-e Avulsa"}
FIN_NFSE = {"0": "NFS-e regular"}
AMB_GER = {"1": "Prefeitura", "2": "Sistema Nacional NFS-e"}
TP_AMB = {"1": "Produção", "2": "Homologação"}
OP_SIMP = {"1": "Não Optante", "2": "Optante - Microempreendedor Individual (MEI)",
           "3": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)"}
REG_AP_SN = {
    "1": "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
    "2": "Regime de apuração dos tributos federais pelo SN e ISSQN por fora do SN conforme respectiva legislação municipal do tributo",
    "3": "Regime de apuração dos tributos federais e municipal por fora do SN conforme respectivas legislações federal e municipal de cada tributo",
}
REG_ESP = {"0": "Nenhum", "1": "Ato Cooperado (Cooperativa)", "2": "Estimativa",
           "3": "Microempresa Municipal", "4": "Notário ou Registrador",
           "5": "Profissional Autônomo", "6": "Sociedade de Profissionais", "9": "Outros"}
TRIB_ISSQN = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação de Serviço",
              "4": "Não Incidência"}
RET_ISSQN = {"1": "Não Retido", "2": "Retido pelo Tomador", "3": "Retido pelo Intermediário"}
IMUNIDADE = {"0": "Imunidade (tipo não informado)",
             "1": "Patrimônio, renda ou serviços, uns dos outros",
             "2": "Templos de qualquer culto",
             "3": "Partidos, sindicatos, educação e assistência social",
             "4": "Livros, jornais, periódicos e o papel destinado a sua impressão",
             "5": "Fonogramas e videofonogramas musicais"}
SUSPENSAO = {"1": "Exigibilidade Suspensa por Decisão Judicial",
             "2": "Exigibilidade Suspensa por Processo Administrativo"}
TP_BM = {"1": "Isenção", "2": "Redução da BC em percentual", "3": "Redução da BC em valor",
         "4": "Alíquota diferenciada"}
RET_PIS = {"0": "PIS/COFINS/CSLL Não Retidos", "1": "PIS/COFINS Retidos",
           "2": "PIS/COFINS Não Retidos", "3": "PIS/COFINS/CSLL Retidos",
           "4": "PIS/COFINS Retidos, CSLL Não Retido", "5": "PIS Retido, COFINS/CSLL Não Retido",
           "6": "COFINS Retido, PIS/CSLL Não Retido", "7": "PIS Não Retido, COFINS/CSLL Retidos",
           "8": "PIS/COFINS Não Retidos, CSLL Retido", "9": "COFINS Não Retido, PIS/CSLL Retidos"}


# --------------------------------------------------------------------- fontes e tabelas

@lru_cache(maxsize=None)
def _fontes() -> tuple[str, str, str]:
    """(rótulo, rótulo negrito, conteúdo): Arial e Microsoft Sans Serif, como pede a NT."""
    pasta = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    pares = {"Arial": "arial.ttf", "Arial-Bold": "arialbd.ttf", "MSSansSerif": "micross.ttf"}
    ok = {}
    for nome, arq in pares.items():
        try:
            pdfmetrics.registerFont(TTFont(nome, str(pasta / arq)))
            ok[nome] = True
        except Exception:      # noqa: BLE001 - sem a fonte, cai na Helvetica
            ok[nome] = False
    return (("Arial" if ok["Arial"] else "Helvetica"),
            ("Arial-Bold" if ok["Arial-Bold"] else "Helvetica-Bold"),
            ("MSSansSerif" if ok["MSSansSerif"] else ("Arial" if ok["Arial"] else "Helvetica")))


@lru_cache(maxsize=None)
def _municipios() -> dict[str, str]:
    caminho = pasta_base() / "recursos" / "municipios_ibge.csv"
    try:
        with open(caminho, encoding="utf-8") as f:
            return dict(ln.rstrip("\n").split(";", 1) for ln in f if ";" in ln)
    except OSError:
        return {}


def nome_municipio(c_mun: str) -> str:
    if not c_mun:
        return ""
    nome = _municipios().get(c_mun, c_mun)
    uf = UF_POR_CODIGO.get(c_mun[:2], "")
    return f"{nome} / {uf}" if uf else nome


# --------------------------------------------------------------------- formatação

def _cnpj_cpf(v: str) -> str:
    if len(v) == 14 and v.isdigit():
        return f"{v[:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:]}"
    if len(v) == 11 and v.isdigit():
        return f"{v[:3]}.{v[3:6]}.{v[6:9]}-{v[9:]}"
    return v


def _cep(v: str) -> str:
    return f"{v[:2]}.{v[2:5]}-{v[5:]}" if len(v) == 8 and v.isdigit() else v


def _fone(v: str) -> str:
    if v.isdigit() and len(v) in (10, 11):
        return f"({v[:2]}) {v[2:-4]}-{v[-4:]}"
    return v


def _data(v: str) -> str:
    try:
        return datetime.fromisoformat(v[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return v


def _data_hora(v: str) -> str:
    try:
        return datetime.fromisoformat(v).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return v


def _moeda(v: str) -> str:
    if not v:
        return ""
    s = f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _perc(v: str) -> str:
    return f"{Decimal(v):.2f}".replace(".", ",") + " %" if v else ""


def _trib_nac(v: str) -> str:
    return f"{v[:2]}.{v[2:4]}.{v[4:6]}" if len(v) == 6 else v


def _nbs(v: str) -> str:
    return f"{v[0]}.{v[1:5]}.{v[5:7]}.{v[7:9]}" if len(v) == 9 else v


def _corta(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."


# --------------------------------------------------------------------- desenho

class _Folha:
    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.rot, self.rot_b, self.cont = _fontes()
        self.y = 0.0

    def _Y(self, y_cm: float) -> float:          # topo (cm) -> coordenada do reportlab
        return A4[1] - y_cm * cm

    def caixa(self, x, y, w, h, fundo=None, borda=True):
        if fundo:
            self.c.setFillColor(fundo)
            self.c.rect(x * cm, self._Y(y + h), w * cm, h * cm, stroke=0, fill=1)
            self.c.setFillColor(black)
        if borda:
            self.c.setLineWidth(0.5)
            self.c.rect(x * cm, self._Y(y + h), w * cm, h * cm, stroke=1, fill=0)

    def linha_h(self, y):
        self.c.setLineWidth(0.5)
        self.c.line(X0 * cm, self._Y(y), (X0 + LARG) * cm, self._Y(y))

    def texto(self, x, y, s, fonte=None, tam=7, cor=black, centro_w=None, direita_w=None):
        self.c.setFillColor(cor)
        self.c.setFont(fonte or self.cont, tam)
        if centro_w is not None:
            self.c.drawCentredString((x + centro_w / 2) * cm, self._Y(y), s)
        elif direita_w is not None:
            self.c.drawRightString((x + direita_w) * cm, self._Y(y), s)
        else:
            self.c.drawString(x * cm, self._Y(y), s)
        self.c.setFillColor(black)

    def caber(self, s: str, largura_cm: float, tam=7, fonte=None) -> str:
        fonte = fonte or self.cont
        if pdfmetrics.stringWidth(s, fonte, tam) <= largura_cm * cm - 4:
            return s
        while s and pdfmetrics.stringWidth(s + "...", fonte, tam) > largura_cm * cm - 4:
            s = s[:-1]
        return s + "..."

    def campo(self, col: int, rotulo: str, valor: str, span: int = 1, y: float | None = None,
              alt: float = ALT_LINHA, rot_tam=6, rot_maiusc=False):
        y = self.y if y is None else y
        x = COLS[col] + 0.05
        w = LCOL * span + (span - 1) * 0.02 - 0.1
        self.texto(x, y + 0.24, rotulo.upper() if rot_maiusc else rotulo, self.rot_b, rot_tam)
        self.texto(x, y + 0.24 + 0.30, self.caber(valor or "-", w), self.cont, 7)

    def titulo_bloco(self, titulo: str, alt: float = ALT_LINHA):
        """Título do bloco na 1ª coluna, sombreado, 7 pt negrito caixa alta."""
        self.caixa(COLS[0], self.y, LCOL, alt, fundo=CINZA, borda=False)
        self.texto(COLS[0] + 0.05, self.y + 0.24, titulo.upper(), self.rot_b, 7)

    def faixa(self, mensagem: str, alt: float = 0.32):
        """Bloco suprimido: uma linha centralizada (notas 2, 3 e 4 da NT)."""
        self.linha_h(self.y)
        self.texto(X0, self.y + 0.23, mensagem, self.rot_b, 6.5, centro_w=LARG)
        self.y += alt

    def nova_linha(self, alt: float = ALT_LINHA, divisoria: bool = False):
        if divisoria:
            self.linha_h(self.y)
        self.y += alt


# --------------------------------------------------------------------- leitura do XML

class _Xml:
    def __init__(self, raiz: etree._Element):
        self.inf = raiz.find("n:infNFSe", N)
        if self.inf is None:
            raise ValueError("XML não é uma NFS-e (infNFSe ausente).")
        self.dps = self.inf.find("n:DPS/n:infDPS", N)

    def t(self, caminho: str, base=None) -> str:
        el = self.inf if base is None else base
        if el is None:
            return ""
        return (el.findtext(caminho, namespaces=N) or "").strip()

    def d(self, caminho: str) -> str:
        return self.t(caminho, self.dps)

    def no(self, caminho: str, base=None):
        el = self.inf if base is None else base
        return el.find(caminho, N) if el is not None else None


def _doc(x: _Xml, el) -> str:
    if el is None:
        return ""
    return _cnpj_cpf(x.t("n:CNPJ", el) or x.t("n:CPF", el)) or x.t("n:NIF", el)


def _endereco(x: _Xml, end) -> tuple[str, str, str]:
    """(município / UF, IBGE / CEP, logradouro...)"""
    if end is None:
        return "", "", ""
    lgr = ", ".join(p for p in (x.t("n:xLgr", end), x.t("n:nro", end), x.t("n:xCpl", end),
                                x.t("n:xBairro", end)) if p)
    ext = end.find("n:endExt", N)
    if ext is not None:
        return (x.t("n:xCidade", ext), x.t("n:cEndPost", ext), lgr)
    c_mun = x.t("n:endNac/n:cMun", end) or x.t("n:cMun", end)
    cep = x.t("n:endNac/n:CEP", end) or x.t("n:CEP", end)
    return nome_municipio(c_mun), f"{c_mun} / {_cep(cep)}" if c_mun else _cep(cep), lgr


# --------------------------------------------------------------------- geração

def gerar_pdf(nfse_xml: bytes, marca_dagua: str = "", canhoto: bool = True) -> bytes:
    """PDF do DANFSe. marca_dagua: "" | "CANCELADA" | "SUBSTITUÍDA"."""
    raiz = etree.fromstring(nfse_xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    x = _Xml(raiz)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    chave = x.inf.get("Id", "")[3:]
    c.setTitle(f"DANFSe {chave}")
    c.setAuthor("NFSE_Nacional")
    f = _Folha(c)

    _cabecalho(f, x)
    _identificacao(f, x, chave)
    _prestador(f, x)
    _tomador(f, x)
    _destinatario(f, x)
    _intermediario(f, x)
    _servico(f, x)
    _issqn(f, x)
    _federal(f, x)
    _ibscbs(f, x)
    _totais(f, x)
    _complementares(f, x, canhoto)
    if canhoto:
        _canhoto(f, x, chave)

    # Borda da página: 1 pt
    c.setLineWidth(1)
    c.rect(X0 * cm, A4[1] - (0.30 + _ALTURA_UTIL) * cm, LARG * cm, _ALTURA_UTIL * cm)
    if marca_dagua:
        _marca(c, marca_dagua)
    c.showPage()
    c.save()
    return buf.getvalue()


_ALTURA_UTIL = 29.10                         # 29,7 - margens (0,30 em cima e embaixo)


def _cabecalho(f: _Folha, x: _Xml):
    f.y = 0.30
    f.caixa(X0, f.y, LARG, 1.16, fundo=CINZA, borda=False)
    logo = pasta_base() / "recursos" / "logo_nfse.png"
    if logo.exists():
        f.c.drawImage(str(logo), 0.49 * cm, f._Y(0.44 + 0.81), width=4.00 * cm,
                      height=0.81 * cm, mask="auto", preserveAspectRatio=True)
    f.texto(5.41, 0.70, "DANFSe v2.0", f.rot_b, 9, centro_w=10.19)
    f.texto(5.41, 1.05, "Documento Auxiliar da NFS-e", f.rot_b, 9, centro_w=10.19)
    if x.d("n:tpAmb") == "2":
        f.texto(5.41, 1.40, "NFS-e SEM VALIDADE JURÍDICA", f.rot_b, 9, cor=VERMELHO, centro_w=10.19)
    c_mun_emit = x.t("n:emit/n:enderNac/n:cMun")
    uf = x.t("n:emit/n:enderNac/n:UF") or UF_POR_CODIGO.get(c_mun_emit[:2], "")
    if not x.d("n:serv/n:cServ/n:cTribNac").startswith("99"):
        f.texto(15.62, 0.62, f"Município: {x.t('n:xLocEmi')} - {uf}", f.cont, 8)
    f.texto(15.62, 1.00, f"Ambiente Gerador: {AMB_GER.get(x.t('n:ambGer'), x.t('n:ambGer'))}", f.cont, 6)
    f.texto(15.62, 1.25, f"Tipo de Ambiente: {TP_AMB.get(x.d('n:tpAmb'), x.d('n:tpAmb'))}", f.cont, 6)
    f.y = 1.48
    f.linha_h(f.y)


def _identificacao(f: _Folha, x: _Xml, chave: str):
    import segno
    y0 = f.y
    f.texto(X0 + 0.05, y0 + 0.30, "CHAVE DE ACESSO DA NFS-e", f.rot_b, 7)
    f.texto(X0 + 0.05, y0 + 0.62, chave, f.cont, 7)
    linhas = [
        [("NÚMERO DA NFS-e", x.t("n:nNFSe")), ("COMPETÊNCIA DA NFS-e", _data(x.d("n:dCompet"))),
         ("DATA E HORA DA EMISSÃO DA NFS-e", _data_hora(x.t("n:dhProc")))],
        [("NÚMERO DA DPS", x.d("n:nDPS")), ("SÉRIE DA DPS", x.d("n:serie")),
         ("DATA E HORA DA EMISSÃO DA DPS", _data_hora(x.d("n:dhEmi")))],
        [("EMITENTE DA NFS-e", TP_EMIT.get(x.d("n:tpEmit"), "")),
         ("SITUAÇÃO DA NFS-e", _corta(C_STAT.get(x.t("n:cStat"), x.t("n:cStat")), 40)),
         ("FINALIDADE", FIN_NFSE.get(x.d("n:IBSCBS/n:finNFSe"), "-"))],
    ]
    y = y0 + 0.79
    for i, linha in enumerate(linhas):
        if i == 2:     # "Emitente da NFS-e" sombreado (item 2.2.3)
            f.caixa(COLS[0], y, LCOL, 0.67, fundo=CINZA, borda=False)
        for col, (rot, val) in enumerate(linha):
            f.texto(COLS[col] + 0.05, y + 0.26, rot, f.rot_b, 7)
            f.texto(COLS[col] + 0.05, y + 0.56, val or "-", f.cont, 7)
        y += 0.69
    # QR Code: 1,52 x 1,52 cm em X 17,48 / Y 1,67
    qr = segno.make(URL_CONSULTA + chave, error="m")
    png = io.BytesIO()
    qr.save(png, kind="png", scale=6, border=0)
    png.seek(0)
    from reportlab.lib.utils import ImageReader
    f.c.drawImage(ImageReader(png), 17.48 * cm, f._Y(1.67 + 1.52), 1.52 * cm, 1.52 * cm)
    for i, ln in enumerate(("A autenticidade desta NFS-e pode ser verificada",
                            "pela leitura deste código QR ou pela consulta da",
                            "chave de acesso no portal nacional da NFS-e")):
        f.texto(15.80, 3.50 + i * 0.22, ln, f.cont, 6)
    f.y = y0 + 2.86
    f.linha_h(f.y)


def _pessoa(f: _Folha, x: _Xml, titulo: str, el, com_im=True, nome_el=None, regime=False):
    mun, ibge_cep, end = _endereco(x, el.find("n:end", N) if nome_el is None else nome_el)
    f.titulo_bloco(titulo)
    f.campo(1, "CNPJ / CPF / NIF", _doc(x, el))
    if com_im:
        f.campo(2, "Indicador Municipal (Inscrição)", x.t("n:IM", el))
    f.campo(3, "Telefone", _fone(x.t("n:fone", el)))
    f.nova_linha()
    f.campo(0, "Nome / Nome Empresarial", x.t("n:xNome", el), span=2)
    f.campo(2, "Município / Sigla UF", mun)
    f.campo(3, "Código IBGE / CEP", ibge_cep)
    f.nova_linha()
    f.campo(0, "Endereço", end, span=2)
    f.campo(2, "E-mail", x.t("n:email", el), span=2)
    f.nova_linha()
    if regime:
        reg = x.no("n:prest/n:regTrib", x.dps)
        f.campo(0, "Simples Nacional na Data de Competência",
                _corta(OP_SIMP.get(x.t("n:opSimpNac", reg), ""), 40))
        f.campo(1, "Regime de Apuração Tributária pelo SN",
                _corta(REG_AP_SN.get(x.t("n:regApTribSN", reg), ""), 80), span=3)
        f.nova_linha()
    f.linha_h(f.y)


def _prestador(f: _Folha, x: _Xml):
    """Prestador: dados do emitente (emit) completam o que a DPS não traz quando tpEmit=1."""
    prest = x.no("n:prest", x.dps)
    emit = x.no("n:emit")
    src = prest
    # Nome, endereço, fone e e-mail: na DPS com tpEmit=1 não vêm; usa o grupo emit da NFS-e.
    if x.d("n:tpEmit") == "1" and emit is not None:
        mun = nome_municipio(x.t("n:enderNac/n:cMun", emit))
        c_mun = x.t("n:enderNac/n:cMun", emit)
        cep = x.t("n:enderNac/n:CEP", emit)
        end = ", ".join(p for p in (x.t("n:enderNac/n:xLgr", emit), x.t("n:enderNac/n:nro", emit),
                                    x.t("n:enderNac/n:xCpl", emit), x.t("n:enderNac/n:xBairro", emit)) if p)
        f.titulo_bloco("Prestador / Fornecedor")
        f.campo(1, "CNPJ / CPF / NIF", _doc(x, emit))
        f.campo(2, "Indicador Municipal (Inscrição)", x.t("n:IM", emit) or x.t("n:IM", prest))
        f.campo(3, "Telefone", _fone(x.t("n:fone", emit) or x.t("n:fone", prest)))
        f.nova_linha()
        f.campo(0, "Nome / Nome Empresarial", x.t("n:xNome", emit), span=2)
        f.campo(2, "Município / Sigla UF", mun)
        f.campo(3, "Código IBGE / CEP", f"{c_mun} / {_cep(cep)}" if c_mun else "")
        f.nova_linha()
        f.campo(0, "Endereço", end, span=2)
        f.campo(2, "E-mail", x.t("n:email", emit) or x.t("n:email", prest), span=2)
        f.nova_linha()
        reg = x.no("n:regTrib", prest)
        f.campo(0, "Simples Nacional na Data de Competência",
                _corta(OP_SIMP.get(x.t("n:opSimpNac", reg), ""), 40))
        f.campo(1, "Regime de Apuração Tributária pelo SN",
                _corta(REG_AP_SN.get(x.t("n:regApTribSN", reg), ""), 80), span=3)
        f.nova_linha()
        f.linha_h(f.y)
    else:
        _pessoa(f, x, "Prestador / Fornecedor", src, regime=True)


def _tomador(f: _Folha, x: _Xml):
    toma = x.no("n:toma", x.dps)
    if toma is None:
        f.faixa("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
        return
    _pessoa(f, x, "Tomador / Adquirente", toma)


def _destinatario(f: _Folha, x: _Xml):
    dest = x.no("n:IBSCBS/n:dest", x.dps)
    if dest is not None:
        _pessoa(f, x, "Destinatário da Operação", dest, com_im=False)
    elif x.d("n:IBSCBS/n:indDest") == "0":
        f.faixa("O DESTINATÁRIO É O PRÓPRIO TOMADOR/ADQUIRENTE DA OPERAÇÃO")
    else:
        f.faixa("DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")


def _intermediario(f: _Folha, x: _Xml):
    interm = x.no("n:interm", x.dps)
    if interm is None:
        f.faixa("INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
        f.linha_h(f.y)
        return
    _pessoa(f, x, "Intermediário da Operação", interm)


def _servico(f: _Folha, x: _Xml):
    c_trib_nac = x.d("n:serv/n:cServ/n:cTribNac")
    c_trib_mun = x.d("n:serv/n:cServ/n:cTribMun")
    loc = x.d("n:serv/n:locPrest/n:cLocPrestacao")
    pais = x.d("n:serv/n:locPrest/n:cPaisPrestacao")
    if loc:
        local = f"{x.t('n:xLocPrestacao') or nome_municipio(loc).split(' / ')[0]} / " \
                f"{UF_POR_CODIGO.get(loc[:2], '')} / -"
    else:
        local = f"- / - / {pais or '-'}"
    f.titulo_bloco("Serviço Prestado")
    f.campo(1, "Código de Tributação Nacional/Municipal",
            f"{_trib_nac(c_trib_nac)} / {c_trib_mun or '-'}")
    f.campo(2, "Código da NBS", _nbs(x.d("n:serv/n:cServ/n:cNBS")))
    f.campo(3, "Local da Prestação / Sigla UF / País", local)
    f.nova_linha()
    desc_trib = x.t("n:xTribMun") or x.t("n:xTribNac")
    f.texto(X0 + 0.05, f.y + 0.26, f.caber(_corta(desc_trib, 170), LARG - 0.1), f.cont, 7)
    f.y += 0.38
    # Descrição do serviço: quebra em linhas (até 1300 caracteres)
    desc = _corta(x.d("n:serv/n:cServ/n:xDescServ"), 1300)
    f.texto(X0 + 0.05, f.y + 0.24, "Descrição do Serviço", f.rot_b, 6)
    linhas = []
    for par in desc.splitlines() or [""]:
        linhas += textwrap.wrap(par, 165) or [""]
    for i, ln in enumerate(linhas[:14]):
        f.texto(X0 + 0.05, f.y + 0.54 + i * 0.30, f.caber(ln, LARG - 0.1), f.cont, 7)
    f.y += max(ALT_LINHA, 0.30 + 0.30 * len(linhas[:14]) + 0.08)
    f.linha_h(f.y)


def _issqn(f: _Folha, x: _Xml):
    tm = x.no("n:valores/n:trib/n:tribMun", x.dps)
    if tm is None:
        f.faixa("TRIBUTAÇÃO MUNICIPAL (ISSQN) - OPERAÇÃO NÃO SUJEITA AO ISSQN")
        f.linha_h(f.y)
        return
    c_inc = x.t("n:cLocIncid")
    if c_inc:
        incid = f"{x.t('n:xLocIncid')} / {UF_POR_CODIGO.get(c_inc[:2], '')} / -"
    else:
        incid = f"- / - / {x.t('n:cPaisResult', tm) or '-'}"
    f.titulo_bloco("Tributação Municipal (ISSQN)")
    f.campo(1, "Tipo de Tributação do ISSQN", TRIB_ISSQN.get(x.t("n:tribISSQN", tm), ""))
    f.campo(2, "Município / Sigla UF / País de Incidência do ISSQN", incid, span=2)
    f.nova_linha()
    reg_esp = x.d("n:prest/n:regTrib/n:regEspTrib")
    imun = x.t("n:tpImunidade", tm)
    susp = x.t("n:exigSusp/n:tpSusp", tm)
    proc = x.t("n:exigSusp/n:nProcesso", tm)
    if (reg_esp and reg_esp != "0") or imun or susp or proc:      # nota 5
        f.campo(0, "Regime Especial de Tributação", REG_ESP.get(reg_esp, ""))
        f.campo(1, "Tipo de Imunidade do ISSQN", _corta(IMUNIDADE.get(imun, imun), 40) if imun else "")
        f.campo(2, "Suspensão da Exigibilidade do ISSQN", _corta(SUSPENSAO.get(susp, ""), 40))
        f.campo(3, "Número Processo Suspensão", proc)
        f.nova_linha()
    tp_bm = x.t("n:valores/n:tpBM")
    v_bm = x.t("n:valores/n:vCalcBM")
    v_dr = x.t("n:valores/n:vCalcDR") or x.d("n:valores/n:vDedRed/n:vDR")
    v_desc = x.d("n:valores/n:vDescCondIncond/n:vDescIncond")
    if tp_bm or v_bm or v_dr or v_desc:
        f.campo(0, "Benefício Municipal", TP_BM.get(tp_bm, tp_bm))
        f.campo(1, "Cálculo do BM", _moeda(v_bm))
        f.campo(2, "Total Deduções/Reduções", _moeda(v_dr))
        f.campo(3, "Desconto Incondicionado", _moeda(v_desc))
        f.nova_linha()
    f.campo(0, "BC ISSQN", _moeda(x.t("n:valores/n:vBC")))
    f.campo(1, "Alíquota Aplicada", _perc(x.t("n:valores/n:pAliqAplic")))
    f.campo(2, "Retenção do ISSQN", RET_ISSQN.get(x.t("n:tpRetISSQN", tm), ""))
    f.campo(3, "ISSQN Apurado", _moeda(x.t("n:valores/n:vISSQN")))
    f.nova_linha()
    f.linha_h(f.y)


def _federal(f: _Folha, x: _Xml):
    tf = x.no("n:valores/n:trib/n:tribFed", x.dps)
    f.titulo_bloco("Tributação Federal (exceto CBS)")
    f.campo(1, "IRRF", _moeda(x.t("n:vRetIRRF", tf)))
    f.campo(2, "Contribuição Previdenciária - Retida", _moeda(x.t("n:vRetCP", tf)))
    f.campo(3, "Contribuições Sociais - Retidas", _moeda(x.t("n:vRetCSLL", tf)))
    f.nova_linha()
    if x.d("n:dCompet")[:4] <= "2026":                              # nota 6
        f.campo(0, "PIS - Débito Apuração Própria", _moeda(x.t("n:piscofins/n:vPis", tf)))
        f.campo(1, "COFINS - Débito Apuração Própria", _moeda(x.t("n:piscofins/n:vCofins", tf)))
        ret = x.t("n:piscofins/n:tpRetPisCofins", tf)
        f.campo(2, "Descrição Contrib. Sociais - Retidas",
                f"{ret} - {RET_PIS[ret]}" if ret in RET_PIS else "", span=2)
        f.nova_linha()
    f.linha_h(f.y)


def _ibscbs(f: _Folha, x: _Xml):
    g = x.no("n:IBSCBS")
    gd = x.no("n:IBSCBS", x.dps)
    v = lambda c: x.t(c, g)          # noqa: E731
    cst = x.t("n:valores/n:trib/n:gIBSCBS/n:CST", gd)
    ccl = x.t("n:valores/n:trib/n:gIBSCBS/n:cClassTrib", gd)
    loc = v("n:cLocalidadeIncid")
    ind = " / ".join([x.t("n:cIndOp", gd) or "-", loc or "-", v("n:xLocalidadeIncid") or "-",
                      UF_POR_CODIGO.get(loc[:2], "-") if loc else "-"])
    f.titulo_bloco("Tributação IBS / CBS")
    f.campo(1, "CST / cClassTrib", f"{cst or '-'} / {ccl or '-'}")
    f.campo(2, "Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF",
            ind, span=2)
    f.nova_linha()
    soma = Decimal(0)
    for c in (x.d("n:valores/n:vDescCondIncond/n:vDescIncond"), v("n:valores/n:vCalcReeRepRes"),
              x.t("n:valores/n:vISSQN"), x.d("n:valores/n:trib/n:tribFed/n:piscofins/n:vPis"),
              x.d("n:valores/n:trib/n:tribFed/n:piscofins/n:vCofins")):
        if c:
            soma += Decimal(c)
    red = " / ".join(_perc(v(f"n:valores/n:{g_}/n:{c}")) or "-" for g_, c in
                     (("uf", "pRedAliqUF"), ("mun", "pRedAliqMun"), ("fed", "pRedAliqCBS")))
    f.campo(0, "Exclusões e Reduções da Base de Cálculo", _moeda(str(soma)))
    f.campo(1, "Base de Cálculo Após Exclusões e Reduções", _moeda(v("n:valores/n:vBC")))
    f.campo(2, "Red. Alíquota IBS / Red. Alíquota CBS", red)
    f.campo(3, "Alíquota - IBS UF / IBS Mun",
            f"{_perc(v('n:valores/n:uf/n:pIBSUF')) or '-'} / {_perc(v('n:valores/n:mun/n:pIBSMun')) or '-'}")
    f.nova_linha()
    f.campo(0, "Alíq. Efetiva Municipal - IBS", _perc(v("n:valores/n:mun/n:pAliqEfetMun")))
    f.campo(1, "Valor Apurado Municipal - IBS", _moeda(v("n:totCIBS/n:gIBS/n:gIBSMunTot/n:vIBSMun")))
    f.campo(2, "Alíq. Efetiva Estadual - IBS", _perc(v("n:valores/n:uf/n:pAliqEfetUF")))
    f.campo(3, "Valor Apurado Estadual - IBS", _moeda(v("n:totCIBS/n:gIBS/n:gIBSUFTot/n:vIBSUF")))
    f.nova_linha()
    f.campo(0, "Valor Total Apurado - IBS", _moeda(v("n:totCIBS/n:gIBS/n:vIBSTot")))
    f.campo(1, "Alíquota - CBS", _perc(v("n:valores/n:fed/n:pCBS")))
    f.campo(2, "Alíquota Efetiva - CBS", _perc(v("n:valores/n:fed/n:pAliqEfetCBS")))
    f.campo(3, "Valor Total Apurado - CBS", _moeda(v("n:totCIBS/n:gCBS/n:vCBS")))
    f.nova_linha()
    f.linha_h(f.y)


def _totais(f: _Folha, x: _Xml):
    g = x.no("n:IBSCBS")
    ibs = x.t("n:totCIBS/n:gIBS/n:vIBSTot", g)
    cbs = x.t("n:totCIBS/n:gCBS/n:vCBS", g)
    tot_ibscbs = str(Decimal(ibs or 0) + Decimal(cbs or 0))
    f.titulo_bloco("Valor Total da NFS-e", 0.67)
    f.campo(1, "Valor da Operação / Serviço", _moeda(x.d("n:valores/n:vServPrest/n:vServ")))
    f.campo(2, "Desconto Incondicionado", _moeda(x.d("n:valores/n:vDescCondIncond/n:vDescIncond")))
    f.campo(3, "Desconto Condicionado", _moeda(x.d("n:valores/n:vDescCondIncond/n:vDescCond")))
    f.nova_linha(0.67)
    f.caixa(COLS[3], f.y, LCOL, 0.67, fundo=CINZA, borda=False)    # item 2.2.3
    f.campo(0, "Total das Retenções (ISSQN / Federais)", _moeda(x.t("n:valores/n:vTotalRet")))
    f.campo(1, "Valor Líquido da NFS-e", _moeda(x.t("n:valores/n:vLiq")))
    f.campo(2, "Total do IBS/CBS", _moeda(tot_ibscbs))
    f.campo(3, "Valor Líquido da NFS-e + IBS/CBS", _moeda(x.t("n:totCIBS/n:vTotNF", g)))
    f.nova_linha(0.67)
    f.linha_h(f.y)


def _totais_aproximados(x: _Xml) -> str:
    tt = x.no("n:valores/n:trib/n:totTrib", x.dps)
    fed = est = mun = "-"
    if tt is not None:
        if tt.find("n:vTotTrib", N) is not None:
            fed, est, mun = (_moeda(x.t(f"n:vTotTrib/n:{c}", tt)) or "-"
                             for c in ("vTotTribFed", "vTotTribEst", "vTotTribMun"))
        elif tt.find("n:pTotTrib", N) is not None:
            fed, est, mun = (_perc(x.t(f"n:pTotTrib/n:{c}", tt)) or "-"
                             for c in ("pTotTribFed", "pTotTribEst", "pTotTribMun"))
    return (f"Totais aproximados dos Tributos cfe. Lei n° 12.741/2012: Federais: {fed}; "
            f"Estaduais: {est}; Municipais: {mun};")


def _complementares(f: _Folha, x: _Xml, canhoto: bool):
    ic = x.no("n:serv/n:infoCompl", x.dps)
    partes = []
    for rot, val in (
            ("Inf. Cont.:", x.t("n:xInfComp", ic)),
            ("NFS-e Subst.:", x.d("n:subst/n:chSubstda")),
            ("Doc. Ref.:", x.t("n:docRef", ic)),
            ("Cod. Obra:", x.d("n:serv/n:obra/n:cObra")),
            ("Insc. Imob.:", x.d("n:serv/n:obra/n:inscImobFisc") or x.d("n:IBSCBS/n:imovel/n:inscImobFisc")),
            ("Cod. Evt.:", x.d("n:serv/n:atvEvento/n:idAtvEvt")),
            ("Doc. Tec.:", x.t("n:idDocTec", ic)),
            ("Núm. Ped.:", x.t("n:xPed", ic)),
            ("Item Ped.:", ", ".join(e.text or "" for e in (ic.findall("n:gItemPed/n:xItemPed", N)
                                                            if ic is not None else []))),
            ("Inf. A. T. Mun.:", x.t("n:xOutInf"))):
        if val:
            partes.append(f"{rot} {val}")
    texto = _corta(" | ".join(partes), 1997)
    f.caixa(X0, f.y, LARG, 0.39, fundo=CINZA, borda=False)
    f.texto(X0 + 0.05, f.y + 0.28, "INFORMAÇÕES COMPLEMENTARES", f.rot_b, 7)
    f.y += 0.39
    f.linha_h(f.y)
    linhas = []
    for par in texto.splitlines():
        linhas += textwrap.wrap(par, 165) or [""]
    linhas.append(_totais_aproximados(x))
    y = f.y + 0.35
    limite = (28.10 if canhoto else 29.30) - 0.15
    for ln in linhas:
        if y > limite:
            break
        f.texto(X0 + 0.05, y, f.caber(ln, LARG - 0.1), f.cont, 7)
        y += 0.30
    f.y = 28.10 if canhoto else 29.40


def _canhoto(f: _Folha, x: _Xml, chave: str):
    f.linha_h(f.y)
    f.c.setLineWidth(0.5)
    for col in (1, 2):
        xx = COLS[col] * cm
        f.c.line(xx, f._Y(f.y), xx, f._Y(f.y + 0.67))
    f.campo(0, "Data Cientificação", " ", rot_maiusc=True)
    f.campo(1, "Identificação e Assinatura", " ", rot_maiusc=True)
    f.campo(2, "Nº NFS-e / Chave NFS-e", f"{x.t('n:nNFSe')} / {chave}", span=2, rot_maiusc=True)
    f.y += 0.67


def _marca(c: canvas.Canvas, texto: str):
    arial = _fontes()[0]
    c.saveState()
    c.setFillColor(CINZA_MARCA)
    c.setFont(arial, 90)
    c.translate(A4[0] / 2, A4[1] / 2)
    c.rotate(45)
    c.drawCentredString(0, -30, texto)
    c.restoreState()
