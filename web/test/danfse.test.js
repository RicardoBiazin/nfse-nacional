import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { DOMParser } from "@xmldom/xmldom";

import { chaveDe, cnpjCpf, data, dataHora, gerarDanfse, moeda } from "../src/danfse.js";
import { lerEvento, resumir, tipo } from "../src/xml.js";

const ler = (nome) => new DOMParser().parseFromString(readFileSync(new URL(`exemplos/${nome}`, import.meta.url), "utf8"), "text/xml");
const LOGO = readFileSync(new URL("../../recursos/logo_nfse.png", import.meta.url));
const MUNICIPIOS = { 4205407: "Florianópolis", 3106200: "Belo Horizonte" };

test("formatação igual à do app desktop", () => {
  assert.equal(cnpjCpf("11444777000161"), "11.444.777/0001-61");
  assert.equal(cnpjCpf("12345678909"), "123.456.789-09");
  assert.equal(moeda("1500.00"), "R$ 1.500,00");
  assert.equal(moeda("1234567.5"), "R$ 1.234.567,50");
  assert.equal(moeda("0"), "R$ 0,00");
  assert.equal(data("2026-09-01"), "01/09/2026");
  assert.equal(dataHora("2026-09-02T07:50:41-03:00"), "02/09/2026 07:50:41");
});

test("lê NFS-e e evento", () => {
  const nfse = ler("exemplo_nfse.xml");
  assert.equal(tipo(nfse), "NFSe");
  const r = resumir(nfse);
  assert.equal(r.numero, "42");
  assert.equal(r.tomador, "CLIENTE EXEMPLO SERVICOS LTDA");
  assert.equal(r.valor, "1500.00");
  assert.equal(chaveDe(nfse), "42054072211222333000181000000000004226100000000017");
  const ev = lerEvento(ler("exemplo_evento_cancelamento.xml"));
  assert.deepEqual([ev.chave, ev.tipo, ev.marca], [r.chave, "101101", "CANCELADA"]);
});

test("gera PDF de uma página, com e sem marca d'água", () => {
  for (const marca of ["", "CANCELADA", "SUBSTITUÍDA"]) {
    const pdf = gerarDanfse(ler("exemplo_nfse.xml"), { logo: LOGO, municipios: MUNICIPIOS, marca });
    const cabeca = Buffer.from(pdf.slice(0, 5)).toString();
    assert.equal(cabeca, "%PDF-");
    const texto = Buffer.from(pdf).toString("latin1");
    assert.equal((texto.match(/\/Type \/Page\b/g) || []).length, 1, "página única (NT 008)");
  }
});

test("recusa XML que não é NFS-e", () => {
  assert.throws(() => gerarDanfse(ler("exemplo_evento_cancelamento.xml")), /não é de uma NFS-e/);
});
