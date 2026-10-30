// Pagina de apresentacao /sobre/ (unica parte indexavel do site).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const ler = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const html = ler("../public/sobre/index.html");

test("/sobre/: SEO basico", () => {
  const titulo = /<title>([^<]+)<\/title>/.exec(html)[1];
  assert.ok(titulo.length <= 60, `title com ${titulo.length} caracteres`);
  assert.match(titulo, /NFS-e Nacional/);
  const desc = /<meta name="description" content="([^"]+)">/.exec(html)[1];
  assert.ok(desc.length >= 140 && desc.length <= 160, `description com ${desc.length} caracteres`);
  assert.match(html, /<html lang="pt-BR">/);
  assert.match(html, /<link rel="canonical" href="https:\/\/nfse\.biazin\.com\.br\/sobre\/">/);
  assert.match(html, /<meta property="og:title"/);
  assert.equal((html.match(/<h1[ >]/g) ?? []).length, 1);
  assert.doesNotMatch(html, /noindex/);
  assert.match(html, /<a class="botao primario" href="\/">Abrir o DANFSe no navegador<\/a>/);
});

test("/sobre/: JSON-LD valido (WebApplication + FAQPage) e igual ao FAQ visivel", () => {
  const blocos = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
  assert.equal(blocos.length, 1);
  const tipos = JSON.parse(blocos[0][1])["@graph"];
  const faq = tipos.find((t) => t["@type"] === "FAQPage");
  assert.ok(tipos.some((t) => t["@type"] === "WebApplication"));
  const visiveis = [...html.matchAll(/<summary>([^<]+)<\/summary>/g)].map((m) => m[1]);
  assert.deepEqual(faq.mainEntity.map((q) => q.name), visiveis);
});

test("/sobre/: respeita a CSP (sem script executavel nem estilo embutido)", () => {
  assert.doesNotMatch(html, /<script(?! type="application\/ld\+json")/);
  assert.doesNotMatch(html, /<style|style="/);
  assert.doesNotMatch(html, / on\w+="/);
  for (const m of html.matchAll(/(?:href|src)="(\/[^"]*)"/g)) {
    assert.ok(m[1] === "/" || m[1].startsWith("/sobre/"), `recurso fora de /sobre/ passa pelo portao: ${m[1]}`);
  }
});

test("robots.txt e sitemap.xml", () => {
  const robots = ler("../public/robots.txt");
  assert.match(robots, /^Allow: \/sobre\/$/m);
  assert.match(robots, /^Disallow: \/$/m);
  assert.match(robots, /^Sitemap: https:\/\/nfse\.biazin\.com\.br\/sitemap\.xml$/m);
  const locs = [...ler("../public/sitemap.xml").matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  assert.deepEqual(locs, ["https://nfse.biazin.com.br/sobre/"]);
});
