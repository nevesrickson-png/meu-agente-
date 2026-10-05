"""Banco de ideias de conteúdo (`dados/conteudo.db`): ideias soltas, pautas salvas e rascunhos, com situação e busca."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from quiron.nucleo.config import pasta_dados

SITUACOES = ("ideia", "rascunho", "publicado", "descartada")


def _con() -> sqlite3.Connection:
    caminho = pasta_dados() / "conteudo.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS ideias (id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, angulo TEXT DEFAULT '', formato TEXT DEFAULT '',
      fontes TEXT DEFAULT '[]', situacao TEXT DEFAULT 'ideia', arquivo TEXT DEFAULT '', criada_em TEXT, atualizada_em TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS ideias_busca USING fts5(titulo, angulo, content='ideias', content_rowid='id',
      tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER IF NOT EXISTS ideias_ai AFTER INSERT ON ideias BEGIN
      INSERT INTO ideias_busca(rowid, titulo, angulo) VALUES (new.id, new.titulo, new.angulo); END;
    CREATE TRIGGER IF NOT EXISTS ideias_au AFTER UPDATE ON ideias BEGIN
      INSERT INTO ideias_busca(ideias_busca, rowid, titulo, angulo) VALUES ('delete', old.id, old.titulo, old.angulo);
      INSERT INTO ideias_busca(rowid, titulo, angulo) VALUES (new.id, new.titulo, new.angulo); END;
    """)
    return con


@dataclass
class Ideia:
    id: int
    titulo: str
    angulo: str = ""
    formato: str = ""
    fontes: list[str] = field(default_factory=list)
    situacao: str = "ideia"
    arquivo: str = ""
    criada_em: str = ""
    atualizada_em: str = ""

    def descrever(self) -> str:
        marca = {"ideia": "💡", "rascunho": "📝", "publicado": "✅", "descartada": "🗑️"}[self.situacao]
        return f"{marca} #{self.id} {self.titulo}" + (f" — {self.angulo}" if self.angulo else "") + (f" [{self.formato}]" if self.formato else "")


def _de(r) -> Ideia:
    return Ideia(**{**{k: r[k] for k in r.keys()}, "fontes": json.loads(r["fontes"] or "[]")})


def criar(titulo: str, angulo: str = "", formato: str = "", fontes: list[str] | None = None, situacao: str = "ideia") -> Ideia:
    titulo = (titulo or "").strip()
    if len(titulo) < 4:
        raise ValueError("escreva a ideia (ex.: /ideia por que a poupança perde para o Tesouro Selic)")
    agora = datetime.now().isoformat(timespec="seconds")
    with _con() as con:
        cur = con.execute("INSERT INTO ideias(titulo, angulo, formato, fontes, situacao, criada_em, atualizada_em) VALUES (?,?,?,?,?,?,?)",
                          (titulo[:200], angulo[:400], formato, json.dumps(fontes or [], ensure_ascii=False), situacao, agora, agora))
        return _de(con.execute("SELECT * FROM ideias WHERE id = ?", (cur.lastrowid,)).fetchone())


def obter(ident: int) -> Ideia:
    with _con() as con:
        r = con.execute("SELECT * FROM ideias WHERE id = ?", (ident,)).fetchone()
    if not r:
        raise ValueError(f"ideia #{ident} não existe")
    return _de(r)


def atualizar(ident: int, **campos) -> Ideia:
    obter(ident)
    if "situacao" in campos and campos["situacao"] not in SITUACOES:
        raise ValueError(f"situação: {', '.join(SITUACOES)}")
    if "fontes" in campos:
        campos["fontes"] = json.dumps(campos["fontes"], ensure_ascii=False)
    campos["atualizada_em"] = datetime.now().isoformat(timespec="seconds")
    with _con() as con:
        con.execute(f"UPDATE ideias SET {', '.join(f'{k} = ?' for k in campos)} WHERE id = ?", (*campos.values(), ident))
    return obter(ident)


def listar(busca: str = "", situacao: str = "", limite: int = 20) -> list[Ideia]:
    with _con() as con:
        if busca.strip():
            consulta = " ".join(f'"{p}"*' for p in re.findall(r"\w+", busca))
            linhas = con.execute("SELECT i.* FROM ideias_busca b JOIN ideias i ON i.id = b.rowid WHERE ideias_busca MATCH ? ORDER BY rank LIMIT ?",
                                 (consulta, limite))
        elif situacao:
            linhas = con.execute("SELECT * FROM ideias WHERE situacao = ? ORDER BY id DESC LIMIT ?", (situacao, limite))
        else:
            linhas = con.execute("SELECT * FROM ideias WHERE situacao IN ('ideia', 'rascunho') ORDER BY id DESC LIMIT ?", (limite,))
        return [_de(r) for r in linhas]
