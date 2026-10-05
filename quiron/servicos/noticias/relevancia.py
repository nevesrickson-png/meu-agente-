"""Qualidade da informação: o que de fato importa para um assessor, em vez de "as mais recentes".

1. **Histórias**: a mesma notícia contada por vários portais vira UMA história, com a lista de quem cobriu
   (manchetes parecidas — palavras importantes em comum —, não só o título idêntico).
2. **Nota de relevância** (Python, explicável): peso dos temas de mercado (juros, inflação, fiscal… valem mais que
   internacional genérico), tema no título vale mais que no resumo, ativos citados, palavras-alerta, credibilidade da
   fonte (oficial > imprensa de referência > portal), quantos veículos cobriram e quão recente é. Assunto fora do
   escopo (esporte, celebridade, crime…) é descartado.
Pesos, fontes e ruído ficam em `config/temas_noticias.yaml` e `config/fontes_noticias.yaml`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache

from quiron.nucleo.config import ler_yaml
from quiron.servicos.biblioteca.trechos import chave
from quiron.servicos.noticias import classificacao
from quiron.servicos.noticias.coleta import Noticia

PESO_TEMA_PADRAO = {
    "copom": 3.0, "juros": 3.0, "inflacao": 3.0, "banco_central": 2.5, "fiscal": 2.5, "cambio": 2.5, "renda_fixa": 2.5,
    "politica": 2.0, "bolsa": 2.0, "fed": 2.0, "tributacao": 2.0, "regulacao": 1.5, "fundos_previdencia": 1.5,
    "commodities": 1.5, "empresas": 1.5, "internacional": 0.8, "cripto": 0.8,
}
PESO_GRUPO_PADRAO = {"oficiais": 1.0, "referencia": 0.9, "brasil": 0.75, "global": 0.75}
MEIA_VIDA_H = 12.0  # uma notícia de 12 h atrás vale metade de uma de agora
_PALAVRAS_VAZIAS = set("""
para pelo pela pelos pelas com sem sobre entre apos antes como mais menos muito todo toda todos todas este esta esse essa
isso aquele aquela qual quais quando onde porque diz dizem disse afirma segundo ainda pode podem deve devem nesta neste
seus suas sera serao tem foram sendo estao esta vai vao veja entenda saiba what with from that this have will after over
into about their says said amid than more most could would should your they them were been
""".split())


@dataclass
class Historia:
    titulo: str
    link: str
    fonte: str
    publicado_em: datetime  # a mais recente da história (UTC)
    fontes: list[str] = field(default_factory=list)  # todos os veículos que cobriram (o principal primeiro)
    temas: list[str] = field(default_factory=list)
    ativos: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    nota: float = 0.0
    itens: list[Noticia] = field(default_factory=list)

    @property
    def cobertura(self) -> int:
        return len(self.fontes)


@lru_cache(maxsize=1)
def _cfg() -> tuple[dict[str, float], dict[str, float], tuple[re.Pattern, ...]]:
    temas = ler_yaml("temas_noticias") or {}
    pesos = {**PESO_TEMA_PADRAO, **{k: float(v) for k, v in (temas.get("pesos") or {}).items()}}
    fontes = {f["nome"]: float(f["peso"]) if "peso" in f else PESO_GRUPO_PADRAO.get(f.get("grupo", ""), 0.75)
              for f in (ler_yaml("fontes_noticias") or {}).get("fontes", [])}
    ruido = tuple(re.compile(rf"(?<![\w]){re.escape(chave(p))}(?![\w])") for p in temas.get("ruido") or [])
    return pesos, fontes, ruido


def limpar_cache() -> None:
    _cfg.cache_clear()


def peso_fonte(n: Noticia) -> float:
    return _cfg()[1].get(n.fonte, PESO_GRUPO_PADRAO.get(n.grupo, 0.75))


def e_ruido(titulo: str) -> bool:
    t = chave(titulo)
    return any(p.search(t) for p in _cfg()[2])


def nota(n: Noticia, agora: datetime | None = None, cobertura: int = 1) -> float:
    """Relevância de uma notícia (0 = fora do escopo). Ver o topo do módulo."""
    pesos = _cfg()[0]
    if e_ruido(n.titulo):
        return 0.0
    no_titulo = set(classificacao.temas(n.titulo))
    if not no_titulo and not n.ativos and not n.alertas and n.grupo != "oficiais":
        return 0.0  # assunto de mercado só no resumo ("Candidatos a governador… — Eleições") não é notícia de mercado
    base = sum(pesos.get(t, 1.0) * (1.0 if t in no_titulo else 0.35) for t in set(n.temas) | no_titulo)
    base = min(base, 7.0)  # muitos temas não fazem uma notícia valer 5 vezes mais
    base += min(len(n.ativos), 3) * 0.8 + len(n.alertas) * 2.0
    if n.grupo == "oficiais":
        base += 1.5  # comunicado oficial (BC, CVM, IBGE, Fed) é informação primária
    if base <= 0:
        return 0.0
    agora = agora or datetime.now(timezone.utc)
    idade_h = max(0.0, (agora - n.publicado_em).total_seconds() / 3600)
    recencia = 0.5 ** (idade_h / MEIA_VIDA_H)
    return round(base * peso_fonte(n) * (1 + 0.6 * math.log2(cobertura)) * (0.35 + 0.65 * recencia), 3)


def _radical(p: str) -> str:
    p = re.sub(r"(?:oes|aes)$", "ao", p)  # eleições → eleicao
    return (p[:-1] if p.endswith("s") and len(p) > 4 else p)[:7]


def _palavras(titulo: str) -> set[str]:
    return {_radical(p) for p in re.findall(r"[a-z0-9$%]{4,}", chave(titulo)) if p not in _PALAVRAS_VAZIAS}


def _parecidas(a: set[str], b: set[str]) -> bool:
    comuns = len(a & b)
    proporcao = comuns / max(1, min(len(a), len(b)))
    return (comuns >= 3 and proporcao >= 0.5) or (comuns >= 4 and proporcao >= 0.35)


def agrupar(noticias: list[Noticia], agora: datetime | None = None) -> list[Historia]:
    """Junta a mesma história de vários veículos e ordena pela nota (maior primeiro). Ruído fica de fora."""
    agora = agora or datetime.now(timezone.utc)
    grupos: list[tuple[set[str], list[Noticia]]] = []
    for n in sorted(noticias, key=lambda x: x.publicado_em, reverse=True):
        if e_ruido(n.titulo):
            continue
        pal = _palavras(n.titulo)
        for palavras, itens in grupos:
            if _parecidas(pal, palavras) and abs((itens[0].publicado_em - n.publicado_em).total_seconds()) < 36 * 3600:
                itens.append(n)
                palavras |= pal
                break
        else:
            grupos.append((pal, [n]))
    historias = []
    for _, itens in grupos:
        fontes: list[str] = []
        for n in sorted(itens, key=lambda x: -peso_fonte(x)):
            for f in [n.fonte, *n.outras_fontes]:
                if f not in fontes:
                    fontes.append(f)
        principal = max(itens, key=lambda x: (peso_fonte(x), x.publicado_em))
        melhor = max(nota(n, agora, len(fontes)) for n in itens)
        if melhor <= 0:
            continue
        historias.append(Historia(
            principal.titulo, principal.link, principal.fonte, max(n.publicado_em for n in itens), fontes,
            sorted({t for n in itens for t in n.temas}), sorted({a for n in itens for a in n.ativos}),
            sorted({a for n in itens for a in n.alertas}), melhor, itens))
    historias.sort(key=lambda h: (-h.nota, -h.publicado_em.timestamp()))
    return historias


def tema_principal(h: Historia) -> str:
    pesos = _cfg()[0]
    no_titulo = classificacao.temas(h.titulo) or h.temas
    return max(no_titulo, key=lambda t: pesos.get(t, 1.0)) if no_titulo else "outros"


def diversificar(historias: list[Historia], n: int, max_por_tema: int = 2) -> list[Historia]:
    """As `n` melhores sem deixar um assunto só ocupar tudo (no dia da eleição, entra também o que não é eleição)."""
    escolhidas, contagem, sobra = [], {}, []
    for h in historias:
        t = tema_principal(h)
        if contagem.get(t, 0) < max_por_tema:
            escolhidas.append(h)
            contagem[t] = contagem.get(t, 0) + 1
        else:
            sobra.append(h)
        if len(escolhidas) == n:
            return escolhidas
    return (escolhidas + sobra)[:n]
