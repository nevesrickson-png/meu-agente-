"""Acesso HTTP às fontes públicas, com cache em SQLite (`dados/quiron.db`).

Todo dado guarda a fonte e o horário em que foi obtido. Se a fonte cair, o último valor em cache é
devolvido marcado como "desatualizado" — melhor um número velho identificado do que nenhum.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from quiron.nucleo.config import pasta_dados

logging.getLogger("httpx").setLevel(logging.WARNING)  # sem uma linha de log por consulta

AGENTE = "Quiron/0.1 (uso pessoal; contato via GitHub nevesrickson-png)"
_cliente: httpx.Client | None = None


def definir_cliente(cliente: httpx.Client | None) -> None:
    """Troca o cliente HTTP (nos testes, um cliente com respostas gravadas)."""
    global _cliente
    _cliente = cliente


def cliente() -> httpx.Client:
    global _cliente
    if _cliente is None:
        _cliente = httpx.Client(headers={"User-Agent": AGENTE}, timeout=30, follow_redirects=True)
    return _cliente


class FonteIndisponivel(RuntimeError):
    pass


@dataclass
class Resposta:
    conteudo: Any  # dict/list (json), str (texto) ou bytes
    fonte: str
    obtido_em: datetime
    desatualizado: bool = False


def _banco() -> sqlite3.Connection:
    caminho: Path = pasta_dados() / "quiron.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.execute(
        "CREATE TABLE IF NOT EXISTS cache (chave TEXT PRIMARY KEY, conteudo BLOB, formato TEXT, fonte TEXT, obtido_em REAL)"
    )
    return con


def _chave(url: str, params: dict | None, metodo: str, dados: dict | None, corpo: str | None = None) -> str:
    return json.dumps([metodo, url, sorted((params or {}).items()), sorted((dados or {}).items()), corpo], ensure_ascii=False)


def _decodificar(bruto: bytes, formato: str, codificacao: str) -> Any:
    if formato == "bytes":
        return bruto
    texto = bruto.decode(codificacao, errors="replace")
    return json.loads(texto) if formato == "json" else texto


def obter(
    url: str,
    *,
    fonte: str,
    ttl: int,
    params: dict | None = None,
    formato: str = "json",
    metodo: str = "GET",
    dados: dict | None = None,
    codificacao: str = "utf-8",
    corpo: str | None = None,
    cabecalhos: dict | None = None,
) -> Resposta:
    """Busca com cache. `ttl` em segundos (quanto tempo o dado guardado vale)."""
    chave = _chave(url, params, metodo, dados, corpo)
    with _banco() as con:
        linha = con.execute("SELECT conteudo, obtido_em FROM cache WHERE chave = ?", (chave,)).fetchone()
    if linha and time.time() - linha[1] < ttl:
        return Resposta(_decodificar(linha[0], formato, codificacao), fonte, datetime.fromtimestamp(linha[1]))
    try:
        extras = {"content": corpo.encode("utf-8")} if corpo is not None else {"data": dados}
        r = cliente().request(metodo, url, params=params, headers=cabecalhos, **extras)
        r.raise_for_status()
        bruto = r.content
        conteudo = _decodificar(bruto, formato, codificacao)  # valida antes de guardar
    except (httpx.HTTPError, ValueError) as e:
        if linha:  # fonte fora do ar: devolve o último valor conhecido, avisando
            return Resposta(_decodificar(linha[0], formato, codificacao), fonte, datetime.fromtimestamp(linha[1]), True)
        raise FonteIndisponivel(f"falha ao consultar {fonte}: {type(e).__name__}: {str(e)[:150]}") from e
    agora = time.time()
    with _banco() as con:
        con.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)", (chave, bruto, formato, fonte, agora))
    return Resposta(conteudo, fonte, datetime.fromtimestamp(agora))


def numero_br(texto: str | float | int | None) -> float | None:
    """'1.234,56' → 1234.56; '15.00' → 15.0; vazio → None."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    t = str(texto).strip().replace("%", "")
    if not t or t in {"-", "--", "N/D"}:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)
