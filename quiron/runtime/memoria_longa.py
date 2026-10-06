"""Memória persistente do Quíron, em camadas (o melhor de MemGPT/Letta, Mem0 e Generative Agents):

1. **Trabalho** — as últimas trocas da conversa na íntegra (`memoria.py`, `conversas.db`).
2. **Fatos** (semântica) — o que o Quíron sabe sobre o Rickson: perfil, preferências, objetivos, trabalho, estudo,
   rotinas, clientes por CLI-XXX. Cada fato tem categoria, importância (1–5), origem e histórico de uso. Extraídos
   SOZINHOS das conversas (o modelo propõe adicionar/atualizar/apagar comparando com o que já existe — estilo Mem0) e
   também guardados na hora quando ele diz "lembre que…". Fato novo que contradiz um antigo o substitui (o antigo fica
   arquivado, não some).
3. **Episódios** — cada conversa vira um registro permanente (título, resumo, decisões, pendências), nunca sobrescrito.
4. **Eventos** — o que ele fez pelos comandos diretos (tarefas, simulados, pós-reunião, teses…).

Recuperação automática antes de cada resposta: núcleo (fatos mais importantes) + fatos e episódios relevantes ao pedido
(busca híbrida: significado por embeddings + palavras por FTS5 + importância + recência) + atividades recentes.
Consolidação diária: junta fatos repetidos, arquiva os pouco importantes e sem uso, regenera o `MEMORIA.md` — que o
Rickson pode editar à mão (a edição volta para o banco).

Privacidade: fato com CPF, telefone, e-mail ou outro dado pessoal é recusado em Python (clientes só como CLI-XXX).
Tudo em `dados/memoria.db` (entra no backup e no pacote offline)."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import struct
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from quiron.nucleo.config import pasta_dados

CATEGORIAS = {
    "perfil": "Quem ele é",
    "preferencia": "Preferências e jeito de trabalhar",
    "objetivo": "Objetivos e metas",
    "trabalho": "Trabalho e negócio",
    "estudo": "Estudo e certificações",
    "cliente": "Clientes (só CLI-XXX)",
    "rotina": "Rotinas e agenda",
    "mercado": "Visões e teses de mercado",
    "geral": "Outros",
}
RE_DADO_PESSOAL = re.compile(
    r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"            # CPF
    r"|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"    # CNPJ
    r"|\(?\b\d{2}\)?\s?9\d{4}-?\d{4}\b"            # celular
    r"|[\w.+-]+@[\w-]+\.[\w.]+"                    # e-mail
    r"|\b(?:ag[eê]ncia|conta)\s*(?:n[ºo°]\s*)?\d{3,}", re.I)
RE_LEMBRE = re.compile(r"^\s*(?:quíron,?\s*|quiron,?\s*)?(?:por favor,?\s*)?(?:lembre|lembra|grave|guarde|anote|memorize)"
                       r"(?:-se)?\s+(?:que|de que|disso:?|isto:?|isso:?)\s+(?P<fato>.{6,400})$", re.I | re.S)
RE_PISTAS = re.compile(r"\b(eu prefiro|prefiro|não gosto|nao gosto|gosto de|meu objetivo|minha meta|quero ser|sempre|nunca|"
                       r"a partir de agora|daqui pra frente|daqui para frente|me chame|meu nome|trabalho com|minha prova|"
                       r"vou fazer a prova|estou estudando|meu cliente|o CLI-\d+|mudei|não uso mais|nao uso mais)\b", re.I)
SIMILAR_REPETIDO = 0.93   # acima disso, é o mesmo fato (atualiza em vez de duplicar)
INATIVIDADE_EPISODIO = timedelta(minutes=30)
MAX_MSGS_EPISODIO = 40    # conversa muito longa vira episódio mesmo sem pausa


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _agora()).isoformat(timespec="seconds")


def _chave(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto.casefold())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def tem_dado_pessoal(texto: str) -> bool:
    return bool(RE_DADO_PESSOAL.search(texto or ""))


def _vet_bytes(v: list[float] | None) -> bytes | None:
    return struct.pack(f"{len(v)}f", *v) if v else None


def _vet_lista(b: bytes | None) -> list[float] | None:
    return list(struct.unpack(f"{len(b) // 4}f", b)) if b else None


def _cos(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


@dataclass
class Fato:
    id: int
    texto: str
    categoria: str = "geral"
    importancia: int = 3
    origem: str = "extraido"   # dito | extraido | editado | importado
    criado_em: str = ""
    atualizado_em: str = ""
    usado_em: str = ""
    usos: int = 0
    ativo: bool = True
    substituido_por: int | None = None

    def linha(self) -> str:
        return f"[#{self.id}] {self.texto}"


@dataclass
class Episodio:
    id: int
    chat: int
    inicio: str
    fim: str
    titulo: str
    resumo: str
    pendencias: list[str] = field(default_factory=list)

    def linha(self) -> str:
        quando = datetime.fromisoformat(self.inicio).astimezone(_brt()).strftime("%d/%m/%Y")
        pend = f" Pendências: {'; '.join(self.pendencias)}." if self.pendencias else ""
        return f"[{quando}] {self.titulo} — {self.resumo}{pend}"


def _brt():
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/Sao_Paulo")


# ---------------------------------------------------------------- embeddings (opcionais, com plano B por palavras)
class _Vetorizador:
    """Usa o mesmo motor de embeddings da biblioteca; se não houver (sem download, offline), busca só por palavras."""

    def __init__(self) -> None:
        self._motor: Any = None
        self._falhou = False

    def nome(self) -> str:
        m = self._obter()
        return getattr(m, "nome", "") if m else ""

    def _obter(self):
        if self._motor is None and not self._falhou:
            try:
                from quiron.servicos.biblioteca.embeddings import Lexico, obter_embeddings

                motor = obter_embeddings()
                modelos = pasta_dados() / "modelos"
                if type(motor).__name__ == "FastEmbed" and not (modelos.exists() and any(modelos.glob("models--*"))):
                    motor = Lexico()  # modelo ainda não baixado: não trava a resposta com um download de ~220 MB
                self._motor = motor
            except Exception as e:  # noqa: BLE001
                logging.info("memória sem embeddings (%s): busca por palavras", type(e).__name__)
                self._falhou = True
        return self._motor

    def vetores(self, textos: list[str]) -> list[list[float]] | None:
        m = self._obter()
        if not m or not textos:
            return None
        try:
            return m.vetores(textos)
        except Exception as e:  # noqa: BLE001 — modelo não baixado, sem memória etc.
            logging.info("embeddings indisponíveis (%s): busca por palavras", type(e).__name__)
            self._falhou, self._motor = True, None
            return None


# ---------------------------------------------------------------- banco
class MemoriaLonga:
    def __init__(self, caminho: Path | None = None, vetorizador: _Vetorizador | None = None,
                 arquivo_md: Path | None = None) -> None:
        self.caminho = caminho or pasta_dados() / "memoria.db"
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_md = arquivo_md or pasta_dados() / "workspace" / "MEMORIA.md"
        self.vet = vetorizador or _Vetorizador()
        self._trava = threading.RLock()
        self.con = sqlite3.connect(self.caminho, check_same_thread=False, timeout=15)
        self.con.row_factory = sqlite3.Row
        with self.con:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=FULL")  # cada gravação vai para o disco (queda de luz não perde memória)
            self.con.executescript("""
            CREATE TABLE IF NOT EXISTS fatos (id INTEGER PRIMARY KEY, texto TEXT NOT NULL, categoria TEXT DEFAULT 'geral',
                importancia INTEGER DEFAULT 3, origem TEXT DEFAULT 'extraido', criado_em TEXT, atualizado_em TEXT,
                usado_em TEXT DEFAULT '', usos INTEGER DEFAULT 0, ativo INTEGER DEFAULT 1, substituido_por INTEGER,
                vetor BLOB, modelo_vetor TEXT DEFAULT '');
            CREATE VIRTUAL TABLE IF NOT EXISTS fatos_busca USING fts5(texto, content='fatos', content_rowid='id',
                tokenize='unicode61 remove_diacritics 2');
            CREATE TRIGGER IF NOT EXISTS fatos_ai AFTER INSERT ON fatos BEGIN
                INSERT INTO fatos_busca(rowid, texto) VALUES (new.id, new.texto); END;
            CREATE TRIGGER IF NOT EXISTS fatos_au AFTER UPDATE OF texto ON fatos BEGIN
                INSERT INTO fatos_busca(fatos_busca, rowid, texto) VALUES ('delete', old.id, old.texto);
                INSERT INTO fatos_busca(rowid, texto) VALUES (new.id, new.texto); END;
            CREATE TABLE IF NOT EXISTS episodios (id INTEGER PRIMARY KEY, chat INTEGER, inicio TEXT, fim TEXT, titulo TEXT,
                resumo TEXT, pendencias TEXT DEFAULT '[]', msg_de INTEGER, msg_ate INTEGER, vetor BLOB, modelo_vetor TEXT DEFAULT '');
            CREATE VIRTUAL TABLE IF NOT EXISTS episodios_busca USING fts5(texto, tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, quando TEXT, tipo TEXT, texto TEXT);
            CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT);
            CREATE TABLE IF NOT EXISTS registros (id INTEGER PRIMARY KEY, quando TEXT NOT NULL, canal TEXT, chat INTEGER,
                tipo TEXT NOT NULL, conteudo TEXT, meta TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS registros_quando ON registros(quando);
            CREATE VIRTUAL TABLE IF NOT EXISTS registros_busca USING fts5(conteudo, content='registros', content_rowid='id',
                tokenize='unicode61 remove_diacritics 2');
            CREATE TRIGGER IF NOT EXISTS registros_ai AFTER INSERT ON registros BEGIN
                INSERT INTO registros_busca(rowid, conteudo) VALUES (new.id, new.conteudo); END;
            """)
        self._migrar_memoria_md_antiga()
        self._migrar_conversas()

    # ------------------------------------------------------------ estado
    def _estado(self, chave: str, padrao: str = "") -> str:
        r = self.con.execute("SELECT valor FROM estado WHERE chave = ?", (chave,)).fetchone()
        return r[0] if r else padrao

    def _gravar_estado(self, chave: str, valor: str) -> None:
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO estado VALUES (?,?)", (chave, valor))

    # ------------------------------------------------------------ fatos
    @staticmethod
    def _fato(r: sqlite3.Row) -> Fato:
        return Fato(r["id"], r["texto"], r["categoria"], r["importancia"], r["origem"], r["criado_em"], r["atualizado_em"],
                    r["usado_em"], r["usos"], bool(r["ativo"]), r["substituido_por"])

    def fatos(self, ativos: bool = True, categoria: str | None = None) -> list[Fato]:
        sql = "SELECT * FROM fatos WHERE ativo = ?" + (" AND categoria = ?" if categoria else "") + \
              " ORDER BY importancia DESC, atualizado_em DESC"
        return [self._fato(r) for r in self.con.execute(sql, (1 if ativos else 0, *([categoria] if categoria else [])))]

    def obter(self, ident: int) -> Fato | None:
        r = self.con.execute("SELECT * FROM fatos WHERE id = ?", (ident,)).fetchone()
        return self._fato(r) if r else None

    def _vetor_de(self, texto: str) -> tuple[bytes | None, str]:
        v = self.vet.vetores([texto])
        return (_vet_bytes(v[0]), self.vet.nome()) if v else (None, "")

    def _parecido(self, texto: str, categoria: str | None = None) -> tuple[Fato | None, float]:
        """O fato ativo mais parecido (mesmo texto normalizado = 1.0; senão similaridade de significado)."""
        alvo = _chave(texto)
        candidatos = self.fatos()
        for f in candidatos:
            if _chave(f.texto) == alvo:
                return f, 1.0
        v = self.vet.vetores([texto])
        if not v:
            return None, 0.0
        melhor, nota = None, 0.0
        for r in self.con.execute("SELECT id, vetor, modelo_vetor FROM fatos WHERE ativo = 1 AND vetor IS NOT NULL"):
            if r["modelo_vetor"] != self.vet.nome():
                continue
            s = _cos(v[0], _vet_lista(r["vetor"]))
            if s > nota:
                melhor, nota = r["id"], s
        return (self.obter(melhor), nota) if melhor else (None, 0.0)

    def adicionar(self, texto: str, categoria: str = "geral", importancia: int = 3, origem: str = "extraido") -> tuple[str, Fato | None]:
        """Guarda um fato (ou atualiza o igual). Devolve (mensagem, fato)."""
        texto = re.sub(r"\s+", " ", (texto or "")).strip().lstrip("-• ").strip()
        if len(texto) < 4:
            return "Nada para lembrar.", None
        if tem_dado_pessoal(texto):
            return "Não guardei: tem dado pessoal (CPF, telefone, e-mail ou conta). Use o código CLI-XXX.", None
        categoria = categoria if categoria in CATEGORIAS else "geral"
        importancia = max(1, min(5, int(importancia or 3)))
        with self._trava:
            igual, nota = self._parecido(texto)
            if igual and nota >= SIMILAR_REPETIDO:
                with self.con:
                    self.con.execute("UPDATE fatos SET texto = ?, importancia = MAX(importancia, ?), atualizado_em = ?, "
                                     "origem = CASE WHEN ? = 'dito' THEN 'dito' ELSE origem END WHERE id = ?",
                                     (texto if len(texto) >= len(igual.texto) else igual.texto, importancia, _iso(), origem, igual.id))
                self._refazer_vetor(igual.id)
                return f"Já estava na memória (atualizei): {texto}", self.obter(igual.id)
            vetor, modelo = self._vetor_de(texto)
            with self.con:
                cur = self.con.execute("INSERT INTO fatos(texto, categoria, importancia, origem, criado_em, atualizado_em, vetor, "
                                       "modelo_vetor) VALUES (?,?,?,?,?,?,?,?)",
                                       (texto, categoria, importancia, origem, _iso(), _iso(), vetor, modelo))
        self._exportar_md()
        self.registrar("sistema", None, "memoria_fato", f"guardado #{cur.lastrowid} ({categoria}, {importancia}★, {origem}): {texto}")
        return f"Guardado na memória: {texto}", self.obter(cur.lastrowid)

    def _refazer_vetor(self, ident: int) -> None:
        f = self.obter(ident)
        if f:
            vetor, modelo = self._vetor_de(f.texto)
            with self.con:
                self.con.execute("UPDATE fatos SET vetor = ?, modelo_vetor = ? WHERE id = ?", (vetor, modelo, ident))

    def atualizar(self, ident: int, texto: str, categoria: str | None = None, importancia: int | None = None) -> str:
        """Fato mudou (ex.: 'agora prefiro X'): o antigo é arquivado como substituído e o novo entra no lugar."""
        antigo = self.obter(ident)
        if not antigo or not antigo.ativo:
            return f"Fato #{ident} não existe."
        if tem_dado_pessoal(texto):
            return "Não guardei: tem dado pessoal."
        if _chave(texto) == _chave(antigo.texto):
            return "Sem mudança."
        vetor, modelo = self._vetor_de(texto)
        with self._trava, self.con:
            cur = self.con.execute("INSERT INTO fatos(texto, categoria, importancia, origem, criado_em, atualizado_em, vetor, modelo_vetor) "
                                   "VALUES (?,?,?,?,?,?,?,?)",
                                   (texto.strip(), categoria if categoria in CATEGORIAS else antigo.categoria,
                                    max(1, min(5, int(importancia or antigo.importancia))), antigo.origem, antigo.criado_em, _iso(),
                                    vetor, modelo))
            self.con.execute("UPDATE fatos SET ativo = 0, substituido_por = ?, atualizado_em = ? WHERE id = ?",
                             (cur.lastrowid, _iso(), ident))
        self._exportar_md()
        self.registrar("sistema", None, "memoria_fato", f"atualizado #{ident} → #{cur.lastrowid}: {antigo.texto} → {texto.strip()}")
        return f"Atualizado: {antigo.texto} → {texto.strip()}"

    def esquecer(self, alvo: str) -> str:
        """Por número (#12) ou por trecho. O fato é arquivado (some das respostas; continua no backup)."""
        alvo = (alvo or "").strip()
        if m := re.fullmatch(r"#?(\d+)", alvo):
            ids = [int(m[1])] if self.obter(int(m[1])) else []
        else:
            chave = _chave(alvo)
            ids = [f.id for f in self.fatos() if chave and chave in _chave(f.texto)]
        if not ids:
            return f"Nada na memória com “{alvo}”."
        with self.con:
            self.con.executemany("UPDATE fatos SET ativo = 0, atualizado_em = ? WHERE id = ?", [(_iso(), i) for i in ids])
        self._exportar_md()
        self.registrar("sistema", None, "memoria_fato", f"esquecido(s) {', '.join(f'#{i}' for i in ids)}")
        return f"Esquecido: {len(ids)} item(ns)."

    def apagar_por_cliente(self, codigo: str) -> int:
        """LGPD (/esquecer CLI-XXX): apaga DE VERDADE fatos e episódios que citam o código inteiro."""
        padrao = re.compile(rf"\b{re.escape(codigo)}\b", re.I)
        ids = [r["id"] for r in self.con.execute("SELECT id, texto FROM fatos") if padrao.search(r["texto"])]
        eps = [r["id"] for r in self.con.execute("SELECT id, titulo, resumo, pendencias FROM episodios")
               if padrao.search(f"{r['titulo']} {r['resumo']} {r['pendencias']}")]
        evs = [r["id"] for r in self.con.execute("SELECT id, texto FROM eventos") if padrao.search(r["texto"])]
        regs = [r["id"] for r in self.con.execute("SELECT id, conteudo, meta FROM registros WHERE conteudo LIKE ? OR meta LIKE ?",
                                                  (f"%{codigo}%", f"%{codigo}%"))
                if padrao.search(f"{r['conteudo']} {r['meta']}")]
        self.con.execute("PRAGMA secure_delete=ON")  # LGPD: apagado de verdade (sobrescrito no arquivo)
        with self.con:
            self.con.executemany("DELETE FROM registros WHERE id = ?", [(i,) for i in regs])
            self.con.execute("INSERT INTO registros_busca(registros_busca) VALUES ('rebuild')")
            self.con.executemany("DELETE FROM fatos WHERE id = ?", [(i,) for i in ids])
            self.con.execute("INSERT INTO fatos_busca(fatos_busca) VALUES ('rebuild')")
            self.con.executemany("DELETE FROM episodios WHERE id = ?", [(i,) for i in eps])
            self.con.executemany("DELETE FROM eventos WHERE id = ?", [(i,) for i in evs])
        self._reindexar_episodios()
        self._exportar_md()
        return len(ids) + len(eps) + len(evs) + len(regs)

    # ------------------------------------------------------------ operações vindas da extração automática
    def aplicar(self, operacoes: Iterable[dict[str, Any]]) -> list[str]:
        feitos = []
        for op in operacoes or []:
            if not isinstance(op, dict):
                continue
            tipo = str(op.get("op", "")).lower()
            texto = str(op.get("texto") or "").strip()
            try:
                ident = int(str(op.get("id") or "0").lstrip("#") or 0)
            except ValueError:
                ident = 0
            if tipo in {"adicionar", "add"} and texto:
                msg, f = self.adicionar(texto, str(op.get("categoria") or "geral"), int(op.get("importancia") or 3), "extraido")
                if f:
                    feitos.append(msg)
            elif tipo in {"atualizar", "update"} and ident and texto:
                feitos.append(self.atualizar(ident, texto, op.get("categoria"), op.get("importancia")))
            elif tipo in {"apagar", "delete", "esquecer"} and ident:
                f = self.obter(ident)
                if f and f.origem != "dito":  # o que ele mandou guardar só sai quando ele pedir
                    feitos.append(self.esquecer(f"#{ident}"))
        return feitos

    # ------------------------------------------------------------ eventos (comandos diretos do bot)
    def registrar_evento(self, tipo: str, texto: str) -> None:
        texto = re.sub(r"\s+", " ", texto or "").strip()[:300]
        if not texto or tem_dado_pessoal(texto):
            return
        with self.con:
            self.con.execute("INSERT INTO eventos(quando, tipo, texto) VALUES (?,?,?)", (_iso(), tipo, texto))
            self.con.execute("DELETE FROM eventos WHERE quando < ?", (_iso(_agora() - timedelta(days=120)),))

    def eventos_recentes(self, horas: int = 48, limite: int = 8) -> list[str]:
        linhas = self.con.execute("SELECT quando, texto FROM eventos WHERE quando >= ? ORDER BY id DESC LIMIT ?",
                                  (_iso(_agora() - timedelta(hours=horas)), limite)).fetchall()
        return [f"{datetime.fromisoformat(q).astimezone(_brt()):%d/%m %H:%M} {t}" for q, t in reversed(linhas)]

    # ------------------------------------------------------------ episódios
    def episodios(self, limite: int = 20) -> list[Episodio]:
        return [self._episodio(r) for r in self.con.execute("SELECT * FROM episodios ORDER BY id DESC LIMIT ?", (limite,))]

    @staticmethod
    def _episodio(r: sqlite3.Row) -> Episodio:
        return Episodio(r["id"], r["chat"], r["inicio"], r["fim"], r["titulo"], r["resumo"], json.loads(r["pendencias"] or "[]"))

    def ultimo_id_episodio(self, chat: int) -> int:
        r = self.con.execute("SELECT MAX(msg_ate) FROM episodios WHERE chat = ?", (chat,)).fetchone()
        return int(r[0] or 0) if r else 0

    def guardar_episodio(self, chat: int, inicio: str, fim: str, titulo: str, resumo: str, pendencias: list[str],
                         msg_de: int, msg_ate: int) -> Episodio:
        titulo = re.sub(r"\s+", " ", titulo or "Conversa").strip()[:120]
        resumo = re.sub(r"\s+", " ", resumo or "").strip()[:1500]
        pendencias = [p.strip()[:200] for p in pendencias or [] if p and str(p).strip()][:8]
        vetor, modelo = self._vetor_de(f"{titulo}. {resumo}")
        with self.con:
            cur = self.con.execute("INSERT INTO episodios(chat, inicio, fim, titulo, resumo, pendencias, msg_de, msg_ate, vetor, "
                                   "modelo_vetor) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (chat, inicio, fim, titulo, resumo, json.dumps(pendencias, ensure_ascii=False), msg_de, msg_ate,
                                    vetor, modelo))
            self.con.execute("INSERT INTO episodios_busca(rowid, texto) VALUES (?,?)",
                             (cur.lastrowid, f"{titulo} {resumo} {' '.join(pendencias)}"))
        r = self.con.execute("SELECT * FROM episodios WHERE id = ?", (cur.lastrowid,)).fetchone()
        self.registrar("sistema", chat, "memoria_episodio", f"conversa resumida #{cur.lastrowid}: {titulo} — {resumo}")
        return self._episodio(r)

    def _reindexar_episodios(self) -> None:
        with self.con:
            self.con.execute("DELETE FROM episodios_busca")
            for r in self.con.execute("SELECT id, titulo, resumo, pendencias FROM episodios").fetchall():
                self.con.execute("INSERT INTO episodios_busca(rowid, texto) VALUES (?,?)",
                                 (r["id"], f"{r['titulo']} {r['resumo']} {' '.join(json.loads(r['pendencias'] or '[]'))}"))

    # ------------------------------------------------------------ recuperação
    @staticmethod
    def _consulta_fts(texto: str) -> str:
        palavras = [p for p in re.findall(r"\w+", texto or "") if len(p) > 2][:12]
        return " OR ".join(f'"{p}"*' for p in palavras)

    def _bm25(self, tabela: str, consulta: str, limite: int = 30) -> dict[int, float]:
        q = self._consulta_fts(consulta)
        if not q:
            return {}
        try:
            linhas = self.con.execute(f"SELECT rowid, bm25({tabela}) FROM {tabela} WHERE {tabela} MATCH ? ORDER BY 2 LIMIT ?",
                                      (q, limite)).fetchall()
        except sqlite3.OperationalError:
            return {}
        if not linhas:
            return {}
        piores = max(-s for _, s in linhas) or 1.0
        return {r: (-s) / piores for r, s in linhas}  # 0..1 (1 = melhor)

    def relevantes(self, consulta: str, k: int = 8, excluir: set[int] | None = None) -> list[Fato]:
        excluir = excluir or set()
        ativos = {f.id: f for f in self.fatos() if f.id not in excluir}
        if not ativos:
            return []
        palavras = self._bm25("fatos_busca", consulta)
        v = self.vet.vetores([consulta]) if consulta.strip() else None
        vetores = {}
        if v:
            for r in self.con.execute("SELECT id, vetor, modelo_vetor FROM fatos WHERE ativo = 1 AND vetor IS NOT NULL"):
                if r["modelo_vetor"] == self.vet.nome():
                    vetores[r["id"]] = _cos(v[0], _vet_lista(r["vetor"]))
        agora = _agora()
        notas = []
        for i, f in ativos.items():
            sem, pal = vetores.get(i, 0.0), palavras.get(i, 0.0)
            if sem < 0.35 and pal == 0:
                continue  # nada a ver com o pedido
            idade = (agora - datetime.fromisoformat(f.atualizado_em)).days if f.atualizado_em else 365
            nota = 0.55 * sem + 0.25 * pal + 0.12 * (f.importancia / 5) + 0.08 * math.exp(-idade / 180)
            notas.append((nota, f))
        notas.sort(key=lambda x: -x[0])
        return [f for _, f in notas[:k]]

    def episodios_relevantes(self, consulta: str, k: int = 3) -> list[Episodio]:
        palavras = self._bm25("episodios_busca", consulta)
        v = self.vet.vetores([consulta]) if consulta.strip() else None
        notas = []
        for r in self.con.execute("SELECT * FROM episodios ORDER BY id DESC LIMIT 400"):
            sem = _cos(v[0], _vet_lista(r["vetor"])) if v and r["modelo_vetor"] == self.vet.nome() else 0.0
            pal = palavras.get(r["id"], 0.0)
            if sem < 0.4 and pal == 0:
                continue
            notas.append((0.65 * sem + 0.35 * pal, self._episodio(r)))
        notas.sort(key=lambda x: -x[0])
        return [e for _, e in notas[:k]]

    def nucleo(self, limite: int = 15) -> list[Fato]:
        """Sempre presentes no contexto: os mais importantes (perfil, preferências fortes, objetivos)."""
        return [f for f in self.fatos() if f.importancia >= 4][:limite]

    def marcar_uso(self, fatos: Iterable[Fato]) -> None:
        ids = [(_iso(), f.id) for f in fatos]
        if ids:
            with self.con:
                self.con.executemany("UPDATE fatos SET usos = usos + 1, usado_em = ? WHERE id = ?", ids)

    def contexto(self, consulta: str, limite_caracteres: int = 3500) -> str:
        """Bloco de memória para o prompt: núcleo + relevantes + episódios + atividades recentes."""
        self.importar_edicoes_md()
        nucleo = self.nucleo()
        rel = self.relevantes(consulta, excluir={f.id for f in nucleo})
        eps = self.episodios_relevantes(consulta)
        eventos = self.eventos_recentes()
        partes = []
        if nucleo:
            partes.append("### O essencial sobre o Rickson\n" + "\n".join(f"- {f.texto}" for f in nucleo))
        if rel:
            partes.append("### Lembranças ligadas a este pedido\n" + "\n".join(f"- {f.texto}" for f in rel))
        if eps:
            partes.append("### Conversas anteriores relacionadas\n" + "\n".join(f"- {e.linha()}" for e in eps))
        if eventos:
            partes.append("### O que ele fez pelos comandos (últimas 48 h)\n" + "\n".join(f"- {t}" for t in eventos))
        self.marcar_uso([*nucleo, *rel])
        texto = "\n\n".join(partes)
        return texto[:limite_caracteres]

    def buscar(self, termo: str, limite: int = 8) -> str:
        """Ferramenta `buscar_conversas`: fatos + episódios ligados ao termo (as mensagens cruas vêm de memoria.py)."""
        fatos = self.relevantes(termo, k=limite)
        eps = self.episodios_relevantes(termo, k=limite)
        linhas = [f"- (fato #{f.id}) {f.texto}" for f in fatos] + [f"- (conversa) {e.linha()}" for e in eps]
        return "\n".join(linhas)

    # ------------------------------------------------------------ MEMORIA.md (leitura e edição pelo Rickson)
    def _exportar_md(self) -> None:
        try:
            linhas = ["# Memória do Quíron", "",
                      "Gerado automaticamente a partir de `dados/memoria.db`. Você PODE editar: mude o texto de um item, apague uma",
                      "linha para o Quíron esquecer, ou acrescente `- novo fato` numa seção (o número entre colchetes é o código do fato).", ""]
            for cat, titulo in CATEGORIAS.items():
                itens = self.fatos(categoria=cat)
                if itens:
                    linhas.append(f"## {titulo}")
                    linhas += [f"- {f.linha()}" for f in itens]
                    linhas.append("")
            texto = "\n".join(linhas)
            self.arquivo_md.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo_md.write_text(texto, encoding="utf-8")
            self._gravar_estado("md_hash", hashlib.sha256(texto.encode()).hexdigest())
        except OSError as e:
            logging.warning("não consegui escrever MEMORIA.md: %s", e)

    def importar_edicoes_md(self) -> list[str]:
        """Se o Rickson editou o MEMORIA.md à mão, aplica: texto mudado, linha apagada (esquece) e linha nova (guarda)."""
        if not self.arquivo_md.exists():
            return []
        texto = self.arquivo_md.read_text(encoding="utf-8")
        if hashlib.sha256(texto.encode()).hexdigest() == self._estado("md_hash"):
            return []
        mudancas, vistos = [], set()
        categoria = "geral"
        titulo_para_cat = {t: c for c, t in CATEGORIAS.items()}
        for linha in texto.splitlines():
            if linha.startswith("## "):
                categoria = titulo_para_cat.get(linha[3:].strip(), "geral")
                continue
            if not linha.startswith("- "):
                continue
            m = re.match(r"-\s*\[#(\d+)\]\s*(.+)", linha)
            if m:
                ident, novo = int(m[1]), m[2].strip()
                vistos.add(ident)
                f = self.obter(ident)
                if f and f.ativo and _chave(novo) != _chave(f.texto):
                    mudancas.append(self.atualizar(ident, novo, categoria))
                    vistos.add(self.con.execute("SELECT substituido_por FROM fatos WHERE id = ?", (ident,)).fetchone()[0])
            else:
                novo = re.sub(r"\s*_\(desde [^)]*\)_\s*$", "", linha[2:]).strip()
                msg, f = self.adicionar(novo, categoria, 4, "editado")
                if f:
                    vistos.add(f.id)
                    mudancas.append(msg)
        apagados = [f.id for f in self.fatos() if f.id not in vistos]
        if apagados:
            with self.con:
                self.con.executemany("UPDATE fatos SET ativo = 0, atualizado_em = ? WHERE id = ?", [(_iso(), i) for i in apagados])
            mudancas.append(f"Esquecidos pela edição do MEMORIA.md: {len(apagados)}")
        self._exportar_md()
        return mudancas

    def _migrar_memoria_md_antiga(self) -> None:
        """Primeira vez: os fatos do MEMORIA.md antigo (formato '- fato _(desde dd/mm/aaaa)_') entram no banco."""
        if self._estado("migrado") or not self.arquivo_md.exists():
            self._gravar_estado("migrado", "1")
            return
        for linha in self.arquivo_md.read_text(encoding="utf-8").splitlines():
            if linha.startswith("- ") and not re.match(r"-\s*\[#\d+\]", linha):
                fato = re.sub(r"\s*_\(desde [^)]*\)_\s*$", "", linha[2:]).strip()
                if fato and not fato.startswith("("):
                    self.adicionar(fato, "geral", 4, "importado")
        self._gravar_estado("migrado", "1")
        self._exportar_md()

    # ------------------------------------------------------------ consolidação ("sono")
    def consolidar(self, hoje: datetime | None = None) -> dict[str, int]:
        """Junta fatos repetidos e arquiva os pouco importantes que ninguém usa há 120 dias. Roda de madrugada."""
        hoje = hoje or _agora()
        juntados = arquivados = 0
        with self._trava:
            fatos = self.fatos()
            vetores = {r["id"]: _vet_lista(r["vetor"]) for r in
                       self.con.execute("SELECT id, vetor FROM fatos WHERE ativo = 1 AND vetor IS NOT NULL AND modelo_vetor = ?",
                                        (self.vet.nome(),))}
            fora: set[int] = set()
            for i, a in enumerate(fatos):
                if a.id in fora:
                    continue
                for b in fatos[i + 1:]:
                    if b.id in fora or a.categoria != b.categoria:
                        continue
                    igual = _chave(a.texto) == _chave(b.texto) or _cos(vetores.get(a.id), vetores.get(b.id)) >= SIMILAR_REPETIDO
                    if igual:  # fica o mais recente/importante (a vem antes na ordenação)
                        with self.con:
                            self.con.execute("UPDATE fatos SET ativo = 0, substituido_por = ? WHERE id = ?", (a.id, b.id))
                            # o que o Rickson disse continua protegido no fato que fica (apagar nunca remove "dito")
                            self.con.execute("UPDATE fatos SET importancia = MAX(importancia, ?), usos = usos + ?, "
                                             "origem = CASE WHEN ? = 'dito' THEN 'dito' ELSE origem END WHERE id = ?",
                                             (b.importancia, b.usos, b.origem, a.id))
                        fora.add(b.id)
                        juntados += 1
            limite = _iso(hoje - timedelta(days=120))
            with self.con:
                cur = self.con.execute("UPDATE fatos SET ativo = 0 WHERE ativo = 1 AND importancia <= 2 AND origem != 'dito' "
                                       "AND COALESCE(NULLIF(usado_em, ''), atualizado_em) < ?", (limite,))
                arquivados = cur.rowcount
        self.revetorizar()
        self._exportar_md()
        self._gravar_estado("consolidado_em", _iso(hoje))
        return {"juntados": juntados, "arquivados": arquivados}

    def revetorizar(self) -> int:
        """Fatos/episódios com vetor de outro modelo (ex.: o modelo de significado foi baixado depois) ganham vetor novo."""
        nome = self.vet.nome()
        if not nome:
            return 0
        n = 0
        for tabela, campo in (("fatos", "texto"), ("episodios", "titulo || '. ' || resumo")):
            linhas = self.con.execute(f"SELECT id, {campo} FROM {tabela} WHERE COALESCE(modelo_vetor, '') != ?", (nome,)).fetchall()
            for i in range(0, len(linhas), 32):
                bloco = linhas[i:i + 32]
                vs = self.vet.vetores([r[1] for r in bloco])
                if not vs:
                    return n
                with self.con:
                    self.con.executemany(f"UPDATE {tabela} SET vetor = ?, modelo_vetor = ? WHERE id = ?",
                                         [(_vet_bytes(v), nome, r[0]) for v, r in zip(vs, bloco)])
                n += len(bloco)
        return n

    # ------------------------------------------------------------ registro completo (tudo o que acontece, só acrescenta)
    def registrar(self, canal: str, chat: int | None, tipo: str, conteudo: str, meta: dict[str, Any] | None = None) -> None:
        """Grava qualquer acontecimento (mensagem, resposta, comando, ferramenta, aviso enviado, mudança na memória).
        Nunca altera nem apaga o que já foi gravado (só a LGPD apaga). Nunca derruba quem chamou."""
        try:
            with self._trava, self.con:
                self.con.execute("INSERT INTO registros(quando, canal, chat, tipo, conteudo, meta) VALUES (?,?,?,?,?,?)",
                                 (_iso(), canal or "", chat, tipo, (conteudo or "")[:20000],
                                  json.dumps(meta, ensure_ascii=False, default=str)[:4000] if meta else ""))
        except sqlite3.Error:
            logging.exception("não consegui gravar no registro da memória")

    def registros_do_dia(self, dia: datetime | None = None, tipos: set[str] | None = None) -> list[sqlite3.Row]:
        dia = (dia or datetime.now(_brt())).astimezone(_brt())
        ini = dia.replace(hour=0, minute=0, second=0, microsecond=0)
        linhas = self.con.execute("SELECT * FROM registros WHERE quando >= ? AND quando < ? ORDER BY id",
                                  (_iso(ini.astimezone(timezone.utc)), _iso((ini + timedelta(days=1)).astimezone(timezone.utc)))).fetchall()
        return [r for r in linhas if not tipos or r["tipo"] in tipos]

    def linha_do_tempo(self, dia: datetime | None = None, limite: int = 60) -> str:
        """O que aconteceu num dia, em ordem: o que ele disse/pediu, o que o Quíron respondeu e fez sozinho."""
        nomes = {"entrada": "🗣️", "resposta": "🤖", "comando": "⌨️", "resposta_comando": "📋", "audio": "🎙️", "arquivo": "📎",
                 "proativo": "🔔", "ferramenta": "🔧", "memoria_fato": "🧠", "memoria_episodio": "🗂️"}
        linhas = [r for r in self.registros_do_dia(dia) if r["tipo"] != "ferramenta_resultado"]
        if not linhas:
            return "Nada registrado nesse dia."
        saida = []
        for r in linhas[-limite:]:
            hora = datetime.fromisoformat(r["quando"]).astimezone(_brt()).strftime("%H:%M")
            texto = re.sub(r"\s+", " ", r["conteudo"] or "")[:160]
            saida.append(f"{hora} {nomes.get(r['tipo'], '•')} {texto}")
        extra = f"(mostrando os últimos {limite} de {len(linhas)})\n" if len(linhas) > limite else ""
        return extra + "\n".join(saida)

    def buscar_registros(self, termo: str, limite: int = 8) -> list[sqlite3.Row]:
        q = self._consulta_fts(termo)
        if not q:
            return []
        try:
            return self.con.execute("SELECT r.* FROM registros_busca b JOIN registros r ON r.id = b.rowid WHERE registros_busca "
                                    "MATCH ? AND r.tipo != 'ferramenta_resultado' ORDER BY bm25(registros_busca) LIMIT ?",
                                    (q, limite)).fetchall()
        except sqlite3.OperationalError:
            return []

    def _migrar_conversas(self) -> None:
        """Primeira vez: as conversas antigas (conversas.db) entram no registro completo, para ele começar inteiro."""
        if self._estado("conversas_migradas"):
            return
        antigo = self.caminho.with_name("conversas.db")
        n = 0
        if antigo.exists():
            try:
                with sqlite3.connect(antigo) as con:
                    linhas = con.execute("SELECT chat, quando, papel, texto FROM mensagens ORDER BY id").fetchall()
                with self.con:
                    self.con.executemany("INSERT INTO registros(quando, canal, chat, tipo, conteudo, meta) VALUES (?,?,?,?,?,?)",
                                         [(q, "terminal" if c == -12 else "telegram", c, "entrada" if p == "user" else "resposta", t,
                                           '{"migrado": true}') for c, q, p, t in linhas])
                n = len(linhas)
            except sqlite3.Error:
                logging.exception("não consegui trazer as conversas antigas para o registro")
                return
        self._gravar_estado("conversas_migradas", str(n))

    # ------------------------------------------------------------ cópias de segurança, integridade e exportação
    def pasta_copias(self) -> Path:
        return self.caminho.parent / "backups" / "memoria"

    def fazer_copia(self, manter: int = 30, quando: datetime | None = None, nome: str | None = None) -> Path:
        """Cópia consistente (API de backup do SQLite, funciona com o Quíron ligado) da memória e das conversas.
        Uma pasta por dia (AAAA-MM-DD); as 30 mais recentes ficam. `nome` = pasta avulsa (não entra na rotação)."""
        quando = (quando or datetime.now(_brt())).astimezone(_brt())
        pasta = self.pasta_copias() / (nome or f"{quando:%Y-%m-%d}")
        pasta.mkdir(parents=True, exist_ok=True)
        for origem in (self.caminho, self.caminho.with_name("conversas.db")):
            if not origem.exists():
                continue
            with sqlite3.connect(origem, timeout=30) as fonte, sqlite3.connect(pasta / origem.name) as destino:
                fonte.backup(destino)
        copias = sorted(p for p in self.pasta_copias().iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
        for velha in copias[:-manter]:
            import shutil

            shutil.rmtree(velha, ignore_errors=True)
        self._gravar_estado("ultima_copia", _iso())
        return pasta

    def verificar_integridade(self) -> str:
        """'ok' ou a descrição do problema (PRAGMA integrity_check)."""
        try:
            r = self.con.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as e:
            return f"erro: {e}"
        return "ok" if r == "ok" else r

    def restaurar_copia(self, dia: str) -> str:
        """Volta a memória para a cópia de um dia (a atual é guardada antes, nada se perde)."""
        pasta = self.pasta_copias() / dia
        if not (pasta / self.caminho.name).exists():
            disponiveis = ", ".join(p.name for p in sorted(self.pasta_copias().iterdir())) if self.pasta_copias().exists() else "nenhuma"
            raise FileNotFoundError(f"Não há cópia de {dia}. Disponíveis: {disponiveis}")
        self.fazer_copia(nome=f"antes-de-restaurar-{datetime.now(_brt()):%Y%m%d-%H%M%S}")  # guarda o estado atual antes
        for nome in (self.caminho.name, "conversas.db"):
            if (pasta / nome).exists():
                with sqlite3.connect(pasta / nome) as fonte, sqlite3.connect(self.caminho.with_name(nome), timeout=30) as destino:
                    fonte.backup(destino)
        # o MEMORIA.md ainda descreve a memória de antes: sem regerar, a próxima leitura o trataria como edição à mão
        # e desativaria os fatos restaurados
        from quiron.servicos import lgpd

        for cod in lgpd.esquecidos(copia_de=dia):  # cliente esquecido (LGPD) depois da cópia continua esquecido
            self.apagar_por_cliente(cod)
            lgpd._apagar_conversas(self.caminho.with_name("conversas.db"), cod)
        self._exportar_md()  # a conexão aberta já enxerga o banco restaurado (o backup do SQLite grava pelo próprio SQLite)
        return f"Memória restaurada para a cópia de {dia}. Feche e abra o Quíron para recarregar."

    def exportar(self, destino: Path | None = None) -> Path:
        """Tudo em um JSON legível (fatos, conversas resumidas, registro completo) — os dados são do Rickson."""
        destino = destino or self.caminho.parent / "exportacoes" / f"memoria-{datetime.now(_brt()):%Y%m%d-%H%M}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        dados = {
            "exportado_em": _iso(),
            "fatos": [dict(r) for r in self.con.execute("SELECT id, texto, categoria, importancia, origem, criado_em, atualizado_em, "
                                                         "usos, ativo, substituido_por FROM fatos ORDER BY id")],
            "conversas_resumidas": [dict(r) for r in self.con.execute("SELECT id, chat, inicio, fim, titulo, resumo, pendencias "
                                                                       "FROM episodios ORDER BY id")],
            "registro": [dict(r) for r in self.con.execute("SELECT id, quando, canal, chat, tipo, conteudo, meta FROM registros ORDER BY id")],
        }
        destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        return destino

    # ------------------------------------------------------------ números para a tela
    def resumo(self) -> dict[str, Any]:
        por = dict(self.con.execute("SELECT categoria, COUNT(*) FROM fatos WHERE ativo = 1 GROUP BY categoria").fetchall())
        return {"fatos": sum(por.values()), "por_categoria": por,
                "episodios": self.con.execute("SELECT COUNT(*) FROM episodios").fetchone()[0],
                "arquivados": self.con.execute("SELECT COUNT(*) FROM fatos WHERE ativo = 0").fetchone()[0],
                "registros": self.con.execute("SELECT COUNT(*) FROM registros").fetchone()[0],
                "tamanho_mb": round(sum(p.stat().st_size for p in (self.caminho, self.caminho.with_name(self.caminho.name + "-wal"))
                                        if p.exists()) / 1e6, 2),
                "ultima_copia": self._estado("ultima_copia"), "consolidado_em": self._estado("consolidado_em")}


# ---------------------------------------------------------------- o "escriba": fecha episódios e extrai fatos com o modelo
PEDIDO_ESCRIBA = """Você cuida da memória de longo prazo do Quíron, assistente do Rickson (assessor de investimentos).
Leia a conversa abaixo e responda SÓ um JSON:
{{"titulo": "até 8 palavras", "resumo": "2 a 4 frases: o que foi tratado e decidido, números citados com a fonte",
  "pendencias": ["o que ficou para fazer, se houver"],
  "fatos": [{{"op": "adicionar" | "atualizar" | "apagar", "id": número do fato existente (só para atualizar/apagar),
             "texto": "fato curto e autossuficiente, em 3ª pessoa (ex.: 'Rickson prefere respostas curtas')",
             "categoria": um de {categorias}, "importancia": 1 a 5}}]}}

Regras para "fatos":
- Só o que vale lembrar por semanas ou meses: perfil, preferências, objetivos, rotina, estudo, como ele trabalha,
  decisões duradouras, visões de mercado DELE, contexto de clientes pelo código CLI-XXX.
- NÃO guarde: dados de mercado do dia, cotações, coisas passageiras, o que o Quíron disse, nem dado pessoal de cliente
  (nome, CPF, telefone, e-mail, endereço) — clientes só como CLI-XXX.
- Se um fato existente mudou, use "atualizar" com o id dele. Se ficou falso, "apagar". Não repita o que já existe.
- Importância: 5 = essencial e permanente (quem ele é, objetivo de carreira); 4 = preferência forte; 3 = útil; 1–2 = detalhe.
- Sem nada durável, "fatos": [].

Fatos que já existem:
{existentes}

Conversa ({quando}):
{conversa}"""


def config_escriba(config):
    """Começa pelo modelo de reserva (Groq) para poupar a cota diária do Gemini; o Gemini fica de plano B."""
    if not config or not getattr(config, "llm_reserva", "") or config.ordem:
        return config
    return replace(config, ordem=(config.llm_reserva, *[m for m in config.modelos if m != config.llm_reserva]))


def _json(texto: str) -> Any:
    b = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip())
    ini, fim = b.find("{"), b.rfind("}")
    return json.loads(b[ini:fim + 1]) if ini >= 0 and fim > ini else {}


@dataclass
class Escriba:
    longa: MemoriaLonga
    perguntar: Callable[..., Any] | None = None  # cerebro.perguntar (trocado nos testes)
    config: Any = None

    def _perguntar(self, pedido: str) -> str:
        from quiron.nucleo import cerebro

        f = self.perguntar or cerebro.perguntar
        return f(pedido, config=config_escriba(self.config), temperatura=0.2, max_tokens=1200,
                 response_format={"type": "json_object"}).texto

    def fechar(self, chat: int, mensagens: list[tuple[int, str, str, str]], forcar: bool = False) -> Episodio | None:
        """`mensagens` = (id, quando, papel, texto) desde o último episódio. Cria o episódio e aplica os fatos."""
        if not mensagens or (len(mensagens) < 2 and not forcar):
            return None
        conversa = "\n".join(f"{'Rickson' if p == 'user' else 'Quíron'}: {t[:1500]}" for _, _, p, t in mensagens)[-14000:]
        eventos = self.longa.eventos_recentes(horas=6)
        if eventos:
            conversa += "\n\n(Comandos usados no período: " + "; ".join(eventos) + ")"
        existentes = "\n".join(f.linha() for f in self.longa.fatos()[:120]) or "(nenhum)"
        inicio, fim = mensagens[0][1], mensagens[-1][1]
        quando = datetime.fromisoformat(inicio).astimezone(_brt()).strftime("%d/%m/%Y %H:%M")
        try:
            d = _json(self._perguntar(PEDIDO_ESCRIBA.format(categorias=list(CATEGORIAS), existentes=existentes,
                                                            conversa=conversa, quando=quando)))
            titulo, resumo, pend = str(d.get("titulo") or "Conversa"), str(d.get("resumo") or ""), list(d.get("pendencias") or [])
            ops = d.get("fatos") or []
        except Exception as e:  # noqa: BLE001 — sem IA agora: guarda um episódio simples e tenta os fatos depois
            logging.info("escriba sem IA (%s): episódio simples", type(e).__name__)
            primeiras = [t for _, _, p, t in mensagens if p == "user"][:3]
            titulo = (primeiras[0][:60] if primeiras else "Conversa")
            resumo = "Pedidos: " + " | ".join(x[:160] for x in primeiras)
            pend, ops = [], []
        ep = self.longa.guardar_episodio(chat, inicio, fim, titulo, resumo, pend, mensagens[0][0], mensagens[-1][0])
        feitos = self.longa.aplicar(ops)
        if feitos:
            logging.info("memória: %s", "; ".join(feitos))
        return ep

    def extrair_troca(self, pergunta: str, resposta: str) -> list[str]:
        """Pista de fato durável numa mensagem ("eu prefiro…", "meu objetivo…"): extrai só os fatos desta troca."""
        existentes = "\n".join(f.linha() for f in self.longa.fatos()[:120]) or "(nenhum)"
        conversa = f"Rickson: {pergunta[:2000]}\nQuíron: {resposta[:1500]}"
        try:
            d = _json(self._perguntar(PEDIDO_ESCRIBA.format(categorias=list(CATEGORIAS), existentes=existentes, conversa=conversa,
                                                            quando=datetime.now(_brt()).strftime("%d/%m/%Y %H:%M"))))
        except Exception as e:  # noqa: BLE001
            logging.info("extração sem IA (%s): fica para o fechamento do episódio", type(e).__name__)
            return []
        return self.longa.aplicar(d.get("fatos") or [])

    def lembrete_explicito(self, texto: str) -> str | None:
        """'lembre que eu prefiro…' → guarda na hora, sem modelo (importância 4)."""
        m = RE_LEMBRE.match(texto or "")
        if not m:
            return None
        msg, _ = self.longa.adicionar(m["fato"].strip().rstrip("."), "geral", 4, "dito")
        return msg

    @staticmethod
    def tem_pista(texto: str) -> bool:
        return bool(RE_PISTAS.search(texto or ""))


# ---------------------------------------------------------------- linha de comando (manutenção sem Telegram)
def main() -> None:
    """`uv run quiron-memoria estado | copia | verificar | exportar | dia [DD/MM/AAAA] | restaurar AAAA-MM-DD`."""
    import argparse

    p = argparse.ArgumentParser(description="Memória persistente do Quíron")
    p.add_argument("acao", choices=["estado", "copia", "verificar", "exportar", "dia", "restaurar"])
    p.add_argument("valor", nargs="?", default="")
    a = p.parse_args()
    m = MemoriaLonga(vetorizador=_Vetorizador())
    if a.acao == "estado":
        for k, v in m.resumo().items():
            print(f"{k}: {v}")
        print(f"integridade: {m.verificar_integridade()}")
    elif a.acao == "copia":
        print(f"Cópia feita em {m.fazer_copia()}")
    elif a.acao == "verificar":
        r = m.verificar_integridade()
        print("Integridade: ok" if r == "ok" else f"PROBLEMA: {r}")
        raise SystemExit(0 if r == "ok" else 1)
    elif a.acao == "exportar":
        print(f"Exportado em {m.exportar()}")
    elif a.acao == "dia":
        dia = datetime.strptime(a.valor, "%d/%m/%Y").replace(tzinfo=_brt()) if a.valor else None
        print(m.linha_do_tempo(dia, limite=500))
    elif a.acao == "restaurar":
        print(m.restaurar_copia(a.valor))
