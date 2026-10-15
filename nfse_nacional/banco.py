"""Persistência local (SQLite): empresas, tomadores, notas, eventos, numeração e NSU."""
from __future__ import annotations

import datetime as dt
import sqlite3
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import pasta_dados

ESQUEMA = """
CREATE TABLE IF NOT EXISTS empresas (
    id INTEGER PRIMARY KEY,
    cnpj TEXT NOT NULL UNIQUE,
    razao TEXT NOT NULL DEFAULT '',
    im TEXT NOT NULL DEFAULT '',
    c_mun TEXT NOT NULL DEFAULT '',
    op_simp_nac TEXT NOT NULL DEFAULT '1',
    reg_ap_trib_sn TEXT NOT NULL DEFAULT '',
    reg_esp_trib TEXT NOT NULL DEFAULT '0',
    fone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    serie TEXT NOT NULL DEFAULT '1',
    ambiente TEXT NOT NULL DEFAULT 'producao_restrita',
    cert_arquivo TEXT NOT NULL DEFAULT '',
    convenio_ativo INTEGER,
    p_tot_fed TEXT NOT NULL DEFAULT '0',
    p_tot_est TEXT NOT NULL DEFAULT '0',
    p_tot_mun TEXT NOT NULL DEFAULT '0',
    p_tot_sn TEXT NOT NULL DEFAULT '0',
    c_trib_nac TEXT NOT NULL DEFAULT '',
    c_trib_mun TEXT NOT NULL DEFAULT '',
    c_nbs TEXT NOT NULL DEFAULT '',
    descricao_padrao TEXT NOT NULL DEFAULT '',
    p_aliq TEXT NOT NULL DEFAULT '',
    ibs_c_ind_op TEXT NOT NULL DEFAULT '',
    ibs_cst TEXT NOT NULL DEFAULT '',
    ibs_c_class_trib TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS certificados (
    id INTEGER PRIMARY KEY,
    empresa_id INTEGER NOT NULL,
    arquivo TEXT NOT NULL,
    chave_cofre TEXT NOT NULL,          -- usuário no keyring onde está a senha
    documento TEXT NOT NULL DEFAULT '',
    titular TEXT NOT NULL DEFAULT '',
    serial TEXT NOT NULL DEFAULT '',
    validade TEXT NOT NULL DEFAULT '',  -- ISO, UTC
    principal INTEGER NOT NULL DEFAULT 0,
    UNIQUE (empresa_id, serial)
);
CREATE TABLE IF NOT EXISTS segredos (
    chave TEXT PRIMARY KEY,
    valor BLOB NOT NULL                 -- cifrado com DPAPI (modo servidor)
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome TEXT NOT NULL DEFAULT '',
    hash_senha TEXT NOT NULL,
    papel TEXT NOT NULL DEFAULT 'consulta',   -- consulta | emissor | admin
    ativo INTEGER NOT NULL DEFAULT 1,
    falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY,
    quando TEXT NOT NULL,
    usuario TEXT NOT NULL,
    acao TEXT NOT NULL,
    detalhe TEXT,
    chave TEXT,
    ip TEXT
);
CREATE TABLE IF NOT EXISTS empresa_tomadores (
    empresa_id INTEGER NOT NULL,
    documento TEXT NOT NULL,
    PRIMARY KEY (empresa_id, documento)
);
CREATE TABLE IF NOT EXISTS tomadores (
    id INTEGER PRIMARY KEY,
    documento TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL DEFAULT '',
    im TEXT NOT NULL DEFAULT '',
    c_mun TEXT NOT NULL DEFAULT '',
    cep TEXT NOT NULL DEFAULT '',
    logradouro TEXT NOT NULL DEFAULT '',
    numero TEXT NOT NULL DEFAULT '',
    complemento TEXT NOT NULL DEFAULT '',
    bairro TEXT NOT NULL DEFAULT '',
    fone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS numeracao (
    empresa_id INTEGER NOT NULL,
    ambiente TEXT NOT NULL,
    serie TEXT NOT NULL,
    proximo INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (empresa_id, ambiente, serie)
);
CREATE TABLE IF NOT EXISTS controle_nsu (
    empresa_id INTEGER NOT NULL,
    ambiente TEXT NOT NULL,
    ultimo_nsu INTEGER NOT NULL DEFAULT 0,
    atualizado_em TEXT,
    PRIMARY KEY (empresa_id, ambiente)
);
CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY,
    empresa_id INTEGER NOT NULL,
    ambiente TEXT NOT NULL,
    origem TEXT NOT NULL DEFAULT 'emitida',      -- emitida | recebida
    situacao TEXT NOT NULL DEFAULT 'pendente',   -- pendente | autorizada | rejeitada | cancelada | indefinida
    serie TEXT, n_dps INTEGER, id_dps TEXT UNIQUE,
    chave TEXT UNIQUE, numero TEXT,
    d_compet TEXT, dh_emissao TEXT,
    prestador_doc TEXT, prestador_nome TEXT,
    tomador_doc TEXT, tomador_nome TEXT,
    descricao TEXT,
    v_serv TEXT, v_liq TEXT, v_issqn TEXT,
    mensagem TEXT,
    dps_xml BLOB, nfse_xml BLOB,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notas_empresa ON notas (empresa_id, ambiente, d_compet);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL,
    tipo TEXT NOT NULL,
    descricao TEXT,
    dh TEXT,
    nsu INTEGER,
    xml BLOB,
    UNIQUE (chave, tipo, dh)
);
"""


@dataclass
class Empresa:
    cnpj: str
    razao: str = ""
    im: str = ""
    c_mun: str = ""
    op_simp_nac: str = "1"
    reg_ap_trib_sn: str = ""
    reg_esp_trib: str = "0"
    fone: str = ""
    email: str = ""
    serie: str = "1"
    ambiente: str = "producao_restrita"
    cert_arquivo: str = ""
    convenio_ativo: int | None = None
    p_tot_fed: str = "0"
    p_tot_est: str = "0"
    p_tot_mun: str = "0"
    p_tot_sn: str = "0"
    c_trib_nac: str = ""
    c_trib_mun: str = ""
    c_nbs: str = ""
    descricao_padrao: str = ""
    p_aliq: str = ""
    ibs_c_ind_op: str = ""
    ibs_cst: str = ""
    ibs_c_class_trib: str = ""
    id: int | None = None


@dataclass
class Tomador:
    documento: str
    nome: str = ""
    im: str = ""
    c_mun: str = ""
    cep: str = ""
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    fone: str = ""
    email: str = ""
    id: int | None = None


def _agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _de_linha(cls, linha):
    nomes = {f.name for f in fields(cls)}
    return cls(**{k: linha[k] for k in linha.keys() if k in nomes})


class _Resultado:
    """Resultado já materializado: pode atravessar threads sem cursor aberto."""

    def __init__(self, cursor: sqlite3.Cursor):
        self.linhas = cursor.fetchall()
        self.lastrowid = cursor.lastrowid

    def fetchone(self):
        return self.linhas[0] if self.linhas else None

    def fetchall(self):
        return self.linhas

    def __iter__(self):
        return iter(self.linhas)


class _ConexaoSegura:
    """sqlite3 compartilhado entre a interface e as tarefas em segundo plano."""

    def __init__(self, caminho):
        self._con = sqlite3.connect(caminho, isolation_level=None, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self.trava = threading.RLock()

    def execute(self, sql, args=()):
        with self.trava:
            return _Resultado(self._con.execute(sql, args))

    def executescript(self, sql):
        with self.trava:
            self._con.executescript(sql)

    def close(self):
        with self.trava:
            self._con.close()


class Banco:
    def __init__(self, caminho: str | Path | None = None):
        self.caminho = Path(caminho) if caminho else pasta_dados() / "nfse_nacional.db"
        self.con = _ConexaoSegura(self.caminho)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)
        # Até a 0.7.1 a lista de tomadores era única para todas as empresas: liga cada
        # tomador às empresas que já emitiram nota para ele.
        self.con.execute(
            "INSERT OR IGNORE INTO empresa_tomadores (empresa_id, documento) "
            "SELECT DISTINCT empresa_id, tomador_doc FROM notas "
            "WHERE origem='emitida' AND COALESCE(tomador_doc, '') <> ''")

    def fechar(self):
        self.con.close()

    # ------------------------------------------------------------ empresas
    def salvar_empresa(self, e: Empresa) -> Empresa:
        dados = asdict(e)
        dados.pop("id")
        colunas = ", ".join(dados)
        marcas = ", ".join(f":{k}" for k in dados)
        atualiza = ", ".join(f"{k}=excluded.{k}" for k in dados if k != "cnpj")
        self.con.execute(
            f"INSERT INTO empresas ({colunas}) VALUES ({marcas}) "
            f"ON CONFLICT(cnpj) DO UPDATE SET {atualiza}", dados)
        return self.empresa_por_cnpj(e.cnpj)

    def empresas(self) -> list[Empresa]:
        return [_de_linha(Empresa, r) for r in
                self.con.execute("SELECT * FROM empresas ORDER BY razao, cnpj")]

    def empresa(self, id_: int) -> Empresa | None:
        r = self.con.execute("SELECT * FROM empresas WHERE id=?", (id_,)).fetchone()
        return _de_linha(Empresa, r) if r else None

    def empresa_por_cnpj(self, cnpj: str) -> Empresa | None:
        r = self.con.execute("SELECT * FROM empresas WHERE cnpj=?", (cnpj,)).fetchone()
        return _de_linha(Empresa, r) if r else None

    def excluir_empresa(self, id_: int):
        self.con.execute("DELETE FROM empresas WHERE id=?", (id_,))

    # ------------------------------------------------------------ segredos
    def gravar_segredo(self, chave: str, valor: bytes):
        self.con.execute("INSERT INTO segredos (chave, valor) VALUES (?, ?) "
                         "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, valor))

    def ler_segredo(self, chave: str) -> bytes | None:
        r = self.con.execute("SELECT valor FROM segredos WHERE chave=?", (chave,)).fetchone()
        return bytes(r[0]) if r else None

    def apagar_segredo(self, chave: str):
        self.con.execute("DELETE FROM segredos WHERE chave=?", (chave,))

    # ------------------------------------------------------------ usuários
    def criar_usuario(self, login: str, nome: str, hash_senha: str, papel: str) -> int:
        return self.con.execute(
            "INSERT INTO usuarios (login, nome, hash_senha, papel, criado_em) VALUES (?, ?, ?, ?, ?)",
            (login.strip(), nome.strip(), hash_senha, papel, _agora())).lastrowid

    def usuario(self, login: str):
        return self.con.execute("SELECT * FROM usuarios WHERE login=?", (login.strip(),)).fetchone()

    def usuario_por_id(self, id_: int):
        return self.con.execute("SELECT * FROM usuarios WHERE id=?", (id_,)).fetchone()

    def usuarios(self):
        return self.con.execute("SELECT * FROM usuarios ORDER BY login").fetchall()

    def atualizar_usuario(self, id_: int, **campos):
        if campos:
            sets = ", ".join(f"{k}=?" for k in campos)
            self.con.execute(f"UPDATE usuarios SET {sets} WHERE id=?", (*campos.values(), id_))

    def ha_usuarios(self) -> bool:
        return self.con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None

    # ------------------------------------------------------------ auditoria
    def auditar(self, usuario: str, acao: str, detalhe: str = "", chave: str = "", ip: str = ""):
        self.con.execute(
            "INSERT INTO auditoria (quando, usuario, acao, detalhe, chave, ip) VALUES (?, ?, ?, ?, ?, ?)",
            (_agora(), usuario, acao, detalhe, chave, ip))

    def auditoria(self, limite: int = 200):
        return self.con.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT ?", (limite,)).fetchall()

    # ------------------------------------------------------------ certificados
    def certificados(self, empresa_id: int) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM certificados WHERE empresa_id=? ORDER BY principal DESC, validade DESC",
            (empresa_id,)).fetchall()

    def adicionar_certificado(self, empresa_id: int, arquivo: str, chave_cofre: str,
                              documento: str, titular: str, serial: str, validade: str) -> int:
        with self._transacao():
            self.con.execute(
                "INSERT INTO certificados (empresa_id, arquivo, chave_cofre, documento, titular,"
                " serial, validade) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(empresa_id, serial)"
                " DO UPDATE SET arquivo=excluded.arquivo, chave_cofre=excluded.chave_cofre,"
                " titular=excluded.titular, validade=excluded.validade",
                (empresa_id, arquivo, chave_cofre, documento, titular, serial, validade))
            id_ = self.con.execute("SELECT id FROM certificados WHERE empresa_id=? AND serial=?",
                                   (empresa_id, serial)).fetchone()[0]
            if not self.con.execute("SELECT 1 FROM certificados WHERE empresa_id=? AND principal=1",
                                    (empresa_id,)).fetchone():
                self._marcar_principal(empresa_id, id_)
        return id_

    def definir_certificado_principal(self, empresa_id: int, cert_id: int):
        with self._transacao():
            self._marcar_principal(empresa_id, cert_id)

    def _marcar_principal(self, empresa_id: int, cert_id: int):
        self.con.execute("UPDATE certificados SET principal=(id=?) WHERE empresa_id=?",
                         (cert_id, empresa_id))
        arq = self.con.execute("SELECT arquivo FROM certificados WHERE id=?", (cert_id,)).fetchone()
        # empresas.cert_arquivo continua apontando para o principal (compatibilidade).
        self.con.execute("UPDATE empresas SET cert_arquivo=? WHERE id=?",
                         (arq[0] if arq else "", empresa_id))

    def remover_certificado(self, empresa_id: int, cert_id: int):
        with self._transacao():
            era = self.con.execute("SELECT principal FROM certificados WHERE id=?", (cert_id,)).fetchone()
            self.con.execute("DELETE FROM certificados WHERE id=? AND empresa_id=?", (cert_id, empresa_id))
            if era and era[0]:
                prox = self.con.execute(
                    "SELECT id FROM certificados WHERE empresa_id=? ORDER BY validade DESC LIMIT 1",
                    (empresa_id,)).fetchone()
                if prox:
                    self._marcar_principal(empresa_id, prox[0])
                else:
                    self.con.execute("UPDATE empresas SET cert_arquivo='' WHERE id=?", (empresa_id,))

    # ------------------------------------------------------------ tomadores
    def salvar_tomador(self, t: Tomador, empresa_id: int | None = None) -> Tomador:
        """Grava o tomador (um registro por CPF/CNPJ) e o liga à empresa, se informada."""
        dados = asdict(t)
        dados.pop("id")
        colunas = ", ".join(dados)
        marcas = ", ".join(f":{k}" for k in dados)
        atualiza = ", ".join(f"{k}=excluded.{k}" for k in dados if k != "documento")
        self.con.execute(
            f"INSERT INTO tomadores ({colunas}) VALUES ({marcas}) "
            f"ON CONFLICT(documento) DO UPDATE SET {atualiza}", dados)
        if empresa_id is not None:
            self.ligar_tomador(empresa_id, t.documento)
        return self.tomador(t.documento)

    def ligar_tomador(self, empresa_id: int, documento: str):
        self.con.execute("INSERT OR IGNORE INTO empresa_tomadores (empresa_id, documento) "
                         "VALUES (?, ?)", (empresa_id, documento))

    def tomador(self, documento: str) -> Tomador | None:
        r = self.con.execute("SELECT * FROM tomadores WHERE documento=?", (documento,)).fetchone()
        return _de_linha(Tomador, r) if r else None

    def tomadores(self, filtro: str = "", empresa_id: int | None = None) -> list[Tomador]:
        """Tomadores (de uma empresa, se informada) cujo nome ou documento contém o filtro."""
        f = f"%{filtro}%"
        if empresa_id is None:
            sql, args = ("SELECT * FROM tomadores WHERE (nome LIKE ? OR documento LIKE ?) "
                         "ORDER BY nome", (f, f))
        else:
            sql, args = ("SELECT t.* FROM tomadores t JOIN empresa_tomadores et "
                         "ON et.documento = t.documento AND et.empresa_id = ? "
                         "WHERE (t.nome LIKE ? OR t.documento LIKE ?) ORDER BY t.nome",
                         (empresa_id, f, f))
        return [_de_linha(Tomador, r) for r in self.con.execute(sql, args)]

    # ------------------------------------------------------------ numeração
    def reservar_numero(self, empresa_id: int, ambiente: str, serie: str) -> int:
        """Reserva o próximo nDPS de forma atômica. Número reservado nunca volta."""
        with self._transacao():
            self.con.execute(
                "INSERT OR IGNORE INTO numeracao (empresa_id, ambiente, serie, proximo) "
                "VALUES (?, ?, ?, 1)", (empresa_id, ambiente, serie))
            n = self.con.execute(
                "SELECT proximo FROM numeracao WHERE empresa_id=? AND ambiente=? AND serie=?",
                (empresa_id, ambiente, serie)).fetchone()[0]
            self.con.execute(
                "UPDATE numeracao SET proximo=? WHERE empresa_id=? AND ambiente=? AND serie=?",
                (n + 1, empresa_id, ambiente, serie))
        return n

    def proximo_numero(self, empresa_id: int, ambiente: str, serie: str) -> int:
        r = self.con.execute(
            "SELECT proximo FROM numeracao WHERE empresa_id=? AND ambiente=? AND serie=?",
            (empresa_id, ambiente, serie)).fetchone()
        return r[0] if r else 1

    def definir_proximo_numero(self, empresa_id: int, ambiente: str, serie: str, n: int):
        """Para quem já emitia por outro sistema com a mesma série."""
        if n < 1:
            raise ValueError("Número deve ser >= 1.")
        self.con.execute(
            "INSERT INTO numeracao (empresa_id, ambiente, serie, proximo) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(empresa_id, ambiente, serie) DO UPDATE SET proximo=excluded.proximo",
            (empresa_id, ambiente, serie, n))

    # ------------------------------------------------------------ NSU
    def ultimo_nsu(self, empresa_id: int, ambiente: str) -> int:
        r = self.con.execute("SELECT ultimo_nsu FROM controle_nsu WHERE empresa_id=? AND ambiente=?",
                             (empresa_id, ambiente)).fetchone()
        return r[0] if r else 0

    def gravar_nsu(self, empresa_id: int, ambiente: str, nsu: int):
        self.con.execute(
            "INSERT INTO controle_nsu (empresa_id, ambiente, ultimo_nsu, atualizado_em) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(empresa_id, ambiente) DO UPDATE SET "
            "ultimo_nsu=MAX(ultimo_nsu, excluded.ultimo_nsu), atualizado_em=excluded.atualizado_em",
            (empresa_id, ambiente, nsu, _agora()))

    # ------------------------------------------------------------ notas
    def inserir_nota(self, **campos) -> int:
        campos.setdefault("criado_em", _agora())
        colunas = ", ".join(campos)
        marcas = ", ".join("?" for _ in campos)
        cur = self.con.execute(f"INSERT INTO notas ({colunas}) VALUES ({marcas})",
                               tuple(campos.values()))
        return cur.lastrowid

    def atualizar_nota(self, id_: int, **campos):
        if not campos:
            return
        sets = ", ".join(f"{k}=?" for k in campos)
        self.con.execute(f"UPDATE notas SET {sets} WHERE id=?", (*campos.values(), id_))

    def nota(self, id_: int) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM notas WHERE id=?", (id_,)).fetchone()

    def nota_por_chave(self, chave: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM notas WHERE chave=?", (chave,)).fetchone()

    def notas(self, empresa_id: int, ambiente: str, inicio: str = "", fim: str = "",
              origem: str = "", situacao: str = "", texto: str = "") -> list[sqlite3.Row]:
        sql = ["SELECT id, origem, situacao, serie, n_dps, id_dps, chave, numero, d_compet,"
               " dh_emissao, prestador_doc, prestador_nome, tomador_doc, tomador_nome,"
               " descricao, v_serv, v_liq, v_issqn, mensagem FROM notas"
               " WHERE empresa_id=? AND ambiente=?"]
        args: list = [empresa_id, ambiente]
        if inicio:
            sql.append("AND d_compet >= ?"); args.append(inicio)
        if fim:
            sql.append("AND d_compet <= ?"); args.append(fim)
        if origem:
            sql.append("AND origem = ?"); args.append(origem)
        if situacao:
            sql.append("AND situacao = ?"); args.append(situacao)
        if texto:
            sql.append("AND (tomador_nome LIKE ? OR prestador_nome LIKE ? OR descricao LIKE ?"
                       " OR numero LIKE ? OR chave LIKE ?)")
            args += [f"%{texto}%"] * 5
        sql.append("ORDER BY COALESCE(d_compet, '') DESC, id DESC")
        return self.con.execute(" ".join(sql), args).fetchall()

    def ultima_nota_do_tomador(self, empresa_id: int, documento: str):
        """Nota emitida mais recente (autorizada) para o tomador, com o XML."""
        return self.con.execute(
            "SELECT * FROM notas WHERE empresa_id=? AND origem='emitida' AND tomador_doc=? "
            "AND situacao='autorizada' AND COALESCE(nfse_xml, dps_xml) IS NOT NULL "
            "ORDER BY d_compet DESC, id DESC LIMIT 1", (empresa_id, documento)).fetchone()

    # ------------------------------------------------------------ eventos
    def inserir_evento(self, chave: str, tipo: str, descricao: str, dh: str,
                       xml: bytes, nsu: int | None = None):
        self.con.execute(
            "INSERT OR IGNORE INTO eventos (chave, tipo, descricao, dh, nsu, xml) "
            "VALUES (?, ?, ?, ?, ?, ?)", (chave, tipo, descricao, dh, nsu, xml))

    def eventos(self, chave: str) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM eventos WHERE chave=? ORDER BY dh",
                                (chave,)).fetchall()

    # ------------------------------------------------------------ util
    class _Tx:
        def __init__(self, con):
            self.con = con

        def __enter__(self):
            self.con.trava.acquire()
            self.con.execute("BEGIN IMMEDIATE")

        def __exit__(self, tipo, *_):
            try:
                self.con.execute("ROLLBACK" if tipo else "COMMIT")
            finally:
                self.con.trava.release()

    def _transacao(self):
        return Banco._Tx(self.con)
