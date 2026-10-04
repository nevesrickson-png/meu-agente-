"""Memória de conversas (ideia do Hermes): todo o histórico em SQLite com busca de texto completo (FTS5),
memória recente por conversa e compactação automática das trocas antigas em um resumo.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from quiron.nucleo.config import pasta_dados


@dataclass
class Trecho:
    chat: int
    quando: datetime
    papel: str
    texto: str


class Memoria:
    def __init__(self, caminho: Path | None = None):
        caminho = caminho or pasta_dados() / "conversas.db"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        with self.con:
            self.con.execute("CREATE TABLE IF NOT EXISTS mensagens (id INTEGER PRIMARY KEY, chat INTEGER, quando TEXT, papel TEXT, texto TEXT)")
            self.con.execute("CREATE INDEX IF NOT EXISTS mensagens_chat ON mensagens(chat, id)")
            self.con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mensagens_busca USING fts5(texto, content='mensagens', content_rowid='id', "
                             "tokenize='unicode61 remove_diacritics 2')")
            self.con.execute("CREATE TRIGGER IF NOT EXISTS mensagens_ai AFTER INSERT ON mensagens BEGIN "
                             "INSERT INTO mensagens_busca(rowid, texto) VALUES (new.id, new.texto); END")
            self.con.execute("CREATE TABLE IF NOT EXISTS resumos (chat INTEGER PRIMARY KEY, ate_id INTEGER, resumo TEXT)")

    # ------------------------------------------------------------ gravar e ler
    def guardar(self, chat: int, papel: str, texto: str) -> None:
        with self.con:
            self.con.execute("INSERT INTO mensagens(chat, quando, papel, texto) VALUES (?,?,?,?)",
                             (chat, datetime.now(timezone.utc).isoformat(), papel, texto))

    def _desde_resumo(self, chat: int) -> list[tuple[int, str, str]]:
        ate = self.con.execute("SELECT ate_id FROM resumos WHERE chat = ?", (chat,)).fetchone()
        return self.con.execute("SELECT id, papel, texto FROM mensagens WHERE chat = ? AND id > ? ORDER BY id",
                                (chat, ate[0] if ate else 0)).fetchall()

    def historico(self, chat: int) -> list[dict[str, Any]]:
        """Mensagens para o modelo: resumo das antigas (se houver) + trocas recentes na íntegra."""
        saida: list[dict[str, Any]] = []
        r = self.con.execute("SELECT resumo FROM resumos WHERE chat = ?", (chat,)).fetchone()
        if r and r[0]:
            saida.append({"role": "user", "content": f"[Resumo da nossa conversa até aqui]\n{r[0]}"})
            saida.append({"role": "assistant", "content": "Entendido, sigo a partir desse contexto."})
        saida += [{"role": p, "content": t} for _, p, t in self._desde_resumo(chat)]
        return saida

    def compactar(self, chat: int, manter: int, limite: int, resumir: Callable[[str, str], str]) -> bool:
        """Se houver mais de `limite` mensagens desde o último resumo, resume as antigas e mantém as `manter` últimas."""
        linhas = self._desde_resumo(chat)
        if len(linhas) <= limite:
            return False
        antigas, ultima_antiga = linhas[: len(linhas) - manter], linhas[len(linhas) - manter - 1][0]
        atual = (self.con.execute("SELECT resumo FROM resumos WHERE chat = ?", (chat,)).fetchone() or [""])[0]
        texto = "\n".join(f"{'Rickson' if p == 'user' else 'Quíron'}: {t}" for _, p, t in antigas)
        novo = resumir(atual or "", texto)
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO resumos VALUES (?,?,?)", (chat, ultima_antiga, novo))
        return True

    def reiniciar(self, chat: int) -> None:
        """/novo: começa do zero o contexto (o histórico continua pesquisável)."""
        ultimo = self.con.execute("SELECT MAX(id) FROM mensagens WHERE chat = ?", (chat,)).fetchone()[0] or 0
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO resumos VALUES (?,?,?)", (chat, ultimo, ""))

    # ------------------------------------------------------------ busca
    def buscar(self, termo: str, limite: int = 8) -> list[Trecho]:
        consulta = " ".join(f'"{p}"*' for p in termo.replace('"', " ").split() if p)
        if not consulta:
            return []
        linhas = self.con.execute(
            "SELECT m.chat, m.quando, m.papel, m.texto FROM mensagens_busca b JOIN mensagens m ON m.id = b.rowid "
            "WHERE mensagens_busca MATCH ? ORDER BY m.id DESC LIMIT ?", (consulta, limite)).fetchall()
        return [Trecho(c, datetime.fromisoformat(q), p, t) for c, q, p, t in linhas]

    def exportar(self, chat: int) -> str:
        return json.dumps([{"papel": p, "texto": t} for _, p, t in self._desde_resumo(chat)], ensure_ascii=False)
