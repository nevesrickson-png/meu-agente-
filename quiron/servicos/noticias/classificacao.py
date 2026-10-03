"""Classificação de notícias e posts: temas, ativos (tickers) e palavras-alerta. Tudo por regras em
`config/temas_noticias.yaml` — previsível, explicável e sem custo de modelo."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from quiron.nucleo.config import ler_yaml
from quiron.servicos.biblioteca.trechos import chave

_TICKER = re.compile(r"\b([A-Z]{4}(?:3|4|5|6|11))\b")


@dataclass(frozen=True)
class Regras:
    temas: dict[str, tuple[re.Pattern, ...]]
    alertas: tuple[tuple[str, re.Pattern], ...]
    empresas: tuple[tuple[re.Pattern, str], ...]


def _padrao(termo: str) -> re.Pattern:
    return re.compile(rf"(?<![\w]){re.escape(chave(termo))}(?![\w])")


@lru_cache(maxsize=1)
def regras() -> Regras:
    cfg = ler_yaml("temas_noticias") or {}
    temas = {t: tuple(_padrao(p) for p in palavras) for t, palavras in (cfg.get("temas") or {}).items()}
    alertas = tuple((a, _padrao(a)) for a in cfg.get("alertas") or [])
    # nomes de empresa exigem inicial maiúscula ("Vale", não "vale a pena"); o resto ignora maiúsculas e acentos
    excecoes = cfg.get("empresas_excecoes") or {}

    def _empresa(nome: str) -> re.Pattern:
        nao = "".join(rf"(?!\s+(?i:{re.escape(e)})\b)" for e in excecoes.get(nome, []))
        return re.compile(rf"(?<![\w]){re.escape(nome[0].upper())}(?i:{re.escape(nome[1:])})(?![\w]){nao}")

    empresas = tuple((_empresa(nome), ticker) for nome, ticker in (cfg.get("empresas") or {}).items())
    return Regras(temas, alertas, empresas)


def temas(texto: str) -> list[str]:
    t = chave(texto)
    return [tema for tema, padroes in regras().temas.items() if any(p.search(t) for p in padroes)]


def alertas(texto: str) -> list[str]:
    t = chave(texto)
    return [nome for nome, p in regras().alertas if p.search(t)]


def ativos(texto: str) -> list[str]:
    achados = set(_TICKER.findall(texto))
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    for padrao, ticker in regras().empresas:  # mantém maiúsculas, tira acentos ("Itaú" → "Itau")
        if padrao.search(sem_acento):
            achados.add(ticker)
    return sorted(achados)
