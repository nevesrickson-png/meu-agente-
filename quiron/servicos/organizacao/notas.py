"""Notas rápidas (`/nota texto #tag`): desde 08/10/2026 cada nota é um arquivo Markdown no Cérebro (cofre do Obsidian),
em `Minhas notas/Entrada/`. A busca (`/notas`) procura no Cérebro inteiro, por palavra (sem acento) ou #tag.

As notas antigas, que ficavam só no banco `organizacao.db`, são levadas para o Cérebro uma vez (`migrar_antigas`).
Cliente só como CLI-XXX.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from quiron.servicos.obsidian import indice
from quiron.servicos.obsidian import pasta as P

RE_TAG = re.compile(r"#([\wÀ-ÿ-]+)")
RE_CLIENTE = re.compile(r"\bCLI-\w+\b", re.I)


@dataclass
class Nota:
    id: int
    texto: str
    tags: str
    cliente: str
    criada_em: str
    caminho: str = ""
    trecho: str = ""

    def descrever(self) -> str:
        quando = datetime.fromisoformat(self.criada_em).strftime("%d/%m %H:%M")
        onde = "" if self.caminho.startswith(P.ENTRADA + "/") else f" [[{self.caminho.rsplit('/', 1)[-1].removesuffix('.md')}]]"
        texto = self.trecho or self.texto
        return f"🗒️ #{self.id} ({quando}){onde} {texto}"


def _preparar() -> None:
    from quiron.servicos.obsidian import rotina

    rotina.preparar()


def _titulo(texto: str) -> str:
    sem_tags = RE_TAG.sub("", texto).strip()
    palavras = re.sub(r"\s+", " ", sem_tags).split(" ")
    titulo = " ".join(palavras[:9]).rstrip(" .,:;–-")
    return (titulo + "…") if len(palavras) > 9 else (titulo or "Nota")


def criar(texto: str, agora: datetime | None = None) -> Nota:
    texto = (texto or "").strip()
    if len(texto) < 2:
        raise ValueError("escreva a nota (ex.: /nota ideia de pauta: duration explicada com gangorra #conteudo)")
    texto = texto[:4000]
    tags = sorted({t.lower() for t in RE_TAG.findall(texto)})
    agora = agora or P.agora()
    _preparar()
    corpo = P.frontmatter({"criada": agora.isoformat(timespec="seconds"), "origem": "quiron", "tags": tags}) + texto + "\n"
    arq = P.criar_nova(P.ENTRADA, f"{agora:%Y-%m-%d %H%M} {_titulo(texto)}", corpo)
    indice.atualizar(forcar=True)
    return _de(indice.obter(P.relativo(arq))[0], corpo)


def _de(n: indice.Nota, texto: str | None = None) -> Nota:
    if texto is None:
        try:
            texto = P.caminho(n.caminho).read_text(encoding="utf-8-sig", errors="replace")
        except (OSError, ValueError):
            texto = ""
    fm, corpo = P.ler_frontmatter(texto)
    criada = str(fm.get("criada") or "")
    try:
        datetime.fromisoformat(criada)
    except ValueError:
        criada = datetime.fromtimestamp(n.mtime).isoformat(timespec="seconds")
    corpo = re.sub(r"\s+", " ", corpo).strip()
    return Nota(n.id, corpo[:400], " ".join(n.tags), (RE_CLIENTE.search(corpo) or [""])[0].upper(), criada, n.caminho, n.trecho)


def buscar(termo: str = "", limite: int = 15) -> list[Nota]:
    """Sem termo: as notas mais recentes de Minhas notas. Com termo: o Cérebro inteiro (palavras ou #tag)."""
    _preparar()
    termo = (termo or "").strip()
    achadas = indice.buscar(termo, limite, pasta=None if termo else P.MINHAS)
    return [_de(n) for n in achadas]


def remover(ident: int) -> bool:
    """Apaga uma nota do /nota (só as de Minhas notas/Entrada; as outras notas são do Rickson e se apagam no Obsidian)."""
    indice.atualizar(forcar=True)
    with indice.conectar() as con:
        r = con.execute("SELECT caminho FROM notas WHERE id = ?", (ident,)).fetchone()
    if not r or not r[0].startswith(P.ENTRADA + "/"):
        return False
    try:
        P.caminho(r[0]).unlink()
    except (OSError, ValueError):
        return False
    indice.atualizar(forcar=True)
    return True


def descrever(itens: list[Nota], termo: str = "") -> str:
    if not itens:
        return f"Nenhuma nota{' com “' + termo + '”' if termo else ''}. Crie com /nota <texto> (#tags ajudam a achar depois)."
    return "\n".join(n.descrever() for n in itens)


def migrar_antigas() -> int:
    """Leva as notas que estavam só no banco (`organizacao.db`) para o Cérebro, uma vez. Devolve quantas foram levadas.

    Cada nota vira um arquivo em Minhas notas/Entrada com a data original; a linha só sai do banco depois que o arquivo
    foi gravado (se faltar disco no meio, as que faltam ficam para a próxima vez)."""
    from quiron.servicos.organizacao.banco import conectar

    with conectar() as con:
        antigas = con.execute("SELECT * FROM notas ORDER BY id").fetchall()
    if not antigas:
        return 0
    P.garantir()
    levadas = 0
    for r in antigas:
        try:
            criada = datetime.fromisoformat(r["criada_em"])
        except (TypeError, ValueError):
            criada = P.agora()
        tags = (r["tags"] or "").split()
        corpo = P.frontmatter({"criada": criada.isoformat(timespec="seconds"), "origem": "quiron", "tags": tags}) + r["texto"] + "\n"
        P.criar_nova(P.ENTRADA, f"{criada:%Y-%m-%d %H%M} {_titulo(r['texto'])}", corpo)
        with conectar() as con:
            con.execute("DELETE FROM notas WHERE id = ?", (r["id"],))
        levadas += 1
    indice.atualizar(forcar=True)
    return levadas
