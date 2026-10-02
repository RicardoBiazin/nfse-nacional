"""Senhas (scrypt da biblioteca padrão), bloqueio por tentativas e papéis."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

PAPEIS = {"consulta": 0, "emissor": 1, "admin": 2}
NOMES_PAPEIS = {"consulta": "Consulta (ver e baixar)", "emissor": "Emissor (emite notas)",
                "admin": "Administrador (cancela, configura, usuários)"}
MAX_FALHAS = 5
BLOQUEIO = dt.timedelta(minutes=15)
_N, _R, _P = 2 ** 14, 8, 1


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode("utf-8"), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(sal).decode(),
                                          base64.b64encode(h).decode())


def conferir(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(senha.encode("utf-8"), salt=base64.b64decode(sal),
                              n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def senha_fraca(senha: str) -> str:
    """'' se a senha serve; senão o motivo."""
    if len(senha) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if senha.isdigit() or senha.isalpha():
        return "Misture letras e números."
    return ""


def pode(papel_usuario: str, papel_minimo: str) -> bool:
    return PAPEIS.get(papel_usuario, -1) >= PAPEIS[papel_minimo]


def autenticar(banco, login: str, senha: str, ip: str = ""):
    """Linha do usuário ou None. Conta falhas e bloqueia por 15 min após 5 erros."""
    u = banco.usuario(login)
    agora = dt.datetime.now()
    if not u or not u["ativo"]:
        conferir(senha, gerar_hash("x"))          # tempo parecido com usuário existente
        banco.auditar(login or "?", "login-falhou", "usuário inexistente ou inativo", ip=ip)
        return None
    if u["bloqueado_ate"] and dt.datetime.fromisoformat(u["bloqueado_ate"]) > agora:
        banco.auditar(u["login"], "login-bloqueado", "", ip=ip)
        return None
    if not conferir(senha, u["hash_senha"]):
        falhas = u["falhas"] + 1
        campos = {"falhas": falhas}
        if falhas >= MAX_FALHAS:
            campos = {"falhas": 0, "bloqueado_ate": (agora + BLOQUEIO).isoformat(timespec="seconds")}
        banco.atualizar_usuario(u["id"], **campos)
        banco.auditar(u["login"], "login-falhou", f"tentativa {falhas}", ip=ip)
        return None
    banco.atualizar_usuario(u["id"], falhas=0, bloqueado_ate=None)
    banco.auditar(u["login"], "login", "", ip=ip)
    return banco.usuario_por_id(u["id"])
