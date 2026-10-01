"""Regras de negócio do Anexo I checadas antes do envio.

Só as que dá para conferir sem consultar o sistema; o resto a Sefin devolve.
Cada mensagem cita o código de rejeição correspondente.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from .dps import DPS, so_digitos

OBRIGATORIA, PROIBIDA, OPCIONAL = "obrigatoria", "proibida", "opcional"


def aliquota_exigida(op_simp_nac: str, reg_ap_trib_sn: str, reg_esp_trib: str,
                     trib_issqn: str, tp_ret_issqn: str,
                     convenio_ativo: bool | None) -> str:
    """Se pAliq deve, não pode ou pode ser informado (RNs E0600 a E0640).

    convenio_ativo=None (desconhecido) devolve OPCIONAL nos casos que dependem dele.
    """
    if op_simp_nac == "2":
        return PROIBIDA                                   # E0600 (MEI)
    if trib_issqn in ("2", "3", "4"):
        return PROIBIDA                                   # E0602
    if reg_esp_trib not in ("", "0"):
        return PROIBIDA                                   # E0604
    retido = tp_ret_issqn in ("2", "3")
    if op_simp_nac == "1":
        if convenio_ativo is None:
            return OPCIONAL
        return PROIBIDA if convenio_ativo else OBRIGATORIA   # E0617 / E0619
    if op_simp_nac == "3":
        if reg_ap_trib_sn in ("", "1"):
            return OBRIGATORIA if retido else PROIBIDA       # E0621..E0631
        if convenio_ativo is None:
            return OPCIONAL
        return PROIBIDA if convenio_ativo else OBRIGATORIA   # E0635 / E0640
    return OPCIONAL


def validar_negocio(dps: DPS, convenio_ativo: bool | None = None) -> list[str]:
    erros: list[str] = []
    p, v = dps.prestador, dps.valores
    hoje = dt.date.today()

    # Faixas de série (Anexo I): 1-49999 aplicativo próprio, 50000-69999 emissor móvel,
    # 70000-79999 emissor web (portal), 80000-89999 transcrição manual.
    if not 1 <= int(so_digitos(str(dps.serie)) or 0) <= 49999:
        erros.append("E0010: aplicativo próprio usa série de 1 a 49999 "
                     "(70000-79999 é a série do Emissor Web do portal).")
    if dps.d_compet and dps.d_compet > hoje:
        erros.append("E0015: a competência não pode ser posterior à data de emissão.")
    if v.v_serv is None or Decimal(v.v_serv) <= 0:
        erros.append("O valor do serviço deve ser maior que zero.")
    desc = Decimal(v.v_desc_incond or 0) + Decimal(v.v_desc_cond or 0)
    if v.v_serv is not None and desc > Decimal(v.v_serv):
        erros.append("Descontos maiores que o valor do serviço.")
    if p.reg_ap_trib_sn and p.op_simp_nac != "3":
        erros.append("E0162: regApTribSN só existe para optante ME/EPP (opSimpNac = 3).")
    if p.op_simp_nac == "3" and not p.reg_ap_trib_sn:
        erros.append("Informe o regime de apuração do Simples Nacional (regApTribSN).")
    if v.tp_ret_issqn in ("2", "3"):
        if v.trib_issqn in ("2", "3", "4"):
            erros.append("E0580: sem retenção quando há imunidade, exportação ou não incidência.")
        if p.op_simp_nac == "2":
            erros.append("E0583: MEI não pode ter ISSQN retido.")
        if p.reg_esp_trib not in ("", "0"):
            erros.append("E0588: regime especial de tributação não admite retenção.")
        if v.tp_ret_issqn == "2" and not dps.tomador:
            erros.append("Retenção pelo tomador exige o tomador identificado.")
        if v.tp_ret_issqn == "3" and not dps.intermediario:
            erros.append("Retenção pelo intermediário exige o intermediário identificado.")
    if v.p_aliq is not None and Decimal(v.p_aliq) > 5:
        erros.append("E0595: alíquota não pode passar de 5%.")

    exig = aliquota_exigida(p.op_simp_nac, p.reg_ap_trib_sn, p.reg_esp_trib,
                            v.trib_issqn, v.tp_ret_issqn, convenio_ativo)
    if exig == PROIBIDA and v.p_aliq is not None:
        erros.append("A alíquota (pAliq) não pode ser informada nesta situação.")
    if exig == OBRIGATORIA and v.p_aliq is None:
        erros.append("A alíquota (pAliq) é obrigatória nesta situação.")

    if len(so_digitos(p.documento)) == 11 and not v.trib_fed.vazio():
        erros.append("E0675: prestador pessoa física não informa tributos federais.")
    if dps.ibscbs:
        if dps.versao < "1.01":
            erros.append("E0854: IBS/CBS só a partir do leiaute 1.01.")
        if dps.d_compet and dps.d_compet < dt.date(2026, 1, 1):
            erros.append("E0850: IBS/CBS só para competência a partir de 01/01/2026.")
    if dps.tomador and not so_digitos(dps.tomador.documento) and dps.tomador.nif \
            and not dps.tomador.nome:
        erros.append("E0233: tomador com NIF exige nome.")
    return erros
