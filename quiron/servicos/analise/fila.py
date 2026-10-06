"""Fila de análises pesadas + arquivo pesquisável de relatórios (`dados/analise.db`, `dados/relatorios/`).

Pedido → fila → (coleta + cálculos em Python → redação pelo cérebro) → PDF + planilha + Markdown → entrega.
- Tipos de análise se registram com `@tipo("nome", descricao=..., parametros=...)`; cada um devolve um `Relatorio`.
- Mais de um processo pode processar a fila (bot, Terminal, Claude Code): a tarefa é "reservada" com UPDATE atômico.
- `entregue`: o bot do Telegram envia resumo + PDF + planilha das tarefas pedidas pelo Telegram e marca como entregue.
- Arquivo: cada relatório fica em `dados/relatorios/AAAA-MM/<id>-<slug>/` e é indexado (FTS5) para busca.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from quiron.nucleo.config import pasta_dados
from quiron.servicos.analise.relatorio import MODOS, Relatorio

ESQUEMA = """
CREATE TABLE IF NOT EXISTS tarefas (
  id INTEGER PRIMARY KEY, tipo TEXT NOT NULL, parametros TEXT NOT NULL, modo TEXT NOT NULL DEFAULT 'entregar',
  origem TEXT DEFAULT '', chat INTEGER, situacao TEXT NOT NULL DEFAULT 'na fila', criada_em TEXT NOT NULL,
  iniciada_em TEXT, terminada_em TEXT, titulo TEXT DEFAULT '', resumo TEXT DEFAULT '', pasta TEXT DEFAULT '',
  erro TEXT DEFAULT '', entregue INTEGER DEFAULT 0, dono TEXT DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS busca_relatorios USING fts5(
  tarefa_id UNINDEXED, titulo, texto, tokenize = 'unicode61 remove_diacritics 2'
);
"""


@dataclass
class TipoAnalise:
    nome: str
    descricao: str
    parametros: dict[str, str]  # nome → explicação (com o padrão)
    executar: Callable[[dict[str, Any], str], Relatorio]


TIPOS: dict[str, TipoAnalise] = {}


def tipo(nome: str, descricao: str, parametros: dict[str, str] | None = None):
    """Registra um tipo de análise: a função recebe (parâmetros, modo) e devolve um Relatorio pronto."""
    def registrar(func: Callable[[dict[str, Any], str], Relatorio]):
        TIPOS[nome] = TipoAnalise(nome, descricao, parametros or {}, func)
        return func
    return registrar


def carregar_tipos() -> dict[str, TipoAnalise]:
    """Importa os módulos que registram tipos (as análises das Fases 7 a 11 entram aqui)."""
    from quiron.servicos.analise import tipos  # noqa: F401 — registra os tipos

    return TIPOS


@dataclass
class Tarefa:
    id: int
    tipo: str
    parametros: dict[str, Any]
    modo: str
    origem: str
    chat: int | None
    situacao: str
    criada_em: str
    iniciada_em: str | None
    terminada_em: str | None
    titulo: str
    resumo: str
    pasta: str
    erro: str
    entregue: bool

    def arquivos(self) -> dict[str, Path]:
        if not self.pasta:
            return {}
        p = Path(self.pasta)
        return {k: p / n for k, n in (("pdf", "relatorio.pdf"), ("planilha", "planilha.xlsx"), ("markdown", "relatorio.md"))
                if (p / n).exists()}

    def descrever(self) -> str:
        quando = self.terminada_em or self.iniciada_em or self.criada_em
        return f"#{self.id} {self.titulo or self.tipo} — {self.situacao} ({quando[:16].replace('T', ' ')})"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50] or "analise"


class Fila:
    def __init__(self, banco: Path | None = None, pasta_relatorios: Path | None = None):
        self.banco = banco or pasta_dados() / "analise.db"
        self.pasta_relatorios = pasta_relatorios or pasta_dados() / "relatorios"
        self.banco.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.executescript(ESQUEMA)
        self._acordar = threading.Event()
        self._processador: threading.Thread | None = None
        # processo que reservou a tarefa (se ele morrer, a tarefa volta para a fila); máquina:PID porque o Terminal, o bot
        # e o Claude Code processam a mesma fila (no Docker, cada contêiner tem os seus PIDs)
        self.dono = f"{socket.gethostname()}:{os.getpid()}"
        self._em_andamento = _EM_ANDAMENTO.setdefault(str(self.banco), set())  # rodando AGORA neste processo

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.banco, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _tarefa(r: sqlite3.Row) -> Tarefa:
        return Tarefa(r["id"], r["tipo"], json.loads(r["parametros"]), r["modo"], r["origem"] or "", r["chat"],
                      r["situacao"], r["criada_em"], r["iniciada_em"], r["terminada_em"], r["titulo"] or "",
                      r["resumo"] or "", r["pasta"] or "", r["erro"] or "", bool(r["entregue"]))

    # ------------------------------------------------------------ pedidos
    def pedir(self, nome_tipo: str, parametros: dict[str, Any] | None = None, modo: str = "entregar",
              origem: str = "", chat: int | None = None) -> Tarefa:
        tipos = carregar_tipos()
        if nome_tipo not in tipos:
            raise ValueError(f"Tipo de análise desconhecido: {nome_tipo}. Disponíveis: {', '.join(sorted(tipos))}")
        modo = modo if modo in MODOS else "entregar"
        with self._con() as c:
            cur = c.execute("INSERT INTO tarefas (tipo, parametros, modo, origem, chat, criada_em) VALUES (?,?,?,?,?,?)",
                            (nome_tipo, json.dumps(parametros or {}, ensure_ascii=False), modo, origem, chat, _agora()))
            ident = int(cur.lastrowid)
        self._acordar.set()
        return self.obter(ident)  # type: ignore[return-value]

    def obter(self, ident: int) -> Tarefa | None:
        with self._con() as c:
            r = c.execute("SELECT * FROM tarefas WHERE id=?", (ident,)).fetchone()
        return self._tarefa(r) if r else None

    def listar(self, limite: int = 30, situacao: str | None = None) -> list[Tarefa]:
        sql = "SELECT * FROM tarefas" + (" WHERE situacao=?" if situacao else "") + " ORDER BY id DESC LIMIT ?"
        with self._con() as c:
            rows = c.execute(sql, (situacao, limite) if situacao else (limite,)).fetchall()
        return [self._tarefa(r) for r in rows]

    def posicao(self, ident: int) -> int:
        """Quantas tarefas estão na frente (0 = é a próxima ou já está rodando)."""
        with self._con() as c:
            return c.execute("SELECT COUNT(*) FROM tarefas WHERE situacao='na fila' AND id < ?", (ident,)).fetchone()[0]

    # ------------------------------------------------------------ processamento
    def _reservar(self) -> Tarefa | None:
        with self._con() as c:
            r = c.execute("SELECT id FROM tarefas WHERE situacao='na fila' ORDER BY id LIMIT 1").fetchone()
            if not r:
                return None
            self._em_andamento.add(r["id"])  # antes do UPDATE: outra Fila deste processo não a dá como órfã no meio
            ok = c.execute("UPDATE tarefas SET situacao='rodando', iniciada_em=?, dono=? WHERE id=? AND situacao='na fila'",
                           (_agora(), self.dono, r["id"])).rowcount
            if not ok:
                self._em_andamento.discard(r["id"])
        return self.obter(r["id"]) if ok else self._reservar()

    def processar_uma(self) -> Tarefa | None:
        t = self._reservar()
        if not t:
            return None
        try:
            tipo_ = carregar_tipos()[t.tipo]
            rel = tipo_.executar(t.parametros, t.modo)
            rel.modo, rel.parametros = t.modo, t.parametros
            pasta = self.pasta_relatorios / datetime.now().strftime("%Y-%m") / f"{t.id:04d}-{_slug(rel.titulo)}"
            rel.salvar(pasta)
            with self._con() as c:
                ok = c.execute("UPDATE tarefas SET situacao='pronta', terminada_em=?, titulo=?, resumo=?, pasta=? "
                               "WHERE id=? AND dono=? AND situacao='rodando'",
                               (_agora(), rel.titulo, "\n".join(rel.resumo), str(pasta), t.id, self.dono)).rowcount
                if not ok:  # outro processo assumiu a tarefa (a nossa foi dada como órfã): não grava por cima
                    return self.obter(t.id)
                c.execute("INSERT INTO busca_relatorios (tarefa_id, titulo, texto) VALUES (?,?,?)",
                          (t.id, rel.titulo, rel.markdown()))
        except Exception as e:  # noqa: BLE001 — uma análise com problema não trava a fila
            logging.exception("análise #%s falhou", t.id)
            with self._con() as c:
                c.execute("UPDATE tarefas SET situacao='erro', terminada_em=?, erro=? WHERE id=? AND dono=? AND situacao='rodando'",
                          (_agora(), f"{type(e).__name__}: {str(e)[:300]}", t.id, self.dono))
        finally:
            self._em_andamento.discard(t.id)
        return self.obter(t.id)

    def repetir(self, ident: int) -> Tarefa | None:
        """Análise que falhou volta para a fila (mesmos parâmetros). None se não existe ou não falhou."""
        with self._con() as c:
            ok = c.execute("UPDATE tarefas SET situacao='na fila', erro='', entregue=0, dono='', iniciada_em=NULL, "
                           "terminada_em=NULL WHERE id=? AND situacao='erro'", (ident,)).rowcount
        if ok:
            self._acordar.set()
        return self.obter(ident) if ok else None

    def recuperar_orfas(self) -> int:
        """Tarefas 'rodando' cujo processo morreu (programa fechado no meio) voltam à fila. Processo vivo só perde a tarefa
        depois de 6 h (travada de verdade): análises lentas (1º download da CVM) passam fácil de 30 min."""
        import psutil

        maquina = socket.gethostname()
        with self._con() as c:
            rodando = c.execute("SELECT id, dono, iniciada_em FROM tarefas WHERE situacao='rodando'").fetchall()
            agora = datetime.now().timestamp()

            def vivo(ident: int, dono: str, iniciada: str) -> bool:
                if dono == self.dono:  # "eu" — mas o contêiner reiniciado repete nome e PID: só vale se está rodando aqui
                    return ident in self._em_andamento
                host, _, pid = dono.rpartition(":")
                if host and host != maquina:  # outra máquina/contêiner: não dá para conferir o PID (vale o limite de 6 h)
                    return True
                try:
                    return pid.isdigit() and psutil.pid_exists(int(pid))
                except (OverflowError, ValueError):
                    return False

            orfas = [r["id"] for r in rodando if not vivo(r["id"], r["dono"] or "", r["iniciada_em"])
                     or datetime.fromisoformat(r["iniciada_em"]).timestamp() < agora - 6 * 3600]
            for ident in orfas:
                c.execute("UPDATE tarefas SET situacao='na fila', dono='' WHERE id=? AND situacao='rodando'", (ident,))
        return len(orfas)

    def iniciar_processador(self) -> None:
        if self._processador and self._processador.is_alive():
            return
        self.recuperar_orfas()

        def laco() -> None:
            while True:
                self.recuperar_orfas()
                while self.processar_uma():
                    pass
                self._acordar.wait(timeout=20)
                self._acordar.clear()

        self._processador = threading.Thread(target=laco, name="analises", daemon=True)
        self._processador.start()

    # ------------------------------------------------------------ entrega e arquivo
    def a_entregar(self, origem: str = "telegram") -> list[Tarefa]:
        with self._con() as c:
            rows = c.execute("SELECT * FROM tarefas WHERE origem=? AND entregue=0 AND situacao IN ('pronta','erro') "
                             "ORDER BY id", (origem,)).fetchall()
        return [self._tarefa(r) for r in rows]

    def marcar_entregue(self, ident: int) -> None:
        with self._con() as c:
            c.execute("UPDATE tarefas SET entregue=1 WHERE id=?", (ident,))

    def buscar(self, termo: str, limite: int = 10) -> list[Tarefa]:
        palavras = [re.sub(r"[^\w]", "", p) for p in termo.split()]
        consulta = " ".join(f'"{p}"*' for p in palavras if p)
        if not consulta:
            return self.listar(limite, "pronta")
        with self._con() as c:
            ids = [r[0] for r in c.execute("SELECT tarefa_id FROM busca_relatorios WHERE busca_relatorios MATCH ? "
                                           "ORDER BY rank LIMIT ?", (consulta, limite))]
        return [t for t in (self.obter(i) for i in ids) if t]

    def relatorio(self, ident: int) -> Relatorio | None:
        t = self.obter(ident)
        if not t or not t.pasta or not (Path(t.pasta) / "relatorio.json").exists():
            return None
        return Relatorio.de_dict(json.loads((Path(t.pasta) / "relatorio.json").read_text(encoding="utf-8")))


_FILA: Fila | None = None


_EM_ANDAMENTO: dict[str, set[int]] = {}


def fila() -> Fila:
    global _FILA
    if _FILA is None or _FILA.banco != pasta_dados() / "analise.db":
        _FILA = Fila()
    return _FILA


def motivo_amigavel(erro: str) -> str:
    """O erro técnico vira uma frase que o Rickson entende (o detalhe fica no registro)."""
    e = erro or ""
    if "PermissionError" in e or "WinError 5" in e or "Acesso negado" in e:
        return "o Windows não deixou gravar o arquivo do relatório (antivírus ou o arquivo aberto em outro programa)"
    if any(x in e for x in ("ConnectError", "ConnectTimeout", "ReadTimeout", "HTTPStatusError", "RemoteProtocolError")):
        return "uma fonte de dados não respondeu (internet ou site fora do ar)"
    if "CerebroIndisponivel" in e or "RateLimit" in e or "429" in e:
        return "os modelos de IA grátis estão sem cota agora"
    if "não encontr" in e.lower() or "not found" in e.lower() or "KeyError" in e:
        return "não encontrei o ativo/fundo pedido nas bases (confira o código ou o nome)"
    if "No space left" in e or "Errno 28" in e:
        return "falta espaço em disco"
    return "um erro inesperado (detalhe salvo no registro)"
