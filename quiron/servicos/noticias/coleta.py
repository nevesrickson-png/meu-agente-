"""Coleta de notícias por RSS/feeds oficiais, com deduplicação e classificação, guardadas em `dados/quiron.db`."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from quiron.nucleo.banco import conectar as conectar_banco
from quiron.nucleo.config import ler_yaml, pasta_dados
from quiron.servicos.biblioteca.trechos import chave
from quiron.servicos.mercado.http import FonteIndisponivel, obter
from quiron.servicos.noticias import classificacao

TTL_FEED = 10 * 60  # não consulta o mesmo feed mais de uma vez a cada 10 min


@dataclass
class Noticia:
    id: str
    titulo: str
    link: str
    fonte: str
    grupo: str
    publicado_em: datetime  # UTC
    resumo: str = ""
    temas: list[str] = field(default_factory=list)
    ativos: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    outras_fontes: list[str] = field(default_factory=list)


@dataclass
class ResultadoFonte:
    nome: str
    ok: bool
    itens: int
    detalhe: str = ""


# ---------------------------------------------------------------- banco


def _banco() -> sqlite3.Connection:
    caminho = pasta_dados() / "quiron.db"
    con = conectar_banco(caminho)
    con.execute(
        """CREATE TABLE IF NOT EXISTS noticias (
            id TEXT PRIMARY KEY, chave_titulo TEXT, titulo TEXT, link TEXT, fonte TEXT, grupo TEXT,
            publicado_em TEXT, resumo TEXT, temas TEXT, ativos TEXT, alertas TEXT, outras_fontes TEXT, coletado_em TEXT)"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS noticias_data ON noticias(publicado_em)")
    con.execute("CREATE INDEX IF NOT EXISTS noticias_chave ON noticias(chave_titulo)")
    return con


def _linha_para_noticia(l: tuple) -> Noticia:
    return Noticia(
        l[0], l[2], l[3], l[4], l[5], datetime.fromisoformat(l[6]), l[7] or "",
        json.loads(l[8]), json.loads(l[9]), json.loads(l[10]), json.loads(l[11]),
    )


def listar(horas: int = 24, limite: int | None = 500) -> list[Noticia]:
    """Notícias das últimas `horas`, mais novas primeiro. Busca por termo passa `limite=None` (o filtro vem depois:
    com 79 fontes, 500 itens cobrem só ~1 dia)."""
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat()
    with _banco() as con:
        linhas = con.execute(
            "SELECT * FROM noticias WHERE publicado_em >= ? ORDER BY publicado_em DESC LIMIT ?", (desde, limite or -1)
        ).fetchall()
    desligadas = set((ler_yaml("fontes_noticias") or {}).get("desligadas") or [])  # fonte desligada some na hora
    return [n for n in (_linha_para_noticia(l) for l in linhas) if n.fonte not in desligadas]


# ---------------------------------------------------------------- normalização


def link_canonico(link: str) -> str:
    """Tira parâmetros de rastreio (utm_*, etc.) e a âncora, para reconhecer o mesmo link."""
    p = urlsplit(link.strip())
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid", "ref"))]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(query), ""))


def chave_titulo(titulo: str) -> str:
    """Título normalizado: a mesma manchete em dois portais vira a mesma chave."""
    palavras = re.findall(r"[a-z0-9]+", chave(titulo))
    return " ".join(palavras[:12])


def texto_limpo(bruto: str, limite: int = 400) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(bruto or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limite else t[:limite].rsplit(" ", 1)[0] + "…"


def _data_feed(entrada) -> datetime:
    for campo in ("published_parsed", "updated_parsed"):
        st = entrada.get(campo)
        if st:
            return datetime(*st[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- leitura das fontes


def ler_fontes() -> list[dict]:
    cfg = ler_yaml("fontes_noticias") or {}
    desligadas = set(cfg.get("desligadas") or [])  # desligadas pela tela de Configurações
    return [f for f in cfg.get("fontes", []) if f.get("ativo", True) and f["nome"] not in desligadas]


def _itens_rss(fonte: dict) -> list[Noticia]:
    import feedparser

    r = obter(fonte["url"], fonte=fonte["nome"], ttl=TTL_FEED, formato="bytes")
    feed = feedparser.parse(r.conteudo)
    if feed.bozo and not feed.entries:
        raise FonteIndisponivel(f"{fonte['nome']}: feed inválido ({feed.bozo_exception})")
    saida = []
    for e in feed.entries:
        titulo = texto_limpo(e.get("title", ""), 300)
        link = e.get("link", "")
        if "*http" in link:  # redirecionador do portal (ex.: redir.folha.com.br/…*https://…): fica o endereço real
            link = link.split("*", 1)[1]
        if not titulo or not link:
            continue
        resumo = texto_limpo(e.get("summary", "") or e.get("description", ""))
        saida.append(Noticia("", titulo, link, fonte["nome"], fonte.get("grupo", ""), _data_feed(e), resumo))
    return saida


def _itens_ibge(fonte: dict) -> list[Noticia]:
    r = obter(fonte["url"], fonte=fonte["nome"], ttl=TTL_FEED)
    saida = []
    for i in r.conteudo.get("items", []):
        quando = datetime.strptime(i["data_publicacao"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=-3)))
        link = i.get("link") or f"https://agenciadenoticias.ibge.gov.br/agencia-noticias/{i['id']}"
        saida.append(
            Noticia("", texto_limpo(i["titulo"], 300), link, fonte["nome"], fonte.get("grupo", ""), quando.astimezone(timezone.utc),
                    texto_limpo(i.get("introducao", "")))
        )
    return saida


def _classificar(n: Noticia) -> Noticia:
    texto = f"{n.titulo}. {n.resumo}"
    n.id = hashlib.sha1(link_canonico(n.link).encode()).hexdigest()[:16]
    n.temas = classificacao.temas(texto)
    n.ativos = classificacao.ativos(texto)
    n.alertas = classificacao.alertas(texto)
    return n


RETENCAO_DIAS = 180  # a leitura mais longa do Quíron é de 30 dias: o resto só fazia o banco crescer para sempre


def _gravar(noticias: list[Noticia]) -> int:
    """Grava as novas; a mesma manchete de outra fonte vira 'outras_fontes' da primeira. Devolve quantas eram novas."""
    novas = 0
    agora = datetime.now(timezone.utc).isoformat()
    corte = datetime.now(timezone.utc) - timedelta(days=RETENCAO_DIAS)
    with _banco() as con:
        for n in noticias:
            if n.publicado_em < corte:  # item velho do feed: seria apagado na limpeza e regravado na próxima coleta
                continue
            if con.execute("SELECT 1 FROM noticias WHERE id = ?", (n.id,)).fetchone():
                continue
            ct = chave_titulo(n.titulo)
            # mesma manchete em ~12 h = mesma notícia; colunas fixas ("Ibovespa hoje") do dia seguinte são outra
            igual = con.execute(
                "SELECT id, fonte, outras_fontes FROM noticias WHERE chave_titulo = ? AND publicado_em BETWEEN ? AND ?",
                (ct, (n.publicado_em - timedelta(hours=12)).isoformat(), (n.publicado_em + timedelta(hours=12)).isoformat()),
            ).fetchone() if len(ct.split()) >= 3 else None
            if igual:
                outras = json.loads(igual[2])
                if n.fonte != igual[1] and n.fonte not in outras:
                    outras.append(n.fonte)
                    con.execute("UPDATE noticias SET outras_fontes = ? WHERE id = ?", (json.dumps(outras, ensure_ascii=False), igual[0]))
                continue
            con.execute(
                "INSERT INTO noticias VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (n.id, ct, n.titulo, n.link, n.fonte, n.grupo, n.publicado_em.isoformat(), n.resumo,
                 json.dumps(n.temas), json.dumps(n.ativos), json.dumps(n.alertas, ensure_ascii=False), "[]", agora),
            )
            novas += 1
    return novas


def _baixar(f: dict) -> list[Noticia]:
    itens = _itens_ibge(f) if f.get("tipo") == "ibge_api" else _itens_rss(f)
    return [_classificar(n) for n in itens]


def coletar(fontes: list[dict] | None = None) -> list[ResultadoFonte]:
    """Baixa as fontes em paralelo (24 feeds: ~25 s em fila → poucos segundos) e grava em ordem, uma de cada vez."""
    from concurrent.futures import ThreadPoolExecutor

    lista = fontes if fontes is not None else ler_fontes()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futuros = [(f, ex.submit(_baixar, f)) for f in lista]
    resultados = []
    for f, futuro in futuros:
        try:
            itens = futuro.result()
            novas = _gravar(itens)
            resultados.append(ResultadoFonte(f["nome"], True, len(itens), f"{novas} novas"))
        except Exception as e:  # noqa: BLE001 — uma fonte com problema não derruba as outras
            resultados.append(ResultadoFonte(f["nome"], False, 0, f"{type(e).__name__}: {str(e)[:120]}"))
    if fontes is None:
        limpar_antigas()
    return resultados


def limpar_antigas(dias: int = RETENCAO_DIAS) -> int:
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    try:
        with _banco() as con:
            return con.execute("DELETE FROM noticias WHERE publicado_em < ?", (corte,)).rowcount
    except sqlite3.OperationalError:  # banco ocupado: limpa na próxima coleta
        return 0
