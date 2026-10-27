"""Envio da NFS-e por e-mail ao tomador (DANFSe em PDF + XML), pelo SMTP da empresa.

O sistema nacional não manda e-mail ao tomador; quem envia é o emissor. A configuração
SMTP fica por empresa (tabela config_email) e a senha no mesmo cofre dos certificados.
"""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import cofre
from .banco import Banco, ConfigEmail
from .danfse import URL_CONSULTA

ASSUNTO_PADRAO = "NFS-e nº {numero} - {prestador}"
CORPO_PADRAO = """Olá, {tomador}.

Segue a NFS-e nº {numero}, competência {competencia}, no valor de R$ {valor}.
Em anexo: DANFSe (PDF) e o XML da nota.

Chave de acesso: {chave}
Consulta pública: {link}

Atenciosamente,
{prestador}
"""
CAMPOS = "{numero} {tomador} {prestador} {valor} {competencia} {chave} {link}"
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def chave_senha(empresa_id: int) -> str:
    return f"smtp:{empresa_id}"


def senha_smtp(empresa_id: int) -> str | None:
    return cofre.senha_guardada(chave_senha(empresa_id))


def guardar_senha_smtp(empresa_id: int, senha: str):
    cofre.guardar_senha(chave_senha(empresa_id), senha)


def separar_enderecos(texto: str) -> list[str]:
    """'a@x.com; b@y.com, c@z.com' -> lista; recusa endereço malformado."""
    lista = [p.strip() for p in re.split(r"[;,\s]+", texto or "") if p.strip()]
    ruins = [p for p in lista if not _EMAIL.match(p)]
    if ruins:
        raise ValueError(f"E-mail inválido: {', '.join(ruins)}")
    return lista


def _moeda(v) -> str:
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v or "")


class _Formato(dict):
    def __missing__(self, chave):          # campo desconhecido no modelo fica como está
        return "{" + chave + "}"


def campos_da_nota(nota, empresa_razao: str) -> dict:
    compet = nota["d_compet"] or ""
    if len(compet) >= 10:
        compet = f"{compet[8:10]}/{compet[5:7]}/{compet[:4]}"
    chave = nota["chave"] or ""
    return {"numero": nota["numero"] or "", "tomador": nota["tomador_nome"] or "cliente",
            "prestador": nota["prestador_nome"] or empresa_razao, "valor": _moeda(nota["v_serv"]),
            "competencia": compet, "chave": chave,
            "link": URL_CONSULTA + chave if chave else ""}


def montar_mensagem(cfg: ConfigEmail, para: list[str], assunto: str, corpo: str,
                    anexos: list[tuple[str, bytes, str]] = ()) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.nome_remetente, cfg.remetente)) if cfg.nome_remetente else cfg.remetente
    msg["To"] = ", ".join(para)
    msg["Subject"] = assunto
    msg["Message-ID"] = make_msgid(domain=cfg.remetente.rpartition("@")[2] or None)
    msg.set_content(corpo)
    for nome, dados, tipo in anexos:
        principal, _, sub = tipo.partition("/")
        msg.add_attachment(dados, maintype=principal, subtype=sub, filename=nome)
    return msg


def enviar(cfg: ConfigEmail, senha: str | None, msg: EmailMessage, para: list[str],
           copia_oculta: list[str] = ()):
    """Entrega pelo SMTP configurado. Erros de rede/autenticação sobem como estão."""
    if not cfg.configurado:
        raise ValueError("Configure o envio de e-mail (servidor SMTP e remetente) em "
                         "'Configurar empresa' > E-mail.")
    contexto = ssl.create_default_context()
    if cfg.seguranca == "ssl":
        smtp = smtplib.SMTP_SSL(cfg.host, cfg.porta or 465, timeout=30, context=contexto)
    else:
        smtp = smtplib.SMTP(cfg.host, cfg.porta or 587, timeout=30)
    with smtp:
        smtp.ehlo()
        if cfg.seguranca == "starttls":
            smtp.starttls(context=contexto)
            smtp.ehlo()
        if cfg.usuario:
            smtp.login(cfg.usuario, senha or "")
        smtp.send_message(msg, to_addrs=list(para) + list(copia_oculta))


def enviar_teste(cfg: ConfigEmail, senha: str | None, para: str):
    destinos = separar_enderecos(para)
    if not destinos:
        raise ValueError("Informe para onde mandar o teste.")
    msg = montar_mensagem(cfg, destinos, "Teste de envio - NFS-e Nacional",
                          "Se você recebeu esta mensagem, o envio de NFS-e por e-mail está "
                          "configurado corretamente.")
    enviar(cfg, senha, msg, destinos)


def enviar_nota(banco: Banco, nota_id: int, para: str | None = None) -> list[str]:
    """Manda DANFSe + XML da nota. `para` vazio = e-mail do tomador cadastrado.
    Registra o envio (sucesso ou falha) em envios_email. Devolve os destinatários."""
    from .danfse import gerar_pdf
    from .exportar import _nome_base
    from .servico import marca_dagua
    nota = banco.nota(nota_id)
    if not nota:
        raise ValueError("Nota não encontrada.")
    if not nota["nfse_xml"]:
        raise ValueError("Só dá para enviar nota autorizada (com o XML da NFS-e).")
    empresa = banco.empresa(nota["empresa_id"])
    cfg = banco.config_email(nota["empresa_id"])
    if para is None or not para.strip():
        tom = banco.tomador(nota["tomador_doc"]) if nota["tomador_doc"] else None
        para = tom.email if tom else ""
    destinos = separar_enderecos(para)
    if not destinos:
        raise ValueError("O tomador não tem e-mail cadastrado. Informe o endereço.")
    campos = _Formato(campos_da_nota(nota, empresa.razao if empresa else ""))
    assunto = (cfg.assunto or ASSUNTO_PADRAO).format_map(campos).replace("\n", " ").strip()
    corpo = (cfg.corpo or CORPO_PADRAO).format_map(campos)
    base = _nome_base(nota)
    anexos = [(f"{base}.pdf", gerar_pdf(nota["nfse_xml"], marca_dagua(banco, nota)), "application/pdf"),
              (f"{base}.xml", bytes(nota["nfse_xml"]), "application/xml")]
    for ev in banco.eventos(nota["chave"]) if nota["chave"] else []:
        anexos.append((f"{base}_evento_{ev['tipo']}.xml", bytes(ev["xml"]), "application/xml"))
    msg = montar_mensagem(cfg, destinos, assunto, corpo, anexos)
    copia = separar_enderecos(cfg.copia) if cfg.copia else []
    try:
        enviar(cfg, senha_smtp(nota["empresa_id"]) if cfg.usuario else None, msg, destinos, copia)
    except Exception as erro:
        banco.registrar_envio(nota_id, ", ".join(destinos), False, str(erro))
        raise
    banco.registrar_envio(nota_id, ", ".join(destinos), True)
    return destinos
