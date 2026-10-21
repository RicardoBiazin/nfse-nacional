// DANFSe v2.0 no navegador, a partir do XML da NFS-e (NT SE/CGNFS-e 008/2026).
// Porte de nfse_nacional/danfse.py (o mesmo layout do app desktop): A4 retrato, página
// única, medidas em cm a partir do canto superior esquerdo (tabela do item 2.4.5 da NT).
// A API de DANFSe do governo foi suspensa em 07/2026; a NT manda o emissor gerar.
//
// Fonte: Helvetica (embutida no PDF, mesmas métricas da Arial pedida pela NT).
import { jsPDF } from "jspdf";
import qrcode from "qrcode-generator";
import { busca, no, t, todos } from "./xml.js";

const URL_CONSULTA = "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave=";
const X0 = 0.30, LARG = 20.40;
const COLS = [0.30, 5.41, 10.51, 15.62];
const LCOL = 5.09;
const ALT_LINHA = 0.63;
const PT = 2.54 / 72;                 // 1 ponto em cm
const CINZA = [242, 242, 242];        // sombreamento 5 %
const ALTURA_UTIL = 29.10;

export const UF_POR_CODIGO = {
  11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE",
  24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP",
  41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
};
const uf = (c) => UF_POR_CODIGO[String(c).slice(0, 2)] || "";

const TP_EMIT = { 1: "Prestador", 2: "Tomador", 3: "Intermediário" };
const C_STAT = { 100: "NFS-e Gerada", 101: "NFS-e de Substituição Gerada", 102: "NFS-e de Decisão Judicial", 103: "NFS-e Avulsa" };
const FIN_NFSE = { 0: "NFS-e regular" };
const AMB_GER = { 1: "Prefeitura", 2: "Sistema Nacional NFS-e" };
const TP_AMB = { 1: "Produção", 2: "Homologação" };
const OP_SIMP = { 1: "Não Optante", 2: "Optante - Microempreendedor Individual (MEI)", 3: "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)" };
const REG_AP_SN = {
  1: "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
  2: "Regime de apuração dos tributos federais pelo SN e ISSQN por fora do SN conforme respectiva legislação municipal do tributo",
  3: "Regime de apuração dos tributos federais e municipal por fora do SN conforme respectivas legislações federal e municipal de cada tributo",
};
const REG_ESP = { 0: "Nenhum", 1: "Ato Cooperado (Cooperativa)", 2: "Estimativa", 3: "Microempresa Municipal", 4: "Notário ou Registrador", 5: "Profissional Autônomo", 6: "Sociedade de Profissionais", 9: "Outros" };
const TRIB_ISSQN = { 1: "Operação Tributável", 2: "Imunidade", 3: "Exportação de Serviço", 4: "Não Incidência" };
const RET_ISSQN = { 1: "Não Retido", 2: "Retido pelo Tomador", 3: "Retido pelo Intermediário" };
const IMUNIDADE = { 0: "Imunidade (tipo não informado)", 1: "Patrimônio, renda ou serviços, uns dos outros", 2: "Templos de qualquer culto", 3: "Partidos, sindicatos, educação e assistência social", 4: "Livros, jornais, periódicos e o papel destinado a sua impressão", 5: "Fonogramas e videofonogramas musicais" };
const SUSPENSAO = { 1: "Exigibilidade Suspensa por Decisão Judicial", 2: "Exigibilidade Suspensa por Processo Administrativo" };
const TP_BM = { 1: "Isenção", 2: "Redução da BC em percentual", 3: "Redução da BC em valor", 4: "Alíquota diferenciada" };
const RET_PIS = { 0: "PIS/COFINS/CSLL Não Retidos", 1: "PIS/COFINS Retidos", 2: "PIS/COFINS Não Retidos", 3: "PIS/COFINS/CSLL Retidos", 4: "PIS/COFINS Retidos, CSLL Não Retido", 5: "PIS Retido, COFINS/CSLL Não Retido", 6: "COFINS Retido, PIS/CSLL Não Retido", 7: "PIS Não Retido, COFINS/CSLL Retidos", 8: "PIS/COFINS Não Retidos, CSLL Retido", 9: "COFINS Não Retido, PIS/CSLL Retidos" };

// ------------------------------------------------------------------ formatação
export function cnpjCpf(v) {
  if (/^\d{14}$/.test(v)) return `${v.slice(0, 2)}.${v.slice(2, 5)}.${v.slice(5, 8)}/${v.slice(8, 12)}-${v.slice(12)}`;
  if (/^\d{11}$/.test(v)) return `${v.slice(0, 3)}.${v.slice(3, 6)}.${v.slice(6, 9)}-${v.slice(9)}`;
  return v;
}
const cep = (v) => (/^\d{8}$/.test(v) ? `${v.slice(0, 2)}.${v.slice(2, 5)}-${v.slice(5)}` : v);
const fone = (v) => (/^\d{10,11}$/.test(v) ? `(${v.slice(0, 2)}) ${v.slice(2, -4)}-${v.slice(-4)}` : v);
export function data(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : v || "";
}
export function dataHora(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(v || "");
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}:${m[6]}` : v || "";
}
export function moeda(v) {
  if (v === "" || v === null || v === undefined) return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const [int, dec] = Math.abs(n).toFixed(2).split(".");
  return `R$ ${n < 0 ? "-" : ""}${int.replace(/\B(?=(\d{3})+(?!\d))/g, ".")},${dec}`;
}
const perc = (v) => (v ? `${Number(v).toFixed(2).replace(".", ",")} %` : "");
const tribNac = (v) => (v.length === 6 ? `${v.slice(0, 2)}.${v.slice(2, 4)}.${v.slice(4, 6)}` : v);
const nbs = (v) => (v.length === 9 ? `${v[0]}.${v.slice(1, 5)}.${v.slice(5, 7)}.${v.slice(7, 9)}` : v);
const corta = (s, lim) => (s.length <= lim ? s : s.slice(0, lim - 3) + "...");

/** Quebra por palavras em linhas de até n caracteres (como textwrap.wrap). */
function quebrar(texto, n) {
  const linhas = [];
  for (const par of String(texto).split(/\r?\n/)) {
    let atual = "";
    for (const palavra of par.split(/\s+/).filter(Boolean)) {
      if (!atual) atual = palavra;
      else if ((atual + " " + palavra).length <= n) atual += " " + palavra;
      else { linhas.push(atual); atual = palavra; }
      while (atual.length > n) { linhas.push(atual.slice(0, n)); atual = atual.slice(n); }
    }
    linhas.push(atual);
  }
  return linhas;
}

// ------------------------------------------------------------------ folha
class Folha {
  constructor(doc) {
    this.d = doc;
    this.y = 0;
  }
  fonte(negrito, tam) {
    this.d.setFont("helvetica", negrito ? "bold" : "normal");
    this.d.setFontSize(tam);
  }
  caixa(x, y, w, h, fundo) {
    this.d.setFillColor(...fundo);
    this.d.rect(x, y, w, h, "F");
    this.d.setFillColor(0, 0, 0);
  }
  linhaH(y) {
    this.d.setLineWidth(0.5 * PT);
    this.d.line(X0, y, X0 + LARG, y);
  }
  texto(x, y, s, { negrito = false, tam = 7, cor = [0, 0, 0], centroW = null } = {}) {
    this.fonte(negrito, tam);
    this.d.setTextColor(...cor);
    if (centroW !== null) this.d.text(String(s), x + centroW / 2, y, { align: "center" });
    else this.d.text(String(s), x, y);
    this.d.setTextColor(0, 0, 0);
  }
  caber(s, largura, tam = 7, negrito = false) {
    this.fonte(negrito, tam);
    const max = largura - 4 * PT;
    s = String(s);
    if (this.d.getTextWidth(s) <= max) return s;
    while (s && this.d.getTextWidth(s + "...") > max) s = s.slice(0, -1);
    return s + "...";
  }
  campo(col, rotulo, valor, { span = 1, maiusc = false } = {}) {
    const x = COLS[col] + 0.05;
    const w = LCOL * span + (span - 1) * 0.02 - 0.1;
    this.texto(x, this.y + 0.24, maiusc ? rotulo.toUpperCase() : rotulo, { negrito: true, tam: 6 });
    this.texto(x, this.y + 0.54, this.caber(valor || "-", w));
  }
  tituloBloco(titulo, alt = ALT_LINHA) {
    this.caixa(COLS[0], this.y, LCOL, alt, CINZA);
    this.texto(COLS[0] + 0.05, this.y + 0.24, titulo.toUpperCase(), { negrito: true, tam: 7 });
  }
  faixa(msg, alt = 0.32) {
    this.linhaH(this.y);
    this.texto(X0, this.y + 0.23, msg, { negrito: true, tam: 6.5, centroW: LARG });
    this.y += alt;
  }
  novaLinha(alt = ALT_LINHA) { this.y += alt; }
}

// ------------------------------------------------------------------ blocos
function docDe(el) {
  if (!el) return "";
  return cnpjCpf(t(el, "CNPJ") || t(el, "CPF")) || t(el, "NIF");
}

function endereco(end, nomeMunicipio) {
  if (!end) return ["", "", ""];
  const lgr = [t(end, "xLgr"), t(end, "nro"), t(end, "xCpl"), t(end, "xBairro")].filter(Boolean).join(", ");
  const ext = no(end, "endExt");
  if (ext) return [t(ext, "xCidade"), t(ext, "cEndPost"), lgr];
  const cMun = t(end, "endNac/cMun") || t(end, "cMun");
  const c = t(end, "endNac/CEP") || t(end, "CEP");
  return [nomeMunicipio(cMun), cMun ? `${cMun} / ${cep(c)}` : cep(c), lgr];
}

function pessoa(f, titulo, el, nomeMunicipio, { comIm = true } = {}) {
  const [mun, ibgeCep, end] = endereco(no(el, "end"), nomeMunicipio);
  f.tituloBloco(titulo);
  f.campo(1, "CNPJ / CPF / NIF", docDe(el));
  if (comIm) f.campo(2, "Indicador Municipal (Inscrição)", t(el, "IM"));
  f.campo(3, "Telefone", fone(t(el, "fone")));
  f.novaLinha();
  f.campo(0, "Nome / Nome Empresarial", t(el, "xNome"), { span: 2 });
  f.campo(2, "Município / Sigla UF", mun);
  f.campo(3, "Código IBGE / CEP", ibgeCep);
  f.novaLinha();
  f.campo(0, "Endereço", end, { span: 2 });
  f.campo(2, "E-mail", t(el, "email"), { span: 2 });
  f.novaLinha();
  f.linhaH(f.y);
}

function cabecalho(f, inf, dps, logo) {
  f.y = 0.30;
  f.caixa(X0, f.y, LARG, 1.16, CINZA);
  if (logo) f.d.addImage(logo, "PNG", 0.49, 0.44, 4.0, 0.81);
  f.texto(5.41, 0.70, "DANFSe v2.0", { negrito: true, tam: 9, centroW: 10.19 });
  f.texto(5.41, 1.05, "Documento Auxiliar da NFS-e", { negrito: true, tam: 9, centroW: 10.19 });
  if (t(dps, "tpAmb") === "2") {
    f.texto(5.41, 1.40, "NFS-e SEM VALIDADE JURÍDICA", { negrito: true, tam: 9, cor: [217, 0, 0], centroW: 10.19 });
  }
  const cMun = t(inf, "emit/enderNac/cMun");
  const sigla = t(inf, "emit/enderNac/UF") || uf(cMun);
  if (!t(dps, "serv/cServ/cTribNac").startsWith("99")) {
    f.texto(15.62, 0.62, `Município: ${t(inf, "xLocEmi")} - ${sigla}`, { tam: 8 });
  }
  f.texto(15.62, 1.00, `Ambiente Gerador: ${AMB_GER[t(inf, "ambGer")] || t(inf, "ambGer")}`, { tam: 6 });
  f.texto(15.62, 1.25, `Tipo de Ambiente: ${TP_AMB[t(dps, "tpAmb")] || t(dps, "tpAmb")}`, { tam: 6 });
  f.y = 1.48;
  f.linhaH(f.y);
}

function qr(f, texto, x, y, lado) {
  const q = qrcode(0, "M");
  q.addData(texto);
  q.make();
  const n = q.getModuleCount();
  const m = lado / n;
  f.d.setFillColor(0, 0, 0);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) if (q.isDark(r, c)) f.d.rect(x + c * m, y + r * m, m + 0.001, m + 0.001, "F");
  }
}

function identificacao(f, inf, dps, chave) {
  const y0 = f.y;
  f.texto(X0 + 0.05, y0 + 0.30, "CHAVE DE ACESSO DA NFS-e", { negrito: true });
  f.texto(X0 + 0.05, y0 + 0.62, chave);
  const linhas = [
    [["NÚMERO DA NFS-e", t(inf, "nNFSe")], ["COMPETÊNCIA DA NFS-e", data(t(dps, "dCompet"))],
      ["DATA E HORA DA EMISSÃO DA NFS-e", dataHora(t(inf, "dhProc"))]],
    [["NÚMERO DA DPS", t(dps, "nDPS")], ["SÉRIE DA DPS", t(dps, "serie")],
      ["DATA E HORA DA EMISSÃO DA DPS", dataHora(t(dps, "dhEmi"))]],
    [["EMITENTE DA NFS-e", TP_EMIT[t(dps, "tpEmit")] || ""],
      ["SITUAÇÃO DA NFS-e", corta(C_STAT[t(inf, "cStat")] || t(inf, "cStat"), 40)],
      ["FINALIDADE", FIN_NFSE[t(dps, "IBSCBS/finNFSe")] || "-"]],
  ];
  let y = y0 + 0.79;
  linhas.forEach((linha, i) => {
    if (i === 2) f.caixa(COLS[0], y, LCOL, 0.67, CINZA);
    linha.forEach(([rot, val], col) => {
      f.texto(COLS[col] + 0.05, y + 0.26, rot, { negrito: true });
      f.texto(COLS[col] + 0.05, y + 0.56, val || "-");
    });
    y += 0.69;
  });
  qr(f, URL_CONSULTA + chave, 17.48, 1.67, 1.52);
  ["A autenticidade desta NFS-e pode ser verificada", "pela leitura deste código QR ou pela consulta da",
    "chave de acesso no portal nacional da NFS-e"].forEach((ln, i) => f.texto(15.80, 3.50 + i * 0.22, ln, { tam: 6 }));
  f.y = y0 + 2.86;
  f.linhaH(f.y);
}

function prestador(f, inf, dps, nomeMunicipio) {
  const prest = no(dps, "prest");
  const emit = no(inf, "emit");
  if (t(dps, "tpEmit") === "1" && emit) {
    const cMun = t(emit, "enderNac/cMun");
    const end = ["xLgr", "nro", "xCpl", "xBairro"].map((c) => t(emit, `enderNac/${c}`)).filter(Boolean).join(", ");
    f.tituloBloco("Prestador / Fornecedor");
    f.campo(1, "CNPJ / CPF / NIF", docDe(emit));
    f.campo(2, "Indicador Municipal (Inscrição)", t(emit, "IM") || t(prest, "IM"));
    f.campo(3, "Telefone", fone(t(emit, "fone") || t(prest, "fone")));
    f.novaLinha();
    f.campo(0, "Nome / Nome Empresarial", t(emit, "xNome"), { span: 2 });
    f.campo(2, "Município / Sigla UF", nomeMunicipio(cMun));
    f.campo(3, "Código IBGE / CEP", cMun ? `${cMun} / ${cep(t(emit, "enderNac/CEP"))}` : "");
    f.novaLinha();
    f.campo(0, "Endereço", end, { span: 2 });
    f.campo(2, "E-mail", t(emit, "email") || t(prest, "email"), { span: 2 });
    f.novaLinha();
  } else {
    const [mun, ibgeCep, end] = endereco(no(prest, "end"), nomeMunicipio);
    f.tituloBloco("Prestador / Fornecedor");
    f.campo(1, "CNPJ / CPF / NIF", docDe(prest));
    f.campo(2, "Indicador Municipal (Inscrição)", t(prest, "IM"));
    f.campo(3, "Telefone", fone(t(prest, "fone")));
    f.novaLinha();
    f.campo(0, "Nome / Nome Empresarial", t(prest, "xNome"), { span: 2 });
    f.campo(2, "Município / Sigla UF", mun);
    f.campo(3, "Código IBGE / CEP", ibgeCep);
    f.novaLinha();
    f.campo(0, "Endereço", end, { span: 2 });
    f.campo(2, "E-mail", t(prest, "email"), { span: 2 });
    f.novaLinha();
  }
  const reg = no(prest, "regTrib");
  f.campo(0, "Simples Nacional na Data de Competência", corta(OP_SIMP[t(reg, "opSimpNac")] || "", 40));
  f.campo(1, "Regime de Apuração Tributária pelo SN", corta(REG_AP_SN[t(reg, "regApTribSN")] || "", 80), { span: 3 });
  f.novaLinha();
  f.linhaH(f.y);
}

function servico(f, inf, dps, nomeMunicipio) {
  const cTrib = t(dps, "serv/cServ/cTribNac");
  const cTribMun = t(dps, "serv/cServ/cTribMun");
  const loc = t(dps, "serv/locPrest/cLocPrestacao");
  const pais = t(dps, "serv/locPrest/cPaisPrestacao");
  const local = loc ? `${t(inf, "xLocPrestacao") || nomeMunicipio(loc).split(" / ")[0]} / ${uf(loc)} / -` : `- / - / ${pais || "-"}`;
  f.tituloBloco("Serviço Prestado");
  f.campo(1, "Código de Tributação Nacional/Municipal", `${tribNac(cTrib)} / ${cTribMun || "-"}`);
  f.campo(2, "Código da NBS", nbs(t(dps, "serv/cServ/cNBS")));
  f.campo(3, "Local da Prestação / Sigla UF / País", local);
  f.novaLinha();
  f.texto(X0 + 0.05, f.y + 0.26, f.caber(corta(t(inf, "xTribMun") || t(inf, "xTribNac"), 170), LARG - 0.1));
  f.y += 0.38;
  const linhas = quebrar(corta(t(dps, "serv/cServ/xDescServ"), 1300), 165).slice(0, 14);
  f.texto(X0 + 0.05, f.y + 0.24, "Descrição do Serviço", { negrito: true, tam: 6 });
  linhas.forEach((ln, i) => f.texto(X0 + 0.05, f.y + 0.54 + i * 0.30, f.caber(ln, LARG - 0.1)));
  f.y += Math.max(ALT_LINHA, 0.30 + 0.30 * linhas.length + 0.08);
  f.linhaH(f.y);
}

function issqn(f, inf, dps) {
  const tm = no(dps, "valores/trib/tribMun");
  if (!tm) {
    f.faixa("TRIBUTAÇÃO MUNICIPAL (ISSQN) - OPERAÇÃO NÃO SUJEITA AO ISSQN");
    f.linhaH(f.y);
    return;
  }
  const cInc = t(inf, "cLocIncid");
  const incid = cInc ? `${t(inf, "xLocIncid")} / ${uf(cInc)} / -` : `- / - / ${t(tm, "cPaisResult") || "-"}`;
  f.tituloBloco("Tributação Municipal (ISSQN)");
  f.campo(1, "Tipo de Tributação do ISSQN", TRIB_ISSQN[t(tm, "tribISSQN")] || "");
  f.campo(2, "Município / Sigla UF / País de Incidência do ISSQN", incid, { span: 2 });
  f.novaLinha();
  const regEsp = t(dps, "prest/regTrib/regEspTrib");
  const imun = t(tm, "tpImunidade"), susp = t(tm, "exigSusp/tpSusp"), proc = t(tm, "exigSusp/nProcesso");
  if ((regEsp && regEsp !== "0") || imun || susp || proc) {
    f.campo(0, "Regime Especial de Tributação", REG_ESP[regEsp] || "");
    f.campo(1, "Tipo de Imunidade do ISSQN", imun ? corta(IMUNIDADE[imun] || imun, 40) : "");
    f.campo(2, "Suspensão da Exigibilidade do ISSQN", corta(SUSPENSAO[susp] || "", 40));
    f.campo(3, "Número Processo Suspensão", proc);
    f.novaLinha();
  }
  const tpBm = t(inf, "valores/tpBM"), vBm = t(inf, "valores/vCalcBM");
  const vDr = t(inf, "valores/vCalcDR") || t(dps, "valores/vDedRed/vDR");
  const vDesc = t(dps, "valores/vDescCondIncond/vDescIncond");
  if (tpBm || vBm || vDr || vDesc) {
    f.campo(0, "Benefício Municipal", TP_BM[tpBm] || tpBm);
    f.campo(1, "Cálculo do BM", moeda(vBm));
    f.campo(2, "Total Deduções/Reduções", moeda(vDr));
    f.campo(3, "Desconto Incondicionado", moeda(vDesc));
    f.novaLinha();
  }
  f.campo(0, "BC ISSQN", moeda(t(inf, "valores/vBC")));
  f.campo(1, "Alíquota Aplicada", perc(t(inf, "valores/pAliqAplic")));
  f.campo(2, "Retenção do ISSQN", RET_ISSQN[t(tm, "tpRetISSQN")] || "");
  f.campo(3, "ISSQN Apurado", moeda(t(inf, "valores/vISSQN")));
  f.novaLinha();
  f.linhaH(f.y);
}

function federal(f, dps) {
  const tf = no(dps, "valores/trib/tribFed");
  f.tituloBloco("Tributação Federal (exceto CBS)");
  f.campo(1, "IRRF", moeda(t(tf, "vRetIRRF")));
  f.campo(2, "Contribuição Previdenciária - Retida", moeda(t(tf, "vRetCP")));
  f.campo(3, "Contribuições Sociais - Retidas", moeda(t(tf, "vRetCSLL")));
  f.novaLinha();
  if (t(dps, "dCompet").slice(0, 4) <= "2026") {
    f.campo(0, "PIS - Débito Apuração Própria", moeda(t(tf, "piscofins/vPis")));
    f.campo(1, "COFINS - Débito Apuração Própria", moeda(t(tf, "piscofins/vCofins")));
    const ret = t(tf, "piscofins/tpRetPisCofins");
    f.campo(2, "Descrição Contrib. Sociais - Retidas", RET_PIS[ret] ? `${ret} - ${RET_PIS[ret]}` : "", { span: 2 });
    f.novaLinha();
  }
  f.linhaH(f.y);
}

function ibscbs(f, inf, dps) {
  const g = no(inf, "IBSCBS"), gd = no(dps, "IBSCBS");
  const v = (c) => t(g, c);
  const loc = v("cLocalidadeIncid");
  const ind = [t(gd, "cIndOp") || "-", loc || "-", v("xLocalidadeIncid") || "-", loc ? uf(loc) || "-" : "-"].join(" / ");
  f.tituloBloco("Tributação IBS / CBS");
  f.campo(1, "CST / cClassTrib", `${t(gd, "valores/trib/gIBSCBS/CST") || "-"} / ${t(gd, "valores/trib/gIBSCBS/cClassTrib") || "-"}`);
  f.campo(2, "Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF", ind, { span: 2 });
  f.novaLinha();
  let soma = 0;
  for (const c of [t(dps, "valores/vDescCondIncond/vDescIncond"), v("valores/vCalcReeRepRes"), t(inf, "valores/vISSQN"),
    t(dps, "valores/trib/tribFed/piscofins/vPis"), t(dps, "valores/trib/tribFed/piscofins/vCofins")]) {
    if (c) soma += Number(c);
  }
  const red = [["uf", "pRedAliqUF"], ["mun", "pRedAliqMun"], ["fed", "pRedAliqCBS"]].map(([a, b]) => perc(v(`valores/${a}/${b}`)) || "-").join(" / ");
  f.campo(0, "Exclusões e Reduções da Base de Cálculo", moeda(soma));
  f.campo(1, "Base de Cálculo Após Exclusões e Reduções", moeda(v("valores/vBC")));
  f.campo(2, "Red. Alíquota IBS / Red. Alíquota CBS", red);
  f.campo(3, "Alíquota - IBS UF / IBS Mun", `${perc(v("valores/uf/pIBSUF")) || "-"} / ${perc(v("valores/mun/pIBSMun")) || "-"}`);
  f.novaLinha();
  f.campo(0, "Alíq. Efetiva Municipal - IBS", perc(v("valores/mun/pAliqEfetMun")));
  f.campo(1, "Valor Apurado Municipal - IBS", moeda(v("totCIBS/gIBS/gIBSMunTot/vIBSMun")));
  f.campo(2, "Alíq. Efetiva Estadual - IBS", perc(v("valores/uf/pAliqEfetUF")));
  f.campo(3, "Valor Apurado Estadual - IBS", moeda(v("totCIBS/gIBS/gIBSUFTot/vIBSUF")));
  f.novaLinha();
  f.campo(0, "Valor Total Apurado - IBS", moeda(v("totCIBS/gIBS/vIBSTot")));
  f.campo(1, "Alíquota - CBS", perc(v("valores/fed/pCBS")));
  f.campo(2, "Alíquota Efetiva - CBS", perc(v("valores/fed/pAliqEfetCBS")));
  f.campo(3, "Valor Total Apurado - CBS", moeda(v("totCIBS/gCBS/vCBS")));
  f.novaLinha();
  f.linhaH(f.y);
}

function totais(f, inf, dps) {
  const g = no(inf, "IBSCBS");
  const tot = Number(t(g, "totCIBS/gIBS/vIBSTot") || 0) + Number(t(g, "totCIBS/gCBS/vCBS") || 0);
  f.tituloBloco("Valor Total da NFS-e", 0.67);
  f.campo(1, "Valor da Operação / Serviço", moeda(t(dps, "valores/vServPrest/vServ")));
  f.campo(2, "Desconto Incondicionado", moeda(t(dps, "valores/vDescCondIncond/vDescIncond")));
  f.campo(3, "Desconto Condicionado", moeda(t(dps, "valores/vDescCondIncond/vDescCond")));
  f.novaLinha(0.67);
  f.caixa(COLS[3], f.y, LCOL, 0.67, CINZA);
  f.campo(0, "Total das Retenções (ISSQN / Federais)", moeda(t(inf, "valores/vTotalRet")));
  f.campo(1, "Valor Líquido da NFS-e", moeda(t(inf, "valores/vLiq")));
  f.campo(2, "Total do IBS/CBS", moeda(tot));
  // Sem grupo IBSCBS o DANFSe oficial imprime R$ 0,00; mantém igual.
  f.campo(3, "Valor Líquido da NFS-e + IBS/CBS", moeda(t(g, "totCIBS/vTotNF") || "0"));
  f.novaLinha(0.67);
  f.linhaH(f.y);
}

function totaisAproximados(dps) {
  const tt = no(dps, "valores/trib/totTrib");
  let fed = "-", est = "-", mun = "-";
  if (no(tt, "vTotTrib")) [fed, est, mun] = ["vTotTribFed", "vTotTribEst", "vTotTribMun"].map((c) => moeda(t(tt, `vTotTrib/${c}`)) || "-");
  else if (no(tt, "pTotTrib")) [fed, est, mun] = ["pTotTribFed", "pTotTribEst", "pTotTribMun"].map((c) => perc(t(tt, `pTotTrib/${c}`)) || "-");
  return `Totais aproximados dos Tributos cfe. Lei n° 12.741/2012: Federais: ${fed}; Estaduais: ${est}; Municipais: ${mun};`;
}

function complementares(f, inf, dps, canhoto) {
  const ic = no(dps, "serv/infoCompl");
  const partes = [
    ["Inf. Cont.:", t(ic, "xInfComp")], ["NFS-e Subst.:", t(dps, "subst/chSubstda")], ["Doc. Ref.:", t(ic, "docRef")],
    ["Cod. Obra:", t(dps, "serv/obra/cObra")],
    ["Insc. Imob.:", t(dps, "serv/obra/inscImobFisc") || t(dps, "IBSCBS/imovel/inscImobFisc")],
    ["Cod. Evt.:", t(dps, "serv/atvEvento/idAtvEvt")], ["Doc. Tec.:", t(ic, "idDocTec")], ["Núm. Ped.:", t(ic, "xPed")],
    ["Item Ped.:", todos(no(ic, "gItemPed"), "xItemPed").map((e) => e.textContent).join(", ")],
    ["Inf. A. T. Mun.:", t(inf, "xOutInf")],
  ].filter(([, v]) => v).map(([r, v]) => `${r} ${v}`);
  f.caixa(X0, f.y, LARG, 0.39, CINZA);
  f.texto(X0 + 0.05, f.y + 0.28, "INFORMAÇÕES COMPLEMENTARES", { negrito: true });
  f.y += 0.39;
  f.linhaH(f.y);
  const texto = corta(partes.join(" | "), 1997);
  const linhas = texto ? quebrar(texto, 165) : [];
  linhas.push(totaisAproximados(dps));
  let y = f.y + 0.35;
  const limite = (canhoto ? 28.10 : 29.30) - 0.15;
  for (const ln of linhas) {
    if (y > limite) break;
    f.texto(X0 + 0.05, y, f.caber(ln, LARG - 0.1));
    y += 0.30;
  }
  f.y = canhoto ? 28.10 : 29.40;
}

function canhotoBloco(f, inf, chave) {
  f.linhaH(f.y);
  f.d.setLineWidth(0.5 * PT);
  for (const col of [1, 2]) f.d.line(COLS[col], f.y, COLS[col], f.y + 0.67);
  f.campo(0, "Data Cientificação", " ", { maiusc: true });
  f.campo(1, "Identificação e Assinatura", " ", { maiusc: true });
  f.campo(2, "Nº NFS-e / Chave NFS-e", `${t(inf, "nNFSe")} / ${chave}`, { span: 2, maiusc: true });
  f.y += 0.67;
}

function marcaDagua(doc, texto) {
  doc.saveGraphicsState();
  doc.setGState(new doc.GState({ opacity: 0.45 }));
  doc.setTextColor(166, 166, 166);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(90);
  const w = doc.getTextWidth(texto);
  const ang = Math.PI / 4, cx = 10.5, cy = 14.85;
  doc.text(texto, cx - (w / 2) * Math.cos(ang), cy + (w / 2) * Math.sin(ang), { angle: 45 });
  doc.restoreGraphicsState();
  doc.setTextColor(0, 0, 0);
}

/**
 * PDF do DANFSe (Uint8Array).
 * @param {Document} xmlDoc  XML da NFS-e já lido (DOMParser).
 * @param {{logo?: Uint8Array, municipios?: Record<string,string>, marca?: string, canhoto?: boolean}} op
 */
export function gerarDanfse(xmlDoc, { logo = null, municipios = {}, marca = "", canhoto = true } = {}) {
  const inf = busca(xmlDoc, "infNFSe");
  if (!inf) throw new Error("O XML não é de uma NFS-e (infNFSe ausente).");
  const dps = no(inf, "DPS/infDPS");
  if (!dps) throw new Error("NFS-e sem a DPS (infDPS).");
  const nomeMunicipio = (c) => (c ? (municipios[c] ? `${municipios[c]} / ${uf(c)}` : c) : "");
  const chave = (inf.getAttribute("Id") || "").slice(3);
  const doc = new jsPDF({ unit: "cm", format: "a4", orientation: "portrait", compress: true });
  doc.setProperties({ title: `DANFSe ${chave}`, creator: "NFS-e Nacional (web)" });
  const f = new Folha(doc);
  cabecalho(f, inf, dps, logo);
  identificacao(f, inf, dps, chave);
  prestador(f, inf, dps, nomeMunicipio);
  const toma = no(dps, "toma");
  if (toma) pessoa(f, "Tomador / Adquirente", toma, nomeMunicipio);
  else f.faixa("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e");
  const dest = no(dps, "IBSCBS/dest");
  if (dest) pessoa(f, "Destinatário da Operação", dest, nomeMunicipio, { comIm: false });
  else if (t(dps, "IBSCBS/indDest") === "0") f.faixa("O DESTINATÁRIO É O PRÓPRIO TOMADOR/ADQUIRENTE DA OPERAÇÃO");
  else f.faixa("DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e");
  const interm = no(dps, "interm");
  if (interm) pessoa(f, "Intermediário da Operação", interm, nomeMunicipio);
  else { f.faixa("INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e"); f.linhaH(f.y); }
  servico(f, inf, dps, nomeMunicipio);
  issqn(f, inf, dps);
  federal(f, dps);
  ibscbs(f, inf, dps);
  totais(f, inf, dps);
  complementares(f, inf, dps, canhoto);
  if (canhoto) canhotoBloco(f, inf, chave);
  doc.setLineWidth(1 * PT);
  doc.rect(X0, 0.30, LARG, ALTURA_UTIL);
  if (marca) marcaDagua(doc, marca);
  return new Uint8Array(doc.output("arraybuffer"));
}

export { chaveDe };
function chaveDe(xmlDoc) {
  const inf = busca(xmlDoc, "infNFSe");
  return inf ? (inf.getAttribute("Id") || "").slice(3) : "";
}
