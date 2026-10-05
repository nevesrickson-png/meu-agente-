"""Banco da organização: `dados/organizacao.db` (tarefas, notas com busca FTS5, metas e registros de progresso)."""

from __future__ import annotations

import sqlite3

from quiron.nucleo.config import pasta_dados

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarefas (id INTEGER PRIMARY KEY, texto TEXT NOT NULL, cliente TEXT DEFAULT '', prazo TEXT DEFAULT '',
  hora TEXT DEFAULT '', lembrete INTEGER, evento TEXT DEFAULT '', origem TEXT DEFAULT '', criada_em TEXT, concluida_em TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS notas (id INTEGER PRIMARY KEY, texto TEXT NOT NULL, tags TEXT DEFAULT '', cliente TEXT DEFAULT '', criada_em TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS notas_busca USING fts5(texto, content='notas', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS notas_ai AFTER INSERT ON notas BEGIN INSERT INTO notas_busca(rowid, texto) VALUES (new.id, new.texto); END;
CREATE TRIGGER IF NOT EXISTS notas_ad AFTER DELETE ON notas BEGIN INSERT INTO notas_busca(notas_busca, rowid, texto) VALUES ('delete', old.id, old.texto); END;
CREATE TABLE IF NOT EXISTS metas (id INTEGER PRIMARY KEY, texto TEXT NOT NULL, alvo REAL NOT NULL, unidade TEXT DEFAULT '',
  periodo TEXT DEFAULT 'total', prazo TEXT DEFAULT '', criada_em TEXT, ativa INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS metas_registros (id INTEGER PRIMARY KEY, meta INTEGER NOT NULL, valor REAL NOT NULL, quando TEXT, nota TEXT DEFAULT '');
"""


def conectar() -> sqlite3.Connection:
    caminho = pasta_dados() / "organizacao.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con
