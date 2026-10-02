"""Orquestração: emitir, reconsultar, cancelar, sincronizar com o ADN, DANFSe.

Fluxo de emissão (idempotente):
    valida regras e schema -> reserva nDPS -> grava nota 'pendente' com a DPS
    -> POST /nfse -> 'autorizada' | 'rejeitada'
    Falha de rede/5xx -> consulta GET /dps/{id}; sem resposta -> 'indefinida'
    (reconsultar() resolve depois, sem nunca reenviar a mesma DPS às cegas).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

import requests

from . import assinatura, eventos, leitor, regras, validacao
from .banco import Banco, Empresa, Tomador
from .certificado import Certificado
from .cliente_adn import ClienteADN
from .cliente_http import ErroApi, campo, sessao_mtls
from .cliente_sefin import ClienteSefin
from .config import ambiente as obter_ambiente
from .dps import (DPS, IBSCBS, Endereco, Pessoa, Prestador, Servico,
                  TributosFederais, Valores, gerar_xml, para_bytes, so_digitos)

TIPOS_CANCELAMENTO = {"101101", "105102", "105104", "305101"}


class ErroValidacao(ValueError):
    def __init__(self, erros: list[str]):
        self.erros = erros
        super().__init__("\n".join(erros))


@dataclass
class DadosNota:
    """O que a tela/CLI preenche; o resto vem do cadastro da empresa."""
    descricao: str
    v_serv: Decimal
    tomador: Tomador | None = None
    d_compet: dt.date | None = None
    c_trib_nac: str = ""
    c_trib_mun: str = ""
    c_nbs: str = ""
    c_loc_prestacao: str = ""
    p_aliq: Decimal | None = None
    usar_aliquota_padrao: bool = True
    tp_ret_issqn: str = "1"
    trib_issqn: str = "1"
    v_desc_incond: Decimal | None = None
    v_desc_cond: Decimal | None = None
    info_complementar: str = ""
    trib_fed: TributosFederais = field(default_factory=TributosFederais)
    incluir_ibscbs: bool = True
    p_tot_trib_sn: Decimal | None = None      # None = padrão da empresa (muda todo mês no SN)


@dataclass
class Resultado:
    nota_id: int
    situacao: str
    chave: str = ""
    numero: str = ""
    mensagem: str = ""


def _tomador_de_dps(inf, N) -> Tomador | None:
    toma = inf.find("n:toma", N)
    if toma is None:
        return None
    t = lambda c: (toma.findtext(c, namespaces=N) or "").strip()      # noqa: E731
    doc = t("n:CNPJ") or t("n:CPF")
    if not doc:
        return None
    return Tomador(documento=doc, nome=t("n:xNome"), im=t("n:IM"), email=t("n:email"),
                   fone=t("n:fone"), c_mun=t("n:end/n:endNac/n:cMun"),
                   cep=t("n:end/n:endNac/n:CEP"), logradouro=t("n:end/n:xLgr"),
                   numero=t("n:end/n:nro"), complemento=t("n:end/n:xCpl"),
                   bairro=t("n:end/n:xBairro"))


def dados_de_xml(xml: bytes) -> DadosNota:
    """Dados de uma nota existente (NFS-e ou DPS) para duplicar numa emissão nova."""
    from lxml import etree

    from .config import NS_NFSE
    N = {"n": NS_NFSE}
    raiz = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    inf = raiz.find(".//n:infDPS", N)
    if inf is None:
        raise ValueError("XML sem DPS.")
    t = lambda c: (inf.findtext(c, namespaces=N) or "").strip()      # noqa: E731
    return DadosNota(
        descricao=t("n:serv/n:cServ/n:xDescServ"),
        v_serv=_dec(t("n:valores/n:vServPrest/n:vServ")) or Decimal(0),
        tomador=_tomador_de_dps(inf, N),
        c_trib_nac=t("n:serv/n:cServ/n:cTribNac"), c_trib_mun=t("n:serv/n:cServ/n:cTribMun"),
        c_nbs=t("n:serv/n:cServ/n:cNBS"),
        c_loc_prestacao=t("n:serv/n:locPrest/n:cLocPrestacao"),
        p_aliq=_dec(t("n:valores/n:trib/n:tribMun/n:pAliq")),
        tp_ret_issqn=t("n:valores/n:trib/n:tribMun/n:tpRetISSQN") or "1",
        trib_issqn=t("n:valores/n:trib/n:tribMun/n:tribISSQN") or "1",
        v_desc_incond=_dec(t("n:valores/n:vDescCondIncond/n:vDescIncond")),
        info_complementar=t("n:serv/n:infoCompl/n:xInfComp"))


def tomadores_de_notas(banco: Banco, empresa_id: int) -> int:
    """Cadastra os tomadores das notas emitidas (inclusive as do portal) que ainda não existem."""
    n = 0
    for r in banco.con.execute(
            "SELECT nfse_xml, dps_xml FROM notas WHERE empresa_id=? AND origem='emitida' "
            "AND situacao IN ('autorizada','cancelada') ORDER BY d_compet", (empresa_id,)):
        xml = r["nfse_xml"] or r["dps_xml"]
        if not xml:
            continue
        try:
            tom = dados_de_xml(xml).tomador
        except Exception:      # noqa: BLE001 - XML estranho não impede o resto
            continue
        if tom and not banco.tomador(tom.documento):
            banco.salvar_tomador(tom)
            n += 1
    return n


@dataclass
class ParametrosMunicipio:
    ativo: bool
    aliquota: Decimal | None
    aliquota_desde: str
    c_trib_nac: str
    bruto: dict

    def texto(self, municipio: str) -> str:
        t = (f"{municipio}: convênio ATIVO no Sistema Nacional NFS-e." if self.ativo else
             f"{municipio}: convênio NÃO está ativo no Sistema Nacional NFS-e.")
        if self.aliquota is not None:
            desde = "/".join(reversed(self.aliquota_desde.split("-"))) if self.aliquota_desde else ""
            pct = f"{self.aliquota:.2f}".replace(".", ",")
            t += (f"\nAlíquota do ISS do serviço {self.c_trib_nac[:2]}.{self.c_trib_nac[2:4]}."
                  f"{self.c_trib_nac[4:6]}: {pct}%" + (f" (desde {desde})" if desde else "") + ".")
        elif self.c_trib_nac:
            t += "\nO município não informou alíquota para este serviço."
        return t


@dataclass
class ResumoImportacao:
    importados: int = 0
    ja_existiam: int = 0
    erros: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        t = f"{self.importados} documento(s) importado(s)"
        if self.ja_existiam:
            t += f", {self.ja_existiam} já existia(m)"
        if self.erros:
            t += f", {len(self.erros)} com erro"
        return t + "."


def marca_dagua(banco: Banco, nota) -> str:
    """CANCELADA / SUBSTITUÍDA para o DANFSe (NT 008, item 2.5)."""
    if nota["situacao"] != "cancelada" or not nota["chave"]:
        return ""
    tipos = {ev["tipo"] for ev in banco.eventos(nota["chave"])}
    return "SUBSTITUÍDA" if "105102" in tipos else "CANCELADA"


def _chave_do_xml(xml: bytes) -> str:
    m = re.search(rb'Id="NFS(\d{50})"', xml)
    return m.group(1).decode() if m else ""


EXTENSOES = (".xml", ".pdf")


def _expandir_arquivos(caminhos):
    """(nome, função que lê os bytes) para cada XML/PDF em arquivos, pastas e .zip."""
    import zipfile
    from pathlib import Path
    for c in caminhos:
        p = Path(c)
        if p.is_dir():
            yield from _expandir_arquivos(sorted(x for x in p.rglob("*")
                                                 if x.suffix.lower() in EXTENSOES + (".zip",)))
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for nome in z.namelist():
                    if nome.lower().endswith(EXTENSOES):
                        dado = z.read(nome)
                        yield f"{p.name}/{nome}", (lambda d=dado: d)
        elif p.suffix.lower() in EXTENSOES:
            yield p.name, (lambda x=p: x.read_bytes())


def _dec(texto: str | None) -> Decimal | None:
    texto = (texto or "").strip().replace(",", ".")
    return Decimal(texto) if texto else None


class Emissor:
    def __init__(self, banco: Banco, empresa: Empresa, certificado: Certificado,
                 sessao: requests.Session | None = None, algoritmo: str = "sha1",
                 usuario: str = "desktop", ip: str = ""):
        self.banco = banco
        self.usuario = usuario          # quem opera (auditoria)
        self.ip = ip
        self.empresa = empresa
        self.cert = certificado
        self.amb = obter_ambiente(empresa.ambiente)
        self.algoritmo = algoritmo
        self._sessao = sessao

    @property
    def sessao(self) -> requests.Session:
        if self._sessao is None:
            self._sessao = sessao_mtls(self.cert)
        return self._sessao

    @property
    def sefin(self) -> ClienteSefin:
        return ClienteSefin(self.sessao, self.amb)

    @property
    def adn(self) -> ClienteADN:
        return ClienteADN(self.sessao, self.amb)

    # ------------------------------------------------------------ montagem
    def montar_dps(self, d: DadosNota, n_dps: int = 1) -> DPS:
        e = self.empresa
        tomador = None
        if d.tomador:
            t = d.tomador
            end = None
            if t.c_mun and t.cep and t.logradouro and t.bairro:
                end = Endereco(c_mun=t.c_mun, cep=t.cep, logradouro=t.logradouro,
                               numero=t.numero, complemento=t.complemento, bairro=t.bairro)
            tomador = Pessoa(documento=t.documento, nome=t.nome, im=t.im, endereco=end,
                             fone=t.fone, email=t.email)
        p_aliq = d.p_aliq
        if p_aliq is None and d.usar_aliquota_padrao:
            exig = regras.aliquota_exigida(
                e.op_simp_nac, e.reg_ap_trib_sn, e.reg_esp_trib, d.trib_issqn,
                d.tp_ret_issqn, None if e.convenio_ativo is None else bool(e.convenio_ativo))
            if exig != regras.PROIBIDA:
                p_aliq = _dec(e.p_aliq)
        ibs = None
        if d.incluir_ibscbs and e.ibs_c_ind_op and e.ibs_cst and e.ibs_c_class_trib:
            ibs = IBSCBS(c_ind_op=e.ibs_c_ind_op, cst=e.ibs_cst, c_class_trib=e.ibs_c_class_trib)
        return DPS(
            c_loc_emi=e.c_mun, serie=e.serie, n_dps=n_dps, tp_amb=self.amb.tp_amb,
            d_compet=d.d_compet,
            prestador=Prestador(documento=e.cnpj, op_simp_nac=e.op_simp_nac,
                                reg_ap_trib_sn=e.reg_ap_trib_sn if e.op_simp_nac == "3" else "",
                                reg_esp_trib=e.reg_esp_trib, im=e.im, fone=e.fone, email=e.email),
            tomador=tomador,
            servico=Servico(c_trib_nac=d.c_trib_nac or e.c_trib_nac, descricao=d.descricao,
                            c_trib_mun=d.c_trib_mun or e.c_trib_mun, c_nbs=d.c_nbs or e.c_nbs,
                            c_loc_prestacao=d.c_loc_prestacao,
                            info_complementar=d.info_complementar),
            valores=Valores(v_serv=d.v_serv, v_desc_incond=d.v_desc_incond,
                            v_desc_cond=d.v_desc_cond, trib_issqn=d.trib_issqn,
                            tp_ret_issqn=d.tp_ret_issqn, p_aliq=p_aliq, trib_fed=self._trib_fed(d),
                            p_tot_trib_fed=_dec(e.p_tot_fed) or Decimal(0),
                            p_tot_trib_est=_dec(e.p_tot_est) or Decimal(0),
                            p_tot_trib_mun=_dec(e.p_tot_mun) or Decimal(0),
                            p_tot_trib_sn=(d.p_tot_trib_sn if d.p_tot_trib_sn is not None
                                           else _dec(e.p_tot_sn) or Decimal(0))),
            ibscbs=ibs,
        )

    def _trib_fed(self, d: DadosNota) -> TributosFederais:
        """Sem dados de tributos federais, o ME/EPP vai como o Emissor Web do portal faz:
        PIS/COFINS CST 00 e "0 - PIS/COFINS/CSLL Não Retidos" (aparece no DANFSe)."""
        if d.trib_fed.vazio() and self.empresa.op_simp_nac == "3"                 and len(so_digitos(self.empresa.cnpj)) == 14:
            return TributosFederais(cst_pis_cofins="00", tp_ret_pis_cofins="0")
        return d.trib_fed

    def preparar(self, dps: DPS) -> bytes:
        """Valida regras + schema, assina e devolve o XML pronto para envio."""
        conv = None if self.empresa.convenio_ativo is None else bool(self.empresa.convenio_ativo)
        erros = regras.validar_negocio(dps, conv)
        if not self.empresa.c_mun:
            erros.append("Cadastre o município (IBGE) da empresa.")
        if not so_digitos(dps.servico.c_trib_nac):
            erros.append("Informe o código de tributação nacional (cTribNac).")
        if erros:
            raise ErroValidacao(erros)
        try:
            raiz = gerar_xml(dps)
            validacao.validar_dps(raiz)                 # antes de assinar: erro legível
            assinatura.assinar(raiz, "infDPS", self.cert, self.algoritmo)
            validacao.validar_dps(raiz)
        except validacao.ErroSchema as erro:
            raise ErroValidacao(erro.erros) from None
        return para_bytes(raiz)

    # ------------------------------------------------------------ emissão
    def emitir(self, dados: DadosNota) -> Resultado:
        e = self.empresa
        # Valida com número provisório para não queimar número em erro de digitação.
        self.preparar(self.montar_dps(dados, 1))
        n = self.banco.reservar_numero(e.id, e.ambiente, e.serie)
        dps = self.montar_dps(dados, n)
        xml = self.preparar(dps)
        if dados.tomador and so_digitos(dados.tomador.documento):
            self.banco.salvar_tomador(dados.tomador)
        nota_id = self.banco.inserir_nota(
            empresa_id=e.id, ambiente=e.ambiente, origem="emitida", situacao="pendente",
            serie=e.serie, n_dps=n, id_dps=dps.id,
            d_compet=(dps.d_compet or dt.date.today()).isoformat(),
            dh_emissao=dt.datetime.now().isoformat(timespec="seconds"),
            prestador_doc=e.cnpj, prestador_nome=e.razao,
            tomador_doc=dados.tomador.documento if dados.tomador else "",
            tomador_nome=dados.tomador.nome if dados.tomador else "",
            descricao=dados.descricao, v_serv=str(dados.v_serv), dps_xml=xml)
        r = self._enviar(nota_id, dps.id, xml)
        self.banco.auditar(self.usuario, "emitir",
                           f"DPS {e.serie}/{n} R$ {dados.v_serv} -> {r.situacao} {r.mensagem or ''}".strip(),
                           r.chave, self.ip)
        return r

    def _enviar(self, nota_id: int, id_dps: str, xml: bytes) -> Resultado:
        try:
            resp = self.sefin.emitir(xml)
        except ErroApi as erro:
            if erro.status >= 500:
                return self._recuperar(nota_id, id_dps, str(erro))
            self.banco.atualizar_nota(nota_id, situacao="rejeitada", mensagem=str(erro))
            return Resultado(nota_id, "rejeitada", mensagem=str(erro))
        except requests.RequestException as erro:
            return self._recuperar(nota_id, id_dps, f"Falha de comunicação: {erro}")
        alertas = "; ".join(str(a) for a in resp.alertas)
        return self._autorizar(nota_id, resp.nfse_xml, resp.chave, alertas)

    def _autorizar(self, nota_id: int, nfse_xml: bytes, chave: str = "",
                   mensagem: str = "") -> Resultado:
        r = leitor.ler_nfse(nfse_xml)
        self.banco.atualizar_nota(
            nota_id, situacao="autorizada", chave=chave or r.chave, numero=r.numero,
            v_liq=str(r.v_liq), v_issqn=str(r.v_issqn) if r.v_issqn is not None else None,
            tomador_nome=r.tomador_nome or None, nfse_xml=nfse_xml, mensagem=mensagem or None)
        return Resultado(nota_id, "autorizada", chave or r.chave, r.numero, mensagem)

    def _recuperar(self, nota_id: int, id_dps: str, motivo: str) -> Resultado:
        try:
            chave = self.sefin.chave_por_dps(id_dps)
            if chave:
                return self._autorizar(nota_id, self.sefin.consultar_nfse(chave), chave)
        except (ErroApi, requests.RequestException) as erro:
            motivo = f"{motivo} | consulta da DPS falhou: {erro}"
        self.banco.atualizar_nota(nota_id, situacao="indefinida", mensagem=motivo)
        return Resultado(nota_id, "indefinida", mensagem=motivo)

    def reconsultar(self, nota_id: int) -> Resultado:
        """Resolve nota 'indefinida'/'pendente'; se a DPS não existe na Sefin, reenvia."""
        nota = self.banco.nota(nota_id)
        if nota["situacao"] not in ("indefinida", "pendente"):
            return Resultado(nota_id, nota["situacao"], nota["chave"] or "", nota["numero"] or "")
        chave = self.sefin.chave_por_dps(nota["id_dps"])
        if chave:
            return self._autorizar(nota_id, self.sefin.consultar_nfse(chave), chave)
        return self._enviar(nota_id, nota["id_dps"], nota["dps_xml"])

    # ------------------------------------------------------------ cancelamento
    def cancelar(self, nota_id: int, c_motivo: str, x_motivo: str) -> bytes:
        nota = self.banco.nota(nota_id)
        if not nota or not nota["chave"]:
            raise ValueError("Só dá para cancelar nota autorizada (com chave).")
        if nota["situacao"] == "cancelada":
            raise ValueError("Nota já cancelada.")
        raiz = eventos.pedido_cancelamento(nota["chave"], self.empresa.cnpj, c_motivo,
                                           x_motivo, tp_amb=self.amb.tp_amb)
        try:
            validacao.validar_ped_reg_evento(raiz)
            assinatura.assinar(raiz, "infPedReg", self.cert, self.algoritmo)
            validacao.validar_ped_reg_evento(raiz)
        except validacao.ErroSchema as erro:
            raise ErroValidacao(erro.erros) from None
        xml_evento = self.sefin.registrar_evento(nota["chave"], para_bytes(raiz))
        ev = leitor.ler_evento(xml_evento)
        self.banco.inserir_evento(nota["chave"], ev.tipo or eventos.TIPO_CANCELAMENTO,
                                  ev.descricao, ev.dh_proc, xml_evento)
        self.banco.atualizar_nota(nota_id, situacao="cancelada",
                                  mensagem=f"Cancelada: {x_motivo}")
        self.banco.auditar(self.usuario, "cancelar", f"motivo {c_motivo}: {x_motivo}",
                           nota["chave"], self.ip)
        return xml_evento

    # ------------------------------------------------------------ ADN
    def sincronizar(self, progresso: Callable[[str], None] | None = None,
                    max_lotes: int = 200) -> int:
        """Baixa do ADN tudo a partir do último NSU (emitidas e recebidas). Devolve a contagem."""
        e = self.empresa
        avisar = progresso or (lambda _m: None)
        ultimo = self.banco.ultimo_nsu(e.id, e.ambiente)
        total = 0
        for _ in range(max_lotes):
            lote = self.adn.distribuicao(ultimo + 1, cnpj_consulta=e.cnpj)
            novos = [d for d in lote.documentos if d.nsu > ultimo]
            if not novos:
                break
            for doc in sorted(novos, key=lambda d: d.nsu):
                self._guardar_documento(doc.xml, doc.nsu)
                ultimo = doc.nsu
                total += 1
            self.banco.gravar_nsu(e.id, e.ambiente, ultimo)
            avisar(f"NSU {ultimo}: {total} documento(s) baixado(s)")
            if lote.maior_nsu is not None and ultimo >= lote.maior_nsu:
                break
        return total

    def _guardar_documento(self, xml: bytes, nsu: int | None = None):
        tipo = leitor.tipo_documento(xml)
        e = self.empresa
        if tipo == "NFSe":
            r = leitor.ler_nfse(xml)
            origem = "emitida" if so_digitos(r.emitente_doc) == e.cnpj else "recebida"
            if origem == "emitida":
                tom = dados_de_xml(xml).tomador
                if tom and not self.banco.tomador(tom.documento):
                    self.banco.salvar_tomador(tom)
            # Nota nossa que ficou 'indefinida' ainda não tem chave: casa pelo Id da DPS.
            existente = self.banco.nota_por_chave(r.chave) or (
                self.banco.con.execute(
                    "SELECT * FROM notas WHERE id_dps=? AND chave IS NULL", (r.id_dps,)).fetchone()
                if r.id_dps else None)
            campos = dict(chave=r.chave, numero=r.numero, d_compet=r.d_compet,
                          prestador_doc=r.emitente_doc, prestador_nome=r.emitente_nome,
                          tomador_doc=r.tomador_doc, tomador_nome=r.tomador_nome,
                          descricao=r.descricao, v_serv=str(r.v_serv), v_liq=str(r.v_liq),
                          v_issqn=str(r.v_issqn) if r.v_issqn is not None else None,
                          nfse_xml=xml)
            if existente:
                if existente["situacao"] != "cancelada":
                    campos["situacao"] = "autorizada"
                self.banco.atualizar_nota(existente["id"], **campos)
            else:
                cancelada = any(ev["tipo"] in TIPOS_CANCELAMENTO for ev in self.banco.eventos(r.chave))
                self.banco.inserir_nota(empresa_id=e.id, ambiente=e.ambiente, origem=origem,
                                        situacao="cancelada" if cancelada else "autorizada",
                                        dh_emissao=r.dh_proc, id_dps=r.id_dps or None, **campos)
        elif tipo in ("evento", "Evento"):
            ev = leitor.ler_evento(xml)
            self.banco.inserir_evento(ev.chave, ev.tipo, ev.descricao, ev.dh_proc, xml, nsu)
            if ev.tipo in TIPOS_CANCELAMENTO:
                nota = self.banco.nota_por_chave(ev.chave)
                if nota:
                    self.banco.atualizar_nota(nota["id"], situacao="cancelada",
                                              mensagem=ev.descricao)

    def importar_xml(self, xml: bytes):
        """Importa um XML de NFS-e ou evento (ex.: baixado no portal)."""
        self._guardar_documento(xml)

    def importar_arquivos(self, caminhos, progresso: Callable[[str], None] | None = None
                          ) -> "ResumoImportacao":
        """Importa XMLs, PDFs de DANFSe e .zip (com XML/PDF dentro), arquivos ou pastas.

        XML entra direto. PDF não tem os dados estruturados: o app lê a chave de acesso no
        texto do DANFSe e baixa o XML oficial da Sefin (precisa de certificado e internet).
        """
        avisar = progresso or (lambda _m: None)
        resumo = ResumoImportacao()
        itens = list(_expandir_arquivos(caminhos))
        for i, (nome, ler) in enumerate(itens, 1):
            avisar(f"Importando {i}/{len(itens)}: {nome}")
            try:
                dado = ler()
                if nome.lower().endswith(".pdf"):
                    chaves = leitor.chaves_em_pdf(dado)
                    if not chaves:
                        raise ValueError("não encontrei a chave de acesso no PDF")
                    for chave in chaves:
                        if self.banco.nota_por_chave(chave):
                            resumo.ja_existiam += 1
                            continue
                        self._guardar_documento(self.sefin.consultar_nfse(chave))
                        self._eventos_da_chave(chave)
                        resumo.importados += 1
                else:
                    chave = _chave_do_xml(dado)
                    if chave and self.banco.nota_por_chave(chave) and \
                            leitor.tipo_documento(dado) == "NFSe":
                        resumo.ja_existiam += 1
                        continue
                    self._guardar_documento(dado)
                    resumo.importados += 1
            except Exception as erro:      # noqa: BLE001 - segue com os demais
                resumo.erros.append(f"{nome}: {erro}")
        return resumo

    def _eventos_da_chave(self, chave: str):
        """Cancelamentos de uma nota importada por PDF (sem eles ela pareceria autorizada)."""
        try:
            for ev in self.adn.eventos(chave):
                self._guardar_documento(ev)
        except (ErroApi, requests.RequestException):
            pass

    def danfse(self, nota_id: int) -> bytes:
        """DANFSe gerado localmente (NT 008/2026: a API do ADN foi suspensa em 07/2026)."""
        from .danfse import gerar_pdf
        nota = self.banco.nota(nota_id)
        if not nota or not nota["chave"]:
            raise ValueError("Nota sem chave de acesso.")
        xml = nota["nfse_xml"]
        if not xml:
            xml = self.sefin.consultar_nfse(nota["chave"])
            self.banco.atualizar_nota(nota_id, nfse_xml=xml)
        return gerar_pdf(xml, marca_dagua(self.banco, nota))

    def parametros_municipio(self, c_trib_nac: str = "", c_trib_mun: str = "") -> "ParametrosMunicipio":
        """Convênio do município (ativo no Ambiente Nacional?) e alíquota do ISS do serviço."""
        e = self.empresa
        conv = campo(self.adn.parametros_convenio(e.c_mun), "parametrosConvenio", padrao={}) or {}
        ativo = bool(campo(conv, "aderenteAmbienteNacional")) and \
            str(campo(conv, "situacaoEmissaoPadraoContribuintesRFB", padrao="")) == "1"
        aliq = None
        desde = ""
        c_trib_nac = c_trib_nac or e.c_trib_nac
        if c_trib_nac:
            hoje = dt.date.today().isoformat()
            vigentes = [a for a in self.adn.aliquotas(e.c_mun, c_trib_nac, c_trib_mun or e.c_trib_mun, hoje)
                        if str(campo(a, "Incidencia", padrao="SIM")).upper() == "SIM"]
            if vigentes:
                atual = max(vigentes, key=lambda a: str(campo(a, "DtIni", padrao="")))
                aliq = Decimal(str(campo(atual, "Aliq")))
                desde = str(campo(atual, "DtIni", padrao=""))[:10]
        return ParametrosMunicipio(ativo=ativo, aliquota=aliq, aliquota_desde=desde,
                                   c_trib_nac=c_trib_nac, bruto=conv)
