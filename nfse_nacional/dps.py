"""Montagem do XML da DPS (Declaração de Prestação de Serviço), leiaute 1.01.

A ordem dos elementos segue o XSD (tiposComplexos_v1.01.xsd); validar com
validacao.validar_dps() antes de assinar evita rejeição por schema.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from lxml import etree

from . import VERSAO
from .config import NS_NFSE, VERSAO_LEIAUTE

FUSO_BRASILIA = dt.timezone(dt.timedelta(hours=-3))


# --------------------------------------------------------------------- utilidades

def so_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def texto(valor: str | None) -> str:
    """TSString não aceita espaço nas pontas nem espaços repetidos."""
    return re.sub(r"[ \t]+", " ", (valor or "").strip())


def dec2(valor) -> str:
    """Decimal com 2 casas no formato dos tipos TSDec*V2 ("0.00" e não "0")."""
    d = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:.2f}"


def montar_id_dps(c_mun: str, documento: str, serie: str | int, n_dps: str | int) -> str:
    doc = so_digitos(documento)
    tp_insc = "2" if len(doc) == 14 else "1"
    return ("DPS" + so_digitos(c_mun).zfill(7) + tp_insc + doc.zfill(14)
            + str(int(serie)).zfill(5) + str(int(n_dps)).zfill(15))


def agora_brasilia(margem_s: int = 60) -> dt.datetime:
    """dhEmi não pode ser posterior ao processamento (E0008): recua uma margem."""
    return (dt.datetime.now(FUSO_BRASILIA) - dt.timedelta(seconds=margem_s)).replace(microsecond=0)


# --------------------------------------------------------------------- modelos

@dataclass
class Endereco:
    c_mun: str = ""          # IBGE 7 dígitos (endereço nacional)
    cep: str = ""
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    # Exterior (se c_pais for preenchido, o endereço é tratado como estrangeiro)
    c_pais: str = ""
    cod_postal: str = ""
    cidade: str = ""
    estado: str = ""


@dataclass
class Pessoa:
    """Tomador ou intermediário."""
    documento: str = ""      # CNPJ ou CPF; vazio + nif => estrangeiro
    nome: str = ""
    im: str = ""
    nif: str = ""
    c_nao_nif: str = ""      # motivo de não informar o NIF (0, 1, 2)
    endereco: Endereco | None = None
    fone: str = ""
    email: str = ""


@dataclass
class Prestador:
    documento: str           # CNPJ ou CPF
    op_simp_nac: str = "1"   # 1 não optante, 2 MEI, 3 ME/EPP
    reg_ap_trib_sn: str = "" # só para op_simp_nac = 3
    reg_esp_trib: str = "0"
    im: str = ""
    fone: str = ""
    email: str = ""


@dataclass
class Servico:
    c_trib_nac: str                  # 6 dígitos (item+subitem+desdobro)
    descricao: str
    c_loc_prestacao: str = ""        # IBGE; vazio => usa c_loc_emi
    c_pais_prestacao: str = ""
    c_trib_mun: str = ""
    c_nbs: str = ""
    c_int_contrib: str = ""
    x_ped: str = ""
    info_complementar: str = ""


@dataclass
class TributosFederais:
    cst_pis_cofins: str = ""         # vazio => grupo piscofins omitido
    v_bc_pis_cofins: Decimal | None = None
    p_aliq_pis: Decimal | None = None
    p_aliq_cofins: Decimal | None = None
    v_pis: Decimal | None = None
    v_cofins: Decimal | None = None
    tp_ret_pis_cofins: str = ""
    v_ret_cp: Decimal | None = None
    v_ret_irrf: Decimal | None = None
    v_ret_csll: Decimal | None = None

    def vazio(self) -> bool:
        return not self.cst_pis_cofins and all(
            v is None for v in (self.v_ret_cp, self.v_ret_irrf, self.v_ret_csll))


@dataclass
class Valores:
    v_serv: Decimal
    v_desc_incond: Decimal | None = None
    v_desc_cond: Decimal | None = None
    trib_issqn: str = "1"            # 1 tributável, 2 imunidade, 3 exportação, 4 não incidência
    tp_imunidade: str = ""
    tp_ret_issqn: str = "1"          # 1 não retido, 2 tomador, 3 intermediário
    p_aliq: Decimal | None = None    # ver regras.aliquota_obrigatoria()
    trib_fed: TributosFederais = field(default_factory=TributosFederais)
    # Totais aproximados (Lei 12.741). O tipo usado depende do regime: ver _tot_trib().
    p_tot_trib_fed: Decimal = Decimal("0")
    p_tot_trib_est: Decimal = Decimal("0")
    p_tot_trib_mun: Decimal = Decimal("0")
    p_tot_trib_sn: Decimal = Decimal("0")


@dataclass
class IBSCBS:
    c_ind_op: str                    # Anexo C, 6 dígitos
    cst: str                         # 3 dígitos
    c_class_trib: str                # 6 dígitos
    ind_final: str = "0"
    ind_dest: str = "0"              # 0 = destinatário é o próprio tomador
    fin_nfse: str = "0"


@dataclass
class DPS:
    c_loc_emi: str                   # IBGE do município emissor
    serie: str
    n_dps: int
    prestador: Prestador
    servico: Servico
    valores: Valores
    tomador: Pessoa | None = None
    intermediario: Pessoa | None = None
    ibscbs: IBSCBS | None = None
    tp_amb: str = "2"
    d_compet: dt.date | None = None
    dh_emi: dt.datetime | None = None
    tp_emit: str = "1"
    ver_aplic: str = f"NFSE_Nacional {VERSAO}"
    versao: str = VERSAO_LEIAUTE
    # Substituição de NFS-e (gera cancelamento por substituição da original)
    ch_substituida: str = ""
    c_motivo_subst: str = ""
    x_motivo_subst: str = ""

    @property
    def id(self) -> str:
        return montar_id_dps(self.c_loc_emi, self.prestador.documento, self.serie, self.n_dps)


# --------------------------------------------------------------------- XML

def _sub(pai, nome: str, valor=None):
    el = etree.SubElement(pai, f"{{{NS_NFSE}}}{nome}")
    if valor is not None:
        el.text = str(valor)
    return el


def _opcional(pai, nome: str, valor):
    if valor not in (None, ""):
        _sub(pai, nome, valor)


def _doc_pessoa(pai, doc: str, nif: str = "", c_nao_nif: str = ""):
    d = so_digitos(doc)
    if len(d) == 14:
        _sub(pai, "CNPJ", d)
    elif len(d) == 11:
        _sub(pai, "CPF", d)
    elif nif:
        _sub(pai, "NIF", texto(nif))
    elif c_nao_nif:
        _sub(pai, "cNaoNIF", c_nao_nif)
    else:
        raise ValueError(f"Documento inválido (CNPJ/CPF/NIF): {doc!r}")


def _endereco(pai, end: Endereco):
    e = _sub(pai, "end")
    if end.c_pais:
        ext = _sub(e, "endExt")
        _sub(ext, "cPais", end.c_pais.upper())
        _sub(ext, "cEndPost", texto(end.cod_postal))
        _sub(ext, "xCidade", texto(end.cidade))
        _sub(ext, "xEstProvReg", texto(end.estado))
    else:
        nac = _sub(e, "endNac")
        _sub(nac, "cMun", so_digitos(end.c_mun))
        _sub(nac, "CEP", so_digitos(end.cep))
    _sub(e, "xLgr", texto(end.logradouro))
    _sub(e, "nro", texto(end.numero) or "S/N")
    _opcional(e, "xCpl", texto(end.complemento))
    _sub(e, "xBairro", texto(end.bairro))


def _pessoa(pai, tag: str, p: Pessoa):
    el = _sub(pai, tag)
    _doc_pessoa(el, p.documento, p.nif, p.c_nao_nif)
    _opcional(el, "IM", texto(p.im))
    _sub(el, "xNome", texto(p.nome))
    if p.endereco:
        _endereco(el, p.endereco)
    _opcional(el, "fone", so_digitos(p.fone))
    _opcional(el, "email", texto(p.email))


def _prestador(pai, p: Prestador, tp_emit: str):
    el = _sub(pai, "prest")
    _doc_pessoa(el, p.documento)
    _opcional(el, "IM", texto(p.im))
    # Com tpEmit = 1 o nome (E0121) e o endereço vêm do cadastro nacional.
    _opcional(el, "fone", so_digitos(p.fone))
    _opcional(el, "email", texto(p.email))
    reg = _sub(el, "regTrib")
    _sub(reg, "opSimpNac", p.op_simp_nac)
    if p.op_simp_nac == "3" and p.reg_ap_trib_sn:
        _sub(reg, "regApTribSN", p.reg_ap_trib_sn)
    _sub(reg, "regEspTrib", p.reg_esp_trib or "0")


def _servico(pai, s: Servico, c_loc_emi: str):
    el = _sub(pai, "serv")
    loc = _sub(el, "locPrest")
    if s.c_pais_prestacao:
        _sub(loc, "cPaisPrestacao", s.c_pais_prestacao.upper())
    else:
        _sub(loc, "cLocPrestacao", so_digitos(s.c_loc_prestacao or c_loc_emi))
    cs = _sub(el, "cServ")
    _sub(cs, "cTribNac", so_digitos(s.c_trib_nac).zfill(6))
    _opcional(cs, "cTribMun", so_digitos(s.c_trib_mun))
    _sub(cs, "xDescServ", s.descricao.strip())
    _opcional(cs, "cNBS", so_digitos(s.c_nbs))
    _opcional(cs, "cIntContrib", texto(s.c_int_contrib))
    if s.x_ped or s.info_complementar:
        ic = _sub(el, "infoCompl")
        _opcional(ic, "xPed", texto(s.x_ped))
        _opcional(ic, "xInfComp", s.info_complementar.strip())


def _tot_trib(pai, v: Valores, op_simp_nac: str):
    """RNs E0710/E0712/E0713: o choice de totTrib depende do regime."""
    tot = _sub(pai, "totTrib")
    if op_simp_nac == "3":
        _sub(tot, "pTotTribSN", dec2(v.p_tot_trib_sn))
    elif op_simp_nac == "2":
        _sub(tot, "indTotTrib", "0")
    else:
        p = _sub(tot, "pTotTrib")
        _sub(p, "pTotTribFed", dec2(v.p_tot_trib_fed))
        _sub(p, "pTotTribEst", dec2(v.p_tot_trib_est))
        _sub(p, "pTotTribMun", dec2(v.p_tot_trib_mun))


def _valores(pai, v: Valores, op_simp_nac: str):
    el = _sub(pai, "valores")
    vs = _sub(el, "vServPrest")
    _sub(vs, "vServ", dec2(v.v_serv))
    if v.v_desc_incond or v.v_desc_cond:
        d = _sub(el, "vDescCondIncond")
        if v.v_desc_incond:
            _sub(d, "vDescIncond", dec2(v.v_desc_incond))
        if v.v_desc_cond:
            _sub(d, "vDescCond", dec2(v.v_desc_cond))
    trib = _sub(el, "trib")
    tm = _sub(trib, "tribMun")
    _sub(tm, "tribISSQN", v.trib_issqn)
    if v.trib_issqn == "2":
        _sub(tm, "tpImunidade", v.tp_imunidade or "0")
    _sub(tm, "tpRetISSQN", v.tp_ret_issqn)
    if v.p_aliq is not None:
        _sub(tm, "pAliq", dec2(v.p_aliq))
    tf = v.trib_fed
    if not tf.vazio():
        f = _sub(trib, "tribFed")
        if tf.cst_pis_cofins:
            pc = _sub(f, "piscofins")
            _sub(pc, "CST", tf.cst_pis_cofins)
            for nome, valor in (("vBCPisCofins", tf.v_bc_pis_cofins),
                                ("pAliqPis", tf.p_aliq_pis),
                                ("pAliqCofins", tf.p_aliq_cofins),
                                ("vPis", tf.v_pis), ("vCofins", tf.v_cofins)):
                if valor is not None:
                    _sub(pc, nome, dec2(valor))
            _opcional(pc, "tpRetPisCofins", tf.tp_ret_pis_cofins)
        for nome, valor in (("vRetCP", tf.v_ret_cp), ("vRetIRRF", tf.v_ret_irrf),
                            ("vRetCSLL", tf.v_ret_csll)):
            if valor is not None:
                _sub(f, nome, dec2(valor))
    _tot_trib(trib, v, op_simp_nac)


def _ibscbs(pai, g: IBSCBS):
    el = _sub(pai, "IBSCBS")
    _sub(el, "finNFSe", g.fin_nfse)
    _opcional(el, "indFinal", g.ind_final)
    _sub(el, "cIndOp", so_digitos(g.c_ind_op).zfill(6))
    _sub(el, "indDest", g.ind_dest)
    val = _sub(el, "valores")
    trib = _sub(val, "trib")
    gi = _sub(trib, "gIBSCBS")
    _sub(gi, "CST", so_digitos(g.cst).zfill(3))
    _sub(gi, "cClassTrib", so_digitos(g.c_class_trib).zfill(6))


def gerar_xml(dps: DPS) -> etree._Element:
    """Elemento <DPS> sem assinatura."""
    dh = dps.dh_emi or agora_brasilia()
    compet = dps.d_compet or dh.date()
    raiz = etree.Element(f"{{{NS_NFSE}}}DPS", nsmap={None: NS_NFSE})
    raiz.set("versao", dps.versao)
    inf = _sub(raiz, "infDPS")
    inf.set("Id", dps.id)
    _sub(inf, "tpAmb", dps.tp_amb)
    _sub(inf, "dhEmi", dh.isoformat(timespec="seconds"))
    _sub(inf, "verAplic", dps.ver_aplic[:20])
    _sub(inf, "serie", str(int(dps.serie)))
    _sub(inf, "nDPS", str(int(dps.n_dps)))
    _sub(inf, "dCompet", compet.isoformat())
    _sub(inf, "tpEmit", dps.tp_emit)
    _sub(inf, "cLocEmi", so_digitos(dps.c_loc_emi))
    if dps.ch_substituida:
        s = _sub(inf, "subst")
        _sub(s, "chSubstda", dps.ch_substituida)
        _sub(s, "cMotivo", dps.c_motivo_subst or "99")
        _opcional(s, "xMotivo", texto(dps.x_motivo_subst))
    _prestador(inf, dps.prestador, dps.tp_emit)
    if dps.tomador:
        _pessoa(inf, "toma", dps.tomador)
    if dps.intermediario:
        _pessoa(inf, "interm", dps.intermediario)
    _servico(inf, dps.servico, dps.c_loc_emi)
    _valores(inf, dps.valores, dps.prestador.op_simp_nac)
    if dps.ibscbs:
        _ibscbs(inf, dps.ibscbs)
    return raiz


def para_bytes(el: etree._Element) -> bytes:
    """Serialização sem quebras nem indentação (o hash da assinatura depende disso)."""
    return etree.tostring(el, xml_declaration=True, encoding="UTF-8")
