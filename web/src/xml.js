// Leitura dos XMLs da NFS-e Nacional (NFSe e evento) sem depender de prefixo de namespace.
// Recebe um Document (DOMParser no navegador, @xmldom/xmldom nos testes).

/** Primeiro filho direto com o nome local informado. */
function filho(el, nome) {
  if (!el) return null;
  for (let n = el.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 1 && (n.localName || n.nodeName.split(":").pop()) === nome) return n;
  }
  return null;
}

/** Elemento no caminho "a/b/c" a partir de el (filhos diretos). */
export function no(el, caminho) {
  let atual = el;
  for (const parte of caminho.split("/")) {
    atual = filho(atual, parte);
    if (!atual) return null;
  }
  return atual;
}

/** Texto (aparado) no caminho, ou "". */
export function t(el, caminho) {
  const n = caminho ? no(el, caminho) : el;
  return n ? (n.textContent || "").trim() : "";
}

/** Todos os filhos diretos com o nome. */
export function todos(el, nome) {
  const r = [];
  if (!el) return r;
  for (let n = el.firstChild; n; n = n.nextSibling) {
    if (n.nodeType === 1 && (n.localName || n.nodeName.split(":").pop()) === nome) r.push(n);
  }
  return r;
}

/** Descendente em qualquer profundidade (primeiro achado). */
export function busca(el, nome) {
  if (!el) return null;
  const lista = el.getElementsByTagNameNS ? el.getElementsByTagNameNS("*", nome) : null;
  if (lista && lista.length) return lista[0];
  return null;
}

/** Tipo do documento: "NFSe", "evento" ou outro (nome local da raiz). */
export function tipo(doc) {
  const r = doc.documentElement;
  return r ? (r.localName || r.nodeName.split(":").pop()) : "";
}

const CANCELAMENTOS = { "101101": "CANCELADA", "105104": "CANCELADA", "305101": "CANCELADA", "105102": "SUBSTITUÍDA" };

/** {chave, tipo, marca} de um XML de evento; marca é "", "CANCELADA" ou "SUBSTITUÍDA". */
export function lerEvento(doc) {
  const inf = busca(doc, "infPedReg");
  if (!inf) throw new Error("XML não é um evento de NFS-e.");
  let codigo = "", descricao = "";
  for (let n = inf.firstChild; n; n = n.nextSibling) {
    const nome = n.nodeType === 1 ? (n.localName || n.nodeName) : "";
    if (/^e\d{6}$/.test(nome)) { codigo = nome.slice(1); descricao = t(n, "xDesc"); }
  }
  return { chave: t(inf, "chNFSe"), tipo: codigo, descricao, marca: CANCELAMENTOS[codigo] || "" };
}

/** Resumo de uma NFS-e para listagem. */
export function resumir(doc) {
  const inf = busca(doc, "infNFSe");
  if (!inf) throw new Error("XML não é uma NFS-e (infNFSe ausente).");
  const dps = no(inf, "DPS/infDPS");
  const toma = no(dps, "toma");
  const emit = no(inf, "emit");
  return {
    chave: (inf.getAttribute("Id") || "").slice(3),
    numero: t(inf, "nNFSe"),
    dhProc: t(inf, "dhProc"),
    competencia: t(dps, "dCompet"),
    ambiente: t(dps, "tpAmb") === "2" ? "Homologação (sem valor)" : "Produção",
    prestadorDoc: t(emit, "CNPJ") || t(emit, "CPF"),
    prestador: t(emit, "xNome"),
    tomadorDoc: t(toma, "CNPJ") || t(toma, "CPF") || t(toma, "NIF"),
    tomador: t(toma, "xNome"),
    descricao: t(dps, "serv/cServ/xDescServ"),
    valor: t(dps, "valores/vServPrest/vServ"),
    liquido: t(inf, "valores/vLiq"),
    iss: t(inf, "valores/vISSQN"),
    municipio: t(inf, "xLocEmi"),
  };
}
