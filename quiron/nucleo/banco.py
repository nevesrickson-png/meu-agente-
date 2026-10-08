"""Conexão SQLite padrão do Quíron.

Bot, Terminal e os servidores MCP (processos separados) gravam nos mesmos arquivos de `dados/`. Com o modo padrão do
SQLite (diário de rollback, espera de 5 s) um gravador bloqueia os leitores e, sob carga, aparece "database is locked".
Aqui: modo WAL (leitor não bloqueia gravador; a escolha fica gravada no arquivo) e espera de até 30 s pela trava.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_WAL: set[str] = set()
_trava = threading.Lock()


def conectar(caminho: Path | str, *, linhas: bool = False, mesma_thread: bool = True, espera: float = 30.0) -> sqlite3.Connection:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=espera, check_same_thread=mesma_thread)
    chave = str(caminho.resolve())
    if chave not in _WAL:
        try:
            con.execute("PRAGMA journal_mode=WAL")
            with _trava:
                _WAL.add(chave)
        except sqlite3.OperationalError:  # outro processo trocando o modo agora: fica para a próxima conexão
            pass
    if linhas:
        con.row_factory = sqlite3.Row
    return con
