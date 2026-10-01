"""Linha de comando: python -m nfse_nacional <comando> ...

Exemplo de JSON para `emitir`/`simular`:
{
  "descricao": "Consultoria em TI - setembro/2026",
  "v_serv": "1500.00",
  "d_compet": "2026-09-30",
  "tomador": {"documento": "12345678909", "nome": "Fulano de Tal",
              "c_mun": "4115200", "cep": "87000000", "logradouro": "Rua A",
              "numero": "10", "bairro": "Centro", "email": "fulano@exemplo.com"},
  "tp_ret_issqn": "1"
}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

from . import VERSAO, cofre
from .banco import Banco, Empresa, Tomador
from .cliente_http import ErroApi
from .servico import DadosNota, Emissor, ErroValidacao


def abrir_emissor(banco: Banco, cnpj: str) -> Emissor:
    e = banco.empresa_por_cnpj(cnpj)
    if not e:
        raise SystemExit(f"Empresa {cnpj} não cadastrada. Use: empresa-importar")
    if not e.cert_arquivo:
        raise SystemExit("Empresa sem certificado. Use: empresa-importar")
    return Emissor(banco, e, cofre.abrir_certificado(e.cert_arquivo, e.cnpj))


def dados_de_json(caminho: str) -> DadosNota:
    bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
    tom = bruto.pop("tomador", None)
    if tom:
        bruto["tomador"] = Tomador(**tom)
    for campo in ("v_serv", "p_aliq", "v_desc_incond", "v_desc_cond"):
        if bruto.get(campo) not in (None, ""):
            bruto[campo] = Decimal(str(bruto[campo]))
    if bruto.get("d_compet"):
        bruto["d_compet"] = dt.date.fromisoformat(bruto["d_compet"])
    validos = {f.name for f in fields(DadosNota)}
    desconhecidos = set(bruto) - validos
    if desconhecidos:
        raise SystemExit(f"Campos desconhecidos no JSON: {', '.join(sorted(desconhecidos))}")
    return DadosNota(**bruto)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nfse_nacional", description=f"NFS-e Nacional {VERSAO}")
    ap.add_argument("--banco", help="arquivo SQLite (padrão: %%LOCALAPPDATA%%\\NFSE_Nacional)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("empresa-importar", help="importa o certificado A1 e cria/atualiza a empresa")
    p.add_argument("--pfx", required=True)
    p.add_argument("--senha", required=True)
    p.add_argument("--razao", default="")

    p = sub.add_parser("empresa-config", help="altera campos da empresa (campo=valor)")
    p.add_argument("cnpj")
    p.add_argument("pares", nargs="+")

    sub.add_parser("empresas", help="lista empresas")

    for nome, ajuda in (("emitir", "emite NFS-e a partir de um JSON"),
                        ("simular", "monta, valida e assina a DPS sem enviar")):
        p = sub.add_parser(nome, help=ajuda)
        p.add_argument("cnpj")
        p.add_argument("json")
        if nome == "simular":
            p.add_argument("--saida", default="DPS_simulada.xml")

    p = sub.add_parser("reconsultar", help="resolve nota pendente/indefinida")
    p.add_argument("cnpj"); p.add_argument("id", type=int)

    p = sub.add_parser("cancelar")
    p.add_argument("cnpj"); p.add_argument("id", type=int)
    p.add_argument("--motivo", choices=["1", "2", "9"], required=True,
                   help="1 erro na emissão, 2 serviço não prestado, 9 outros")
    p.add_argument("--justificativa", required=True)

    p = sub.add_parser("sincronizar", help="baixa do ADN as notas emitidas e recebidas")
    p.add_argument("cnpj")

    p = sub.add_parser("notas")
    p.add_argument("cnpj")
    p.add_argument("--inicio", default=""); p.add_argument("--fim", default="")

    p = sub.add_parser("danfse")
    p.add_argument("cnpj"); p.add_argument("id", type=int)
    p.add_argument("--saida")

    p = sub.add_parser("exportar")
    p.add_argument("cnpj")
    p.add_argument("--inicio", default=""); p.add_argument("--fim", default="")
    p.add_argument("--xlsx"); p.add_argument("--xml-pasta")

    a = ap.parse_args(argv)
    banco = Banco(a.banco) if a.banco else Banco()
    try:
        return _executar(a, banco)
    except ErroValidacao as e:
        print("Não passou na validação:\n  - " + "\n  - ".join(e.erros), file=sys.stderr)
        return 2
    except ErroApi as e:
        print(f"Erro da API: {e}", file=sys.stderr)
        return 3
    finally:
        banco.fechar()


def _executar(a, banco: Banco) -> int:
    if a.cmd == "empresa-importar":
        cert, destino = cofre.importar_certificado(a.pfx, a.senha)
        tipo, doc = cert.documento
        e = banco.empresa_por_cnpj(doc) or Empresa(cnpj=doc)
        e.cert_arquivo = str(destino)
        e.razao = a.razao or e.razao or cert.titular.split(":")[0]
        e = banco.salvar_empresa(e)
        print(f"{tipo} {doc} - {e.razao}; certificado válido até {cert.validade:%d/%m/%Y}")
        return 0
    if a.cmd == "empresa-config":
        e = banco.empresa_por_cnpj(a.cnpj)
        if not e:
            raise SystemExit("Empresa não cadastrada.")
        validos = {f.name for f in fields(Empresa)} - {"id", "cnpj"}
        for par in a.pares:
            campo, _, valor = par.partition("=")
            if campo not in validos:
                raise SystemExit(f"Campo inválido: {campo}. Válidos: {', '.join(sorted(validos))}")
            if campo == "convenio_ativo":
                valor = None if valor == "" else int(valor)
            setattr(e, campo, valor)
        banco.salvar_empresa(e)
        print("ok")
        return 0
    if a.cmd == "empresas":
        for e in banco.empresas():
            print(f"{e.cnpj}  {e.razao}  mun={e.c_mun}  amb={e.ambiente}  série={e.serie}")
        return 0

    em = abrir_emissor(banco, a.cnpj)
    if a.cmd == "simular":
        dados = dados_de_json(a.json)
        xml = em.preparar(em.montar_dps(dados, banco.proximo_numero(
            em.empresa.id, em.empresa.ambiente, em.empresa.serie)))
        Path(a.saida).write_bytes(xml)
        print(f"DPS válida e assinada gravada em {a.saida} (nada foi enviado).")
    elif a.cmd == "emitir":
        r = em.emitir(dados_de_json(a.json))
        print(f"nota #{r.nota_id}: {r.situacao} {r.numero} {r.chave} {r.mensagem}".strip())
        return 0 if r.situacao == "autorizada" else 4
    elif a.cmd == "reconsultar":
        r = em.reconsultar(a.id)
        print(f"nota #{r.nota_id}: {r.situacao} {r.numero} {r.chave} {r.mensagem}".strip())
    elif a.cmd == "cancelar":
        em.cancelar(a.id, a.motivo, a.justificativa)
        print("Cancelamento registrado.")
    elif a.cmd == "sincronizar":
        n = em.sincronizar(progresso=print)
        print(f"{n} documento(s) novo(s).")
    elif a.cmd == "notas":
        for n in banco.notas(em.empresa.id, em.empresa.ambiente, a.inicio, a.fim):
            print(f"#{n['id']:<5} {n['situacao']:<11} {n['origem']:<8} {n['numero'] or '-':>6} "
                  f"{n['d_compet'] or '':<10} {n['v_serv'] or '':>12}  {n['tomador_nome'] or n['prestador_nome'] or ''}")
    elif a.cmd == "danfse":
        pdf = em.danfse(a.id)
        saida = a.saida or f"DANFSe_{banco.nota(a.id)['chave']}.pdf"
        Path(saida).write_bytes(pdf)
        print(f"DANFSe salvo em {saida}")
    elif a.cmd == "exportar":
        from . import exportar
        linhas = banco.notas(em.empresa.id, em.empresa.ambiente, a.inicio, a.fim)
        if a.xlsx:
            exportar.exportar_xlsx(linhas, a.xlsx)
            print(f"Planilha: {a.xlsx} ({len(linhas)} notas)")
        if a.xml_pasta:
            n = exportar.exportar_xmls(banco, [ln["id"] for ln in linhas], a.xml_pasta)
            print(f"{n} XML(s) em {a.xml_pasta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
