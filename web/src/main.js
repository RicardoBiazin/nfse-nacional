// Interface da versão web. Nada sai do navegador: os XMLs são lidos aqui e os PDFs gerados aqui.
import { strFromU8, unzipSync, zipSync } from "fflate";

import { cnpjCpf, dataHora, gerarDanfse, moeda, UF_POR_CODIGO } from "./danfse.js";
import { lerEvento, resumir, tipo } from "./xml.js";
import pacote from "../package.json";

const $ = (id) => document.getElementById(id);
$("versao").textContent = `v${pacote.version}`;

// ------------------------------------------------------------------ abas
function mostrarAba() {
  const nome = (location.hash || "#danfse").slice(1);
  const valida = ["danfse", "codigos", "sobre"].includes(nome) ? nome : "danfse";
  for (const s of document.querySelectorAll(".aba")) s.hidden = s.id !== `aba-${valida}`;
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("ativo", a.dataset.aba === valida);
  if (valida === "codigos") carregarTabela();
}
addEventListener("hashchange", mostrarAba);
mostrarAba();

// ------------------------------------------------------------------ recursos (logo e municípios)
let recursos = null;
async function obterRecursos() {
  if (!recursos) {
    const [logo, municipios] = await Promise.all([
      fetch("/logo_nfse.png").then((r) => r.arrayBuffer()).then((b) => new Uint8Array(b)),
      fetch("/dados/municipios.json").then((r) => r.json()),
    ]);
    recursos = { logo, municipios };
  }
  return recursos;
}

// ------------------------------------------------------------------ DANFSe
/** Notas lidas: {nome, doc, resumo}; marcas por chave vindas dos eventos. */
let notas = [];
const marcas = new Map();

function aviso(texto, tipoAviso = "info") {
  const p = document.createElement("p");
  p.className = `aviso ${tipoAviso}`;
  p.textContent = texto;
  $("mensagens").append(p);
}

function lerXml(texto, nome) {
  const doc = new DOMParser().parseFromString(texto, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) throw new Error(`${nome}: XML inválido.`);
  return doc;
}

async function arquivosParaTextos(arquivos) {
  const saida = [];
  for (const arq of arquivos) {
    const nome = arq.name.toLowerCase();
    if (arq.size > 30 * 1024 * 1024) { aviso(`${arq.name}: grande demais (máx. 30 MB).`, "erro"); continue; }
    if (nome.endsWith(".zip")) {
      const itens = unzipSync(new Uint8Array(await arq.arrayBuffer()), { filter: (f) => f.name.toLowerCase().endsWith(".xml") });
      for (const [n, dados] of Object.entries(itens)) saida.push({ nome: `${arq.name}/${n}`, texto: strFromU8(dados) });
    } else if (nome.endsWith(".xml")) {
      saida.push({ nome: arq.name, texto: await arq.text() });
    } else {
      aviso(`${arq.name}: ignorado (só XML ou ZIP).`, "erro");
    }
  }
  return saida;
}

async function receber(arquivos) {
  $("mensagens").replaceChildren();
  const textos = await arquivosParaTextos(arquivos);
  let novas = 0, eventos = 0;
  for (const { nome, texto } of textos) {
    try {
      const doc = lerXml(texto, nome);
      const t = tipo(doc);
      if (t === "NFSe") {
        const resumo = resumir(doc);
        if (notas.some((n) => n.resumo.chave === resumo.chave)) continue;
        notas.push({ nome, doc, resumo });
        novas++;
      } else if (t === "evento" || t === "pedRegEvento") {
        const ev = lerEvento(doc);
        if (ev.marca) marcas.set(ev.chave, ev.marca);
        eventos++;
      } else {
        aviso(`${nome}: não é XML de NFS-e nem de evento (raiz <${t}>).`, "erro");
      }
    } catch (erro) {
      aviso(`${nome}: ${erro.message}`, "erro");
    }
  }
  if (novas || eventos) aviso(`${novas} nota(s) e ${eventos} evento(s) lidos.`, "ok");
  desenharTabela();
}

function situacao(chave) {
  return marcas.get(chave) || "Autorizada";
}

function desenharTabela() {
  $("resultado").hidden = notas.length === 0;
  $("contagem").textContent = `${notas.length} nota(s)`;
  const corpo = $("linhas");
  corpo.replaceChildren();
  notas.forEach((n, i) => {
    const r = n.resumo;
    const tr = document.createElement("tr");
    const celulas = [r.numero, dataHora(r.dhProc).slice(0, 10), r.prestador, r.tomador || "(sem tomador)",
      moeda(r.valor), situacao(r.chave)];
    celulas.forEach((v, j) => {
      const td = document.createElement("td");
      td.textContent = v;
      if (j === 4) td.className = "num";
      if (j === 5) td.className = situacao(r.chave) === "Autorizada" ? "sit-ok" : "sit-cancelada";
      tr.append(td);
    });
    const acoes = document.createElement("td");
    const b = document.createElement("button");
    b.textContent = "Baixar PDF";
    b.addEventListener("click", () => baixarUma(i));
    acoes.append(b);
    tr.append(acoes);
    tr.title = `Chave ${r.chave}\nPrestador ${cnpjCpf(r.prestadorDoc)}\n${r.descricao}`;
    corpo.append(tr);
  });
}

async function pdfDe(n) {
  const { logo, municipios } = await obterRecursos();
  return gerarDanfse(n.doc, { logo, municipios, marca: marcas.get(n.resumo.chave) || "", canhoto: $("canhoto").checked });
}

function nomePdf(n) {
  return `DANFSe_${n.resumo.numero || "sn"}_${n.resumo.chave}.pdf`;
}

function baixar(bytes, nome, tipoMime) {
  const url = URL.createObjectURL(new Blob([bytes], { type: tipoMime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

async function baixarUma(i) {
  try {
    baixar(await pdfDe(notas[i]), nomePdf(notas[i]), "application/pdf");
  } catch (erro) {
    aviso(`Não foi possível gerar o PDF: ${erro.message}`, "erro");
  }
}

$("baixar-todos").addEventListener("click", async () => {
  const botao = $("baixar-todos");
  botao.disabled = true;
  botao.textContent = "Gerando…";
  try {
    const arquivos = {};
    for (const n of notas) arquivos[nomePdf(n)] = await pdfDe(n);
    baixar(zipSync(arquivos, { level: 0 }), `DANFSe_${notas.length}_notas.zip`, "application/zip");
  } catch (erro) {
    aviso(`Não foi possível gerar os PDFs: ${erro.message}`, "erro");
  } finally {
    botao.disabled = false;
    botao.textContent = "Baixar todos (.zip)";
  }
});

$("limpar").addEventListener("click", () => {
  notas = [];
  marcas.clear();
  $("mensagens").replaceChildren();
  $("arquivos").value = "";
  desenharTabela();
});

$("arquivos").addEventListener("change", (e) => receber([...e.target.files]));
const zona = $("soltar");
for (const ev of ["dragenter", "dragover"]) zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("sobre"); });
for (const ev of ["dragleave", "drop"]) zona.addEventListener(ev, () => zona.classList.remove("sobre"));
zona.addEventListener("drop", (e) => { e.preventDefault(); receber([...e.dataTransfer.files]); });

// ------------------------------------------------------------------ códigos
const tabelas = {};
async function carregarTabela() {
  const nome = $("tabela").value;
  if (!tabelas[nome]) tabelas[nome] = await fetch(`/dados/${nome}.json`).then((r) => r.json());
  filtrar();
}

function semAcento(s) {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function filtrar() {
  const nome = $("tabela").value;
  const dados = tabelas[nome];
  if (!dados) return;
  const termo = semAcento($("termo").value.trim());
  const lista = $("lista-codigos");
  lista.replaceChildren();
  const digitos = termo.replace(/\D/g, "");
  const achados = Object.entries(dados).filter(([c, d]) =>
    !termo || (digitos && c.includes(digitos)) || semAcento(d).includes(termo));
  $("total-codigos").textContent = termo ? `${achados.length} resultado(s)` : `${achados.length} códigos na tabela`;
  for (const [codigo, descricao] of achados.slice(0, 200)) {
    const li = document.createElement("li");
    const c = document.createElement("code");
    c.textContent = codigo;
    const d = document.createElement("span");
    d.textContent = nome === "municipios" ? `${descricao} / ${UF_POR_CODIGO[codigo.slice(0, 2)] || ""}` : descricao;
    li.append(c, d);
    lista.append(li);
  }
}
$("tabela").addEventListener("change", carregarTabela);
$("termo").addEventListener("input", filtrar);
