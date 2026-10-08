"""Índice do Cérebro (`dados/cerebro.db`): busca por palavra (FTS5, sem acento), tags, links [[ ]] e quem cita cada nota.

As notas (arquivos .md) são a fonte da verdade; o índice é refeito por diferença: só relê o arquivo cuja data de
modificação ou tamanho mudou, e tira do índice o que sumiu da pasta. Vários processos (bot, Terminal, MCP) podem
atualizar ao mesmo tempo: WAL + `ON CONFLICT` e, dentro de cada processo, no máximo uma varredura a cada 20 s.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.obsidian import pasta as P

ESQUEMA = """
CREATE TABLE IF NOT EXISTS notas (id INTEGER PRIMARY KEY AUTOINCREMENT, caminho TEXT UNIQUE NOT NULL, titulo TEXT,
  pasta TEXT, tags TEXT DEFAULT '', mtime REAL, tamanho INTEGER, texto TEXT);
CREATE TABLE IF NOT EXISTS links (origem INTEGER NOT NULL, alvo TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS links_alvo ON links(alvo);
CREATE INDEX IF NOT EXISTS links_origem ON links(origem);
CREATE VIRTUAL TABLE IF NOT EXISTS notas_busca USING fts5(titulo, texto, tags, content='notas', content_rowid='id',
  tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS notas_ai AFTER INSERT ON notas BEGIN
  INSERT INTO notas_busca(rowid, titulo, texto, tags) VALUES (new.id, new.titulo, new.texto, new.tags); END;
CREATE TRIGGER IF NOT EXISTS notas_ad AFTER DELETE ON notas BEGIN
  INSERT INTO notas_busca(notas_busca, rowid, titulo, texto, tags) VALUES ('delete', old.id, old.titulo, old.texto, old.tags);
  DELETE FROM links WHERE origem = old.id; END;
CREATE TRIGGER IF NOT EXISTS notas_au AFTER UPDATE ON notas BEGIN
  INSERT INTO notas_busca(notas_busca, rowid, titulo, texto, tags) VALUES ('delete', old.id, old.titulo, old.texto, old.tags);
  INSERT INTO notas_busca(rowid, titulo, texto, tags) VALUES (new.id, new.titulo, new.texto, new.tags); END;
"""

RE_LINK = re.compile(r"\[\[([^\]|#^\n]+)(?:[#^][^\]|\n]*)?(?:\|[^\]\n]*)?\]\]")
RE_TAG = re.compile(r"(?<![\w#&/=\[])#([A-Za-zÀ-ÿ][\wÀ-ÿ/-]*)")
RE_CODIGO = re.compile(r"```.*?```|`[^`\n]*`", re.S)
INTERVALO_S = 20.0
_ultima: dict[str, float] = {}
_trava = threading.Lock()


@dataclass
class Nota:
    id: int
    caminho: str
    titulo: str
    pasta: str
    tags: list[str]
    mtime: float
    trecho: str = ""

    @property
    def alterada(self) -> str:
        return datetime.fromtimestamp(self.mtime).strftime("%d/%m/%Y %H:%M")

    def linha(self) -> str:
        tags = (" · " + " ".join("#" + t for t in self.tags[:4])) if self.tags else ""
        trecho = f"\n   {self.trecho}" if self.trecho else ""
        return f"• [[{self.titulo}]] — {self.pasta or 'raiz'} · {self.alterada}{tags}{trecho}"


def conectar() -> sqlite3.Connection:
    caminho = pasta_dados() / "cerebro.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA secure_delete=ON")  # texto apagado (ex.: /esquecer de cliente) não fica legível no arquivo
    con.executescript(ESQUEMA)
    return con


def alvo_link(nome: str) -> str:
    """Como o Obsidian casa [[links]]: pelo nome do arquivo, sem extensão e sem a pasta, ignorando maiúsculas."""
    return P.nfc(nome.strip().replace("\\", "/").split("/")[-1].removesuffix(".md")).casefold()


def analisar(texto: str) -> tuple[list[str], list[str]]:
    """Tags (frontmatter + #inline, fora de código) e alvos dos links [[ ]] de uma nota."""
    fm, corpo = P.ler_frontmatter(texto)
    tags_fm = fm.get("tags") or []
    if isinstance(tags_fm, str):
        tags_fm = [t for t in re.split(r"[,\s]+", tags_fm) if t]
    limpo = RE_CODIGO.sub(" ", corpo)
    tags = {str(t).lstrip("#").casefold() for t in tags_fm} | {t.casefold() for t in RE_TAG.findall(limpo)}
    links = sorted({alvo_link(m) for m in RE_LINK.findall(limpo) if m.strip()})
    return sorted(t for t in tags if t), links


def _arquivos(raiz: Path):
    for arq in raiz.rglob("*.md"):
        rel = arq.relative_to(raiz).parts
        if any(p.startswith(".") for p in rel):  # .obsidian, .trash e temporários de gravação
            continue
        yield arq


def atualizar(forcar: bool = False) -> dict[str, int]:
    """Sincroniza o índice com a pasta. Barato quando nada mudou (só lê datas de modificação)."""
    raiz = P.pasta()
    chave = str(raiz)
    with _trava:
        if not forcar and time.monotonic() - _ultima.get(chave, -1e9) < INTERVALO_S:
            return {"novas": 0, "alteradas": 0, "removidas": 0}
        _ultima[chave] = time.monotonic()
    if not raiz.exists():
        return {"novas": 0, "alteradas": 0, "removidas": 0}
    cont = {"novas": 0, "alteradas": 0, "removidas": 0}
    with conectar() as con:
        conhecidas = {r["caminho"]: (r["id"], r["mtime"], r["tamanho"]) for r in con.execute("SELECT id, caminho, mtime, tamanho FROM notas")}
        vistos = set()
        for arq in _arquivos(raiz):
            try:
                st = arq.stat()
            except OSError:
                continue
            rel = P.nfc(arq.relative_to(raiz).as_posix())
            vistos.add(rel)
            antes = conhecidas.get(rel)
            if antes and antes[1] == st.st_mtime and antes[2] == st.st_size:
                continue
            try:
                texto = arq.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            tags, links = analisar(texto)
            texto = P.ler_frontmatter(texto)[1]  # a busca e os trechos olham só o corpo da nota
            pasta_rel = "/".join(rel.split("/")[:-1])
            con.execute("""INSERT INTO notas(caminho, titulo, pasta, tags, mtime, tamanho, texto) VALUES (?,?,?,?,?,?,?)
                           ON CONFLICT(caminho) DO UPDATE SET titulo=excluded.titulo, pasta=excluded.pasta, tags=excluded.tags,
                           mtime=excluded.mtime, tamanho=excluded.tamanho, texto=excluded.texto""",
                        (rel, arq.stem, pasta_rel, " ".join(tags), st.st_mtime, st.st_size, texto))
            ident = con.execute("SELECT id FROM notas WHERE caminho = ?", (rel,)).fetchone()[0]
            con.execute("DELETE FROM links WHERE origem = ?", (ident,))
            con.executemany("INSERT INTO links(origem, alvo) VALUES (?,?)", [(ident, a) for a in links])
            cont["alteradas" if antes else "novas"] += 1
        sumiram = [(v[0],) for k, v in conhecidas.items() if k not in vistos]
        con.executemany("DELETE FROM notas WHERE id = ?", sumiram)
        cont["removidas"] = len(sumiram)
    return cont


def _nota(r: sqlite3.Row, trecho: str = "") -> Nota:
    return Nota(r["id"], r["caminho"], r["titulo"], r["pasta"], (r["tags"] or "").split(), r["mtime"], trecho)


def _consulta(texto: str, operador: str = " ") -> str:
    termos = re.findall(r"\w+", texto or "")
    return operador.join(f'"{t}"*' for t in termos[:12])


def buscar(texto: str, limite: int = 10, pasta: str | None = None) -> list[Nota]:
    """Busca por palavras (todas; se nada achar, qualquer uma) ou por #tag. `pasta` filtra pelo começo do caminho."""
    atualizar()
    texto = (texto or "").strip()
    filtro, args = f" AND n.caminho NOT LIKE '{P.MODELOS}/%'", []  # modelos ({{title}}…) só aparecem pedindo a pasta
    if pasta:
        filtro, args = " AND (n.caminho LIKE ? ESCAPE '\\')", [pasta.replace("%", r"\%").replace("_", r"\_").rstrip("/") + "/%"]
    with conectar() as con:
        if not texto:
            return [_nota(r) for r in con.execute(f"SELECT * FROM notas n WHERE 1=1{filtro} ORDER BY mtime DESC LIMIT ?",
                                                  (*args, limite))]
        if re.fullmatch(r"#[\wÀ-ÿ/-]+", texto):
            tag = texto[1:].casefold()
            return [_nota(r) for r in con.execute(
                f"SELECT * FROM notas n WHERE (' ' || tags || ' ') LIKE ?{filtro} ORDER BY mtime DESC LIMIT ?",
                (f"% {tag} %", *args, limite))]
        for operador in (" ", " OR "):
            consulta = _consulta(texto, operador)
            if not consulta:
                return []
            linhas = con.execute(
                f"""SELECT n.*, snippet(notas_busca, 1, '«', '»', ' … ', 18) AS trecho FROM notas_busca b
                    JOIN notas n ON n.id = b.rowid WHERE notas_busca MATCH ?{filtro}
                    ORDER BY bm25(notas_busca, 4.0, 1.0, 2.0) LIMIT ?""", (consulta, *args, limite)).fetchall()
            if linhas:
                return [_nota(r, re.sub(r"\s+", " ", r["trecho"] or "").strip()) for r in linhas]
    return []


def obter(caminho_ou_titulo: str) -> tuple[Nota, str] | None:
    """Nota pelo caminho (`Minhas notas/x.md`) ou pelo título/link (`x`). Devolve (nota, texto atual do arquivo)."""
    atualizar()
    alvo = P.nfc((caminho_ou_titulo or "").strip())
    with conectar() as con:
        r = con.execute("SELECT * FROM notas WHERE caminho = ?", (alvo,)).fetchone()
        if not r:
            nome = alvo_link(alvo)
            r = next((x for x in con.execute("SELECT * FROM notas ORDER BY mtime DESC") if x["titulo"].casefold() == nome), None)
    if not r:
        return None
    try:
        texto = P.caminho(r["caminho"]).read_text(encoding="utf-8-sig", errors="replace")
    except (OSError, ValueError):
        texto = r["texto"] or ""
    return _nota(r), texto


def quem_cita(nota: Nota, limite: int = 30) -> list[Nota]:
    with conectar() as con:
        return [_nota(r) for r in con.execute(
            "SELECT DISTINCT n.* FROM links l JOIN notas n ON n.id = l.origem WHERE l.alvo = ? AND n.id != ? "
            "ORDER BY n.mtime DESC LIMIT ?", (alvo_link(nota.titulo), nota.id, limite))]


def ligacoes(nota: Nota) -> tuple[list[Nota], list[str]]:
    """Notas para onde esta aponta (existentes) e links ainda sem nota (o Obsidian os mostra como "não criados")."""
    with conectar() as con:
        alvos = [r[0] for r in con.execute("SELECT alvo FROM links WHERE origem = ?", (nota.id,))]
        por_titulo = {}
        for r in con.execute("SELECT * FROM notas ORDER BY mtime DESC"):
            por_titulo.setdefault(r["titulo"].casefold(), r)
    existentes = [_nota(por_titulo[a]) for a in alvos if a in por_titulo]
    return existentes, [a for a in alvos if a not in por_titulo]


def estatisticas() -> dict[str, int]:
    atualizar()
    with conectar() as con:
        total = con.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
        minhas = con.execute("SELECT COUNT(*) FROM notas WHERE caminho LIKE ?", (P.MINHAS + "/%",)).fetchone()[0]
        links = con.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    return {"notas": total, "minhas": minhas, "links": links}
