"""Radar regulatório: normas e notícias regulatórias de fontes OFICIAIS (`config/radar_regulatorio.yaml`), com relevância
para o trabalho do Rickson calculada por temas (regras, sem modelo).

Fontes: CVM e Receita (RSS do gov.br, filtrados por palavras de norma/tributação), Banco Central (API pública da busca
de normativos) e Câmara dos Deputados (API de Dados Abertos: projetos apresentados nos últimos dias). Tudo guardado em
`dados/carreira.db` (tabela radar), sem repetir link; `novidades` mostra o que ainda não foi visto."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from typing import Any

from quiron.nucleo.config import ler_yaml
from quiron.servicos.carreira.banco import conectar
from quiron.servicos.mercado.http import FonteIndisponivel, obter

TTL = 3 * 3600


@dataclass
class Item:
    fonte: str
    titulo: str
    link: str
    publicado_em: datetime
    resumo: str = ""
    temas: list[str] | None = None
    relevancia: int = 0

    def descrever(self) -> str:
        estrelas = "🔴" if self.relevancia >= 3 else "🟡" if self.relevancia == 2 else "⚪"
        temas = f" [{', '.join(self.temas)}]" if self.temas else ""
        extra = f" — {self.resumo[:180]}" if self.resumo and self.resumo[:40] not in self.titulo else ""
        return f"{estrelas} {self.publicado_em:%d/%m} {self.fonte}: {self.titulo}{extra}{temas}\n   {self.link}"


def config() -> dict[str, Any]:
    return ler_yaml("radar_regulatorio")


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _limpo(html: str, limite: int = 400) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()[:limite]


def classificar(item: Item, temas: dict[str, Any] | None = None) -> Item:
    """Relevância = peso do tema mais importante que aparece no título/resumo (0 a 3). Palavras casam no início de
    uma palavra ("cri" não casa com "Circular")."""
    temas = temas or config()["temas"]
    texto = _norm(f"{item.titulo} {item.resumo}")
    achados = [(v["peso"], v["nome"]) for v in temas.values()
               if any(re.search(rf"\b{re.escape(_norm(p))}" + (r"\b" if len(p) <= 4 else ""), texto) for p in v["palavras"])]
    item.temas = [n for _, n in sorted(achados, reverse=True)]
    item.relevancia = max((p for p, _ in achados), default=0)
    return item


# ---------------------------------------------------------------- fontes
def _rss(f: dict[str, Any]) -> list[Item]:
    import feedparser

    r = obter(f["url"], fonte=f["nome"], ttl=TTL, formato="bytes")
    feed = feedparser.parse(r.conteudo)
    filtro = [_norm(p) for p in f.get("filtro", [])]
    saida = []
    for e in feed.entries:
        titulo, link = _limpo(e.get("title", ""), 300), e.get("link", "")
        resumo = _limpo(e.get("summary", "") or e.get("description", ""))
        if not titulo or not link or (filtro and not any(p in _norm(f"{titulo} {resumo}") for p in filtro)):
            continue
        st = e.get("published_parsed") or e.get("updated_parsed")
        quando = datetime(*st[:6], tzinfo=timezone.utc) if st else datetime.now(timezone.utc)
        saida.append(Item(f["nome"], titulo, link, quando, resumo))
    return saida


def _bcb(f: dict[str, Any]) -> list[Item]:
    r = obter(f["url"], fonte=f["nome"], ttl=TTL, params={
        "querytext": "ContentType:normativo AND contentSource:normativos", "rowlimit": 60, "startrow": 0,
        "sortlist": "Data1OWSDATE:descending"})
    tipos = set(f.get("tipos", []))
    saida = []
    for x in (r.conteudo or {}).get("Rows", []):
        tipo = x.get("TipodoNormativoOWSCHCS", "")
        if tipos and tipo not in tipos:
            continue
        numero = str(x.get("NumeroOWSNMBR", "")).split(".")[0]
        try:
            quando = datetime.fromisoformat(str(x.get("data", "")).replace("Z", "+00:00"))
        except ValueError:
            quando = datetime.now(timezone.utc)
        link = f"https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo={tipo.replace(' ', '%20')}&numero={numero}"
        saida.append(Item(f["nome"], x.get("title", f"{tipo} {numero}"), link, quando, _limpo(x.get("AssuntoNormativoOWSMTXT", ""))))
    return saida


def _camara(f: dict[str, Any], dias: int = 30) -> list[Item]:
    inicio = (date.today() - timedelta(days=dias)).isoformat()
    vistos, saida = set(), []
    for palavra in f.get("palavras", []):
        r = obter(f["url"], fonte=f["nome"], ttl=12 * 3600, params={
            "keywords": palavra, "dataApresentacaoInicio": inicio, "ordem": "DESC", "ordenarPor": "id", "itens": 15},
            cabecalhos={"Accept": "application/json"})
        for x in (r.conteudo or {}).get("dados", []):
            if x["id"] in vistos or x.get("siglaTipo") not in {"PL", "PLP", "PEC", "MPV"}:
                continue
            vistos.add(x["id"])
            try:
                quando = datetime.fromisoformat(x.get("dataApresentacao", "")).replace(tzinfo=timezone(timedelta(hours=-3)))
            except ValueError:
                quando = datetime.now(timezone.utc)
            saida.append(Item(f["nome"], f"{x['siglaTipo']} {x['numero']}/{x['ano']}: {_limpo(x.get('ementa', ''), 220)}",
                              f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={x['id']}", quando,
                              _limpo(x.get("ementa", ""))))
    return saida


LEITORES = {"rss": _rss, "bcb_normativos": _bcb, "camara": _camara}


def atualizar(fontes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Coleta todas as fontes, classifica e grava as novas. Devolve {novos, por_fonte, erros}."""
    cfg = config()
    novos, por_fonte, erros = 0, {}, {}
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for f in fontes or cfg["fontes"]:
        try:
            itens = [classificar(i, cfg["temas"]) for i in LEITORES[f["tipo"]](f)]
        except (FonteIndisponivel, KeyError, ValueError) as e:
            erros[f["nome"]] = str(e)[:200]
            continue
        n = 0
        with conectar() as con:
            for i in itens:
                cur = con.execute("INSERT OR IGNORE INTO radar(link, fonte, titulo, resumo, publicado_em, temas, relevancia, coletado_em) "
                                  "VALUES (?,?,?,?,?,?,?,?)", (i.link, i.fonte, i.titulo, i.resumo, i.publicado_em.isoformat(),
                                                               "|".join(i.temas or []), i.relevancia, agora))
                n += cur.rowcount
        por_fonte[f["nome"]] = (len(itens), n)
        novos += n
    return {"novos": novos, "por_fonte": por_fonte, "erros": erros}


def _de(r) -> Item:
    return Item(r["fonte"], r["titulo"], r["link"], datetime.fromisoformat(r["publicado_em"]), r["resumo"],
                [t for t in r["temas"].split("|") if t], r["relevancia"])


def listar(dias: int = 30, minimo: int = 1, so_novos: bool = False, limite: int = 40) -> list[Item]:
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    sql = "SELECT * FROM radar WHERE publicado_em >= ? AND relevancia >= ?" + (" AND visto_em = ''" if so_novos else "")
    with conectar() as con:
        linhas = con.execute(sql + " ORDER BY relevancia DESC, publicado_em DESC LIMIT ?", (desde, minimo, limite)).fetchall()
    return [_de(r) for r in linhas]


def marcar_vistos(itens: list[Item]) -> None:
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conectar() as con:
        con.executemany("UPDATE radar SET visto_em = ? WHERE link = ? AND visto_em = ''", [(agora, i.link) for i in itens])


def regras_para_conferir() -> list[str]:
    """Blocos de config/regras_mercado.yaml sem verificação há mais de 90 dias (o radar lembra de conferir)."""
    try:
        from quiron.nucleo import regras

        return [s.bloco for s in regras.situacao() if not s.ok]
    except Exception:  # noqa: BLE001
        return []


def relatorio(dias: int = 14, so_novos: bool = False, atualizar_antes: bool = True, minimo: int = 1) -> str:
    erros = {}
    if atualizar_antes:
        erros = atualizar()["erros"]
    itens = listar(dias, minimo, so_novos)
    cab = f"📡 Radar regulatório — {'novidades' if so_novos else f'últimos {dias} dias'} (fontes oficiais)"
    if not itens:
        corpo = "Nada relevante no período." if not so_novos else "Nenhuma novidade relevante desde a última vez."
    else:
        corpo = "\n".join(i.descrever() for i in itens)
        marcar_vistos(itens)
    partes = [cab, corpo, "🔴 mexe no seu dia a dia · 🟡 vale acompanhar · ⚪ contexto. Peça “explique o item X” para o impacto."]
    pend = regras_para_conferir()
    if pend:
        partes.append(f"⚠️ {len(pend)} bloco(s) de config/regras_mercado.yaml sem conferência (ou há mais de 90 dias): {', '.join(pend[:5])}")
    if erros:
        partes.append("Fora do ar agora: " + ", ".join(erros))
    return "\n\n".join(partes)
