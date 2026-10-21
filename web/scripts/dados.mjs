// Gera public/dados/*.json a partir das tabelas oficiais de ../recursos (as mesmas do app
// desktop) e copia o logo da NFS-e e o ícone. Roda antes do dev e do build.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const RAIZ = new URL("../../recursos/", import.meta.url);
const PUBLICO = new URL("../public/", import.meta.url);
mkdirSync(new URL("dados/", PUBLICO), { recursive: true });

function csv(nome) {
  const obj = {};
  for (const linha of readFileSync(new URL(nome, RAIZ), "utf8").split(/\r?\n/)) {
    const i = linha.indexOf(";");
    if (i > 0) obj[linha.slice(0, i)] = linha.slice(i + 1);
  }
  return obj;
}

const tabelas = {
  servicos: csv("servicos_nacionais.csv"),
  nbs: csv("nbs.csv"),
  municipios: csv("municipios_ibge.csv"),
};
for (const [nome, obj] of Object.entries(tabelas)) {
  writeFileSync(new URL(`dados/${nome}.json`, PUBLICO), JSON.stringify(obj));
  console.log(`dados/${nome}.json: ${Object.keys(obj).length} códigos`);
}
copyFileSync(new URL("logo_nfse.png", RAIZ), new URL("logo_nfse.png", PUBLICO));
copyFileSync(new URL("icone.png", RAIZ), new URL("icone.png", PUBLICO));
