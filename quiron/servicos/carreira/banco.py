"""Banco da carreira: `dados/carreira.db` (radar, teses e revisões, portfólio, provas e competências)."""

from __future__ import annotations

import sqlite3

from quiron.nucleo.config import pasta_dados

ESQUEMA = """
CREATE TABLE IF NOT EXISTS radar (id INTEGER PRIMARY KEY, link TEXT UNIQUE, fonte TEXT, titulo TEXT, resumo TEXT, publicado_em TEXT,
  temas TEXT DEFAULT '', relevancia INTEGER DEFAULT 0, visto_em TEXT DEFAULT '', coletado_em TEXT);
CREATE TABLE IF NOT EXISTS teses (id INTEGER PRIMARY KEY, titulo TEXT, tese TEXT, ativo TEXT DEFAULT '', direcao TEXT DEFAULT '',
  premissas TEXT DEFAULT '[]', invalidacao TEXT DEFAULT '[]', confianca REAL, criada_em TEXT, revisar_em TEXT DEFAULT '',
  preco_inicial REAL, benchmark TEXT DEFAULT '', bench_inicial REAL, lembrete INTEGER, situacao TEXT DEFAULT 'aberta',
  resultado REAL, resolvida_em TEXT DEFAULT '', aprendizado TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS revisoes_teses (id INTEGER PRIMARY KEY, tese INTEGER, quando TEXT, preco REAL, bench REAL, nota TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS portfolio (tarefa INTEGER PRIMARY KEY, comentario TEXT DEFAULT '', adicionado_em TEXT);
CREATE TABLE IF NOT EXISTS provas (cert TEXT PRIMARY KEY, data TEXT DEFAULT '', situacao TEXT DEFAULT 'planejada', atualizado_em TEXT);
CREATE TABLE IF NOT EXISTS entrevistas (id INTEGER PRIMARY KEY, cargo TEXT, iniciada_em TEXT, encerrada_em TEXT DEFAULT '',
  mensagens TEXT DEFAULT '[]', feedback TEXT);
CREATE TABLE IF NOT EXISTS competencias (id INTEGER PRIMARY KEY, nome TEXT, nota INTEGER, quando TEXT);
"""


def conectar() -> sqlite3.Connection:
    caminho = pasta_dados() / "carreira.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con
