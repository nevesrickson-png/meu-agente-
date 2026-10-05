"""Notas rápidas (`/nota texto #tag`) com busca por palavra (FTS5, sem acento). Cliente só como CLI-XXX."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from quiron.servicos.organizacao.banco import conectar

RE_TAG = re.compile(r"#([\wÀ-ÿ-]+)")
RE_CLIENTE = re.compile(r"\bCLI-\w+\b", re.I)


@dataclass
class Nota:
    id: int
    texto: str
    tags: str
    cliente: str
    criada_em: str

    def descrever(self) -> str:
        quando = datetime.fromisoformat(self.criada_em).strftime("%d/%m %H:%M")
        return f"🗒️ #{self.id} ({quando}) {self.texto}"


def _de(r) -> Nota:
    return Nota(r["id"], r["texto"], r["tags"], r["cliente"], r["criada_em"])


def criar(texto: str, agora: datetime | None = None) -> Nota:
    texto = (texto or "").strip()
    if len(texto) < 2:
        raise ValueError("escreva a nota (ex.: /nota ideia de pauta: duration explicada com gangorra #conteudo)")
    tags = " ".join(sorted({t.lower() for t in RE_TAG.findall(texto)}))
    cliente = (RE_CLIENTE.search(texto) or [""])[0].upper()
    agora = agora or datetime.now()
    with conectar() as con:
        cur = con.execute("INSERT INTO notas(texto, tags, cliente, criada_em) VALUES (?,?,?,?)",
                          (texto[:4000], tags, cliente, agora.isoformat(timespec="seconds")))
        return _de(con.execute("SELECT * FROM notas WHERE id = ?", (cur.lastrowid,)).fetchone())


def buscar(termo: str = "", limite: int = 15) -> list[Nota]:
    with conectar() as con:
        termo = (termo or "").strip()
        if not termo:
            linhas = con.execute("SELECT * FROM notas ORDER BY id DESC LIMIT ?", (limite,))
        elif termo.startswith("#"):
            linhas = con.execute("SELECT * FROM notas WHERE ' ' || tags || ' ' LIKE ? ORDER BY id DESC LIMIT ?",
                                 (f"% {termo[1:].lower()} %", limite))
        else:
            consulta = " ".join(f'"{p}"*' for p in re.findall(r"\w+", termo))
            if not consulta:
                return []
            linhas = con.execute("SELECT n.* FROM notas_busca b JOIN notas n ON n.id = b.rowid WHERE notas_busca MATCH ? "
                                 "ORDER BY rank LIMIT ?", (consulta, limite))
        return [_de(r) for r in linhas]


def remover(ident: int) -> bool:
    with conectar() as con:
        return con.execute("DELETE FROM notas WHERE id = ?", (ident,)).rowcount > 0


def descrever(itens: list[Nota], termo: str = "") -> str:
    if not itens:
        return f"Nenhuma nota{' com “' + termo + '”' if termo else ''}. Crie com /nota <texto> (#tags ajudam a achar depois)."
    return "\n".join(n.descrever() for n in itens)
