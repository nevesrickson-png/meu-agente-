"""LGPD — `/esquecer CLI-XXX` apaga tudo o que o Quíron guardou sobre um cliente.

Apaga: ficha (e histórico), carteiras lidas, relatórios (tarefas da fila + arquivos), trechos de conversa, linhas da
memória e do diário que citam o código. Não há mapa código → nome aqui (ele só existe na versão offline do Rickson).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.planejamento.ficha import codigo


@dataclass
class Apagado:
    cliente: str
    itens: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.itens.values())

    def descrever(self) -> str:
        if not self.total:
            return f"Nada guardado sobre {self.cliente}."
        partes = [f"{n} {nome}" for nome, n in self.itens.items() if n]
        return f"🧹 {self.cliente} esquecido: " + ", ".join(partes) + "."


def _cita(texto: str, cod: str) -> bool:
    """O código aparece inteiro (CLI-01 não apaga CLI-012)."""
    return re.search(rf"(?<![A-Za-z0-9-]){re.escape(cod)}(?![A-Za-z0-9])", texto or "", re.I) is not None


def esquecer_cliente(cliente: str) -> Apagado:
    cod = codigo(cliente)
    raiz = pasta_dados()
    r = Apagado(cod)

    fichas = [p for p in (raiz / "fichas").glob(f"{cod}.json")] + list((raiz / "fichas" / "historico").glob(f"{cod}-*.json"))
    for p in fichas:
        p.unlink()
    r.itens["fichas/versões"] = len(fichas)

    n = 0
    for p in (raiz / "carteiras").glob("CART-*.json"):
        try:
            if _cita(p.read_text(encoding="utf-8"), cod):
                p.unlink()
                n += 1
        except (OSError, json.JSONDecodeError):
            continue
    r.itens["carteiras"] = n

    r.itens["relatórios"] = _apagar_relatorios(raiz / "analise.db", cod)
    r.itens["mensagens de conversa"] = _apagar_conversas(raiz / "conversas.db", cod)

    n = 0
    ws = raiz / "workspace"
    for arq in [ws / "MEMORIA.md", *sorted((ws / "diario").glob("*.md"))]:
        if not arq.exists():
            continue
        linhas = arq.read_text(encoding="utf-8").splitlines()
        restantes = [l for l in linhas if not _cita(l, cod)]
        if len(restantes) != len(linhas):
            n += len(linhas) - len(restantes)
            arq.write_text("\n".join(restantes) + "\n", encoding="utf-8")
    r.itens["linhas de memória/diário"] = n
    return r


def _apagar_relatorios(banco: Path, cod: str) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        padrao = f"%{cod}%"
        linhas = [(i, p) for i, p, *textos in con.execute(
            "SELECT id, pasta, parametros, titulo, resumo FROM tarefas WHERE parametros LIKE ? OR titulo LIKE ? OR resumo LIKE ?",
            (padrao, padrao, padrao)) if any(_cita(t, cod) for t in textos)]
        for ident, pasta in linhas:
            if pasta and Path(pasta).exists():
                shutil.rmtree(pasta, ignore_errors=True)
            con.execute("DELETE FROM tarefas WHERE id = ?", (ident,))
            con.execute("DELETE FROM busca_relatorios WHERE tarefa_id = ?", (ident,))
        con.commit()
        return len(linhas)
    finally:
        con.close()


def _apagar_conversas(banco: Path, cod: str) -> int:
    if not banco.exists():
        return 0
    con = sqlite3.connect(banco)
    try:
        ids = [i for i, t in con.execute("SELECT id, texto FROM mensagens WHERE texto LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("DELETE FROM mensagens WHERE id = ?", [(i,) for i in ids])
        n = len(ids)
        chats = [c for c, t in con.execute("SELECT chat, resumo FROM resumos WHERE resumo LIKE ?", (f"%{cod}%",)) if _cita(t, cod)]
        con.executemany("DELETE FROM resumos WHERE chat = ?", [(c,) for c in chats])
        if n:
            con.execute("INSERT INTO mensagens_busca(mensagens_busca) VALUES('rebuild')")
        con.commit()
        return n
    finally:
        con.close()
