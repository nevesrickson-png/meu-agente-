"""Cotações: B3 pela brapi (token gratuito opcional) e mercado global pelo Yahoo Finance (yfinance).

Dados gratuitos têm atraso (B3 ~15 min); toda cotação traz o horário do próprio dado.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from quiron.servicos.mercado.http import FonteIndisponivel, obter

URL_BRAPI = "https://brapi.dev/api/quote/{ticker}"

# Nomes da watchlist → símbolo no Yahoo. Ativos da B3 sem mapeamento vão para a brapi.
YAHOO = {
    "IBOV": "^BVSP",
    "IFIX": "IFIX.SA",  # a brapi só entrega o IFIX com token
    "SMLL": "SMAL11.SA",  # ETF que replica o SMLL (o índice não tem símbolo estável no Yahoo)
    "^GSPC": "^GSPC",
    "^IXIC": "^IXIC",
    "USDBRL": "BRL=X",
    "EURBRL": "EURBRL=X",
    "petroleo_brent": "BZ=F",
    "ouro": "GC=F",
    "minerio_ferro": "TIO=F",
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
}
NOMES = {
    "IBOV": "Ibovespa", "IFIX": "IFIX", "SMLL": "Small Caps (via SMAL11)", "^GSPC": "S&P 500", "^IXIC": "Nasdaq",
    "USDBRL": "Dólar", "EURBRL": "Euro", "petroleo_brent": "Petróleo Brent", "ouro": "Ouro", "minerio_ferro": "Minério de ferro",
}


@dataclass
class Cotacao:
    ativo: str
    nome: str
    preco: float
    variacao_pct: float | None
    moeda: str
    horario: datetime | None  # horário do dado na fonte
    fonte: str
    obtido_em: datetime
    atraso: str = ""

    @property
    def minutos_desde_dado(self) -> float | None:
        if not self.horario:
            return None
        return (datetime.now(timezone.utc) - self.horario.astimezone(timezone.utc)).total_seconds() / 60


def brapi(ticker: str) -> Cotacao:
    params = {}
    if token := os.environ.get("BRAPI_TOKEN", "").split(" #")[0].strip():
        params["token"] = token
    r = obter(URL_BRAPI.format(ticker=ticker.upper()), params=params, fonte="brapi (B3)", ttl=300)
    resultados = r.conteudo.get("results") or []
    if not resultados:
        raise FonteIndisponivel(f"brapi sem dados para {ticker}: {r.conteudo.get('message', '')}")
    q = resultados[0]
    horario = q.get("regularMarketTime")
    return Cotacao(
        ticker.upper(),
        q.get("longName") or q.get("shortName") or ticker.upper(),
        float(q["regularMarketPrice"]),
        q.get("regularMarketChangePercent"),
        q.get("currency") or "BRL",
        datetime.fromisoformat(horario.replace("Z", "+00:00")) if horario else None,
        r.fonte,
        r.obtido_em,
        "dados da B3 com atraso de ~15 min",
    )


def _historico_yahoo(simbolo: str, periodo: str = "5d"):
    """Isolado para os testes poderem substituir (o yfinance usa a própria conexão)."""
    import yfinance as yf

    return yf.Ticker(simbolo).history(period=periodo, interval="1d", auto_adjust=False)


_memo: dict[tuple[str, str], tuple[float, object]] = {}
TTL_YAHOO = 60  # o mesmo ativo não é pedido ao Yahoo mais de uma vez por minuto


def _historico_memo(simbolo: str, periodo: str):
    agora = time.time()
    guardado = _memo.get((simbolo, periodo))
    if guardado and agora - guardado[0] < TTL_YAHOO:
        return guardado[1]
    from quiron.nucleo import offline

    if offline.ativo():
        raise FonteIndisponivel(f"Yahoo ({simbolo}): offline")
    hist = _historico_yahoo(simbolo, periodo)
    _memo[(simbolo, periodo)] = (agora, hist)
    return hist


def simbolo_yahoo(ativo: str) -> str:
    """Nome da watchlist/ticker → símbolo do Yahoo (ticker da B3 ganha .SA)."""
    if ativo in YAHOO:
        return YAHOO[ativo]
    if ativo.startswith("^") or "=" in ativo or "." in ativo:
        return ativo
    return f"{ativo.upper()}.SA"


def historico(ativo: str, periodo: str = "6mo") -> list[tuple[datetime, float]]:
    """Fechamentos diários (Yahoo). periodo: 1mo, 3mo, 6mo, 1y, 5y."""
    simbolo = simbolo_yahoo(ativo)
    try:
        hist = _historico_memo(simbolo, periodo)
    except Exception as e:  # noqa: BLE001
        raise FonteIndisponivel(f"Yahoo indisponível para {simbolo}: {e}") from e
    if hist is None or len(hist) == 0:
        raise FonteIndisponivel(f"Yahoo sem histórico para {simbolo}")
    fech = hist["Close"].dropna()
    return [(i.to_pydatetime(), float(v)) for i, v in fech.items()]


def desempenho(ativo: str, serie: list[tuple[datetime, float]] | None = None) -> dict:
    """Variações calculadas sobre os fechamentos diários do último ano (Yahoo): 1 semana, 1 mês, no ano, 12 meses,
    mínima/máxima de 52 semanas. Cada variação compara o último fechamento com o último pregão até a data-base."""
    serie = serie or historico(ativo, "1y")
    if len(serie) < 2:
        raise FonteIndisponivel(f"histórico curto demais para {ativo}")
    ultimo_dia, ultimo = serie[-1]

    def base_em(limite) -> float | None:
        anteriores = [v for d, v in serie if d.date() <= limite]
        return anteriores[-1] if anteriores else None

    def var(base: float | None) -> float | None:
        return (ultimo / base - 1) * 100 if base else None

    hoje = ultimo_dia.date()
    from datetime import timedelta as _td

    fim_ano = base_em(hoje.replace(month=1, day=1) - _td(days=1))
    precos = [v for _, v in serie]
    return {"ativo": ativo, "ultimo": ultimo, "data": ultimo_dia, "anterior": serie[-2][1], "dia": var(serie[-2][1]),
            "semana": var(base_em(hoje - _td(days=7))),
            "mes": var(base_em(hoje - _td(days=30))), "ano": var(fim_ano),
            "doze_meses": var(precos[0]) if (hoje - serie[0][0].date()).days >= 330 else None,
            "minima_52s": min(precos), "maxima_52s": max(precos), "pregoes": len(serie)}


def yahoo(ativo: str) -> Cotacao:
    simbolo = YAHOO.get(ativo, ativo)
    try:
        hist = _historico_memo(simbolo, "5d")
    except Exception as e:  # noqa: BLE001
        raise FonteIndisponivel(f"Yahoo indisponível para {simbolo}: {e}") from e
    if hist is None or len(hist) == 0:
        raise FonteIndisponivel(f"Yahoo sem dados para {simbolo}")
    fech = hist["Close"].dropna()
    preco = float(fech.iloc[-1])
    var = (preco / float(fech.iloc[-2]) - 1) * 100 if len(fech) >= 2 else None
    horario = fech.index[-1].to_pydatetime()
    moeda = "BRL" if simbolo.endswith((".SA", "BRL=X")) or simbolo in {"^BVSP", "BRL=X"} else "USD"
    atraso = "pode ter atraso"
    if ativo in PTAX:  # barras diárias de câmbio do Yahoo vêm defasadas/repetidas: o "dia" sai contra a PTAX oficial
        var, atraso = _variacao_contra_ptax(ativo, preco, horario)
    return Cotacao(ativo, NOMES.get(ativo, simbolo), preco, var, moeda, horario, "Yahoo Finance", datetime.now(), atraso)


PTAX = {"USDBRL": "dolar_ptax", "EURBRL": "euro_ptax"}


def _variacao_contra_ptax(ativo: str, preco: float, horario: datetime) -> tuple[float | None, str]:
    """Variação do câmbio de agora contra a PTAX (Banco Central) do último dia útil ANTES da data do dado."""
    try:
        from quiron.servicos.mercado import bcb

        serie = bcb.sgs(PTAX[ativo], 5)
    except Exception:  # noqa: BLE001 — sem PTAX: melhor não mostrar variação do que mostrar a errada
        return None, "pode ter atraso · variação do dia indisponível"
    dia = horario.date()
    anteriores = [p for p in serie.pontos if p.data < dia and p.valor]
    if not anteriores:
        return None, "pode ter atraso · variação do dia indisponível"
    base = anteriores[-1]
    return (preco / base.valor - 1) * 100, f"pode ter atraso · variação contra a PTAX de {base.data:%d/%m}"


def cotacao(ativo: str) -> Cotacao:
    """Escolhe a fonte: watchlist global/índices → Yahoo; ticker da B3 → brapi (Yahoo .SA como reserva)."""
    if ativo in YAHOO or ativo.startswith("^") or "=" in ativo:
        return yahoo(ativo)
    try:
        return brapi(ativo)
    except FonteIndisponivel as erro_brapi:
        try:
            c = yahoo(f"{ativo.upper()}.SA")
            c.ativo = ativo.upper()  # mostra "TRXF11", não o símbolo do Yahoo
            c.nome = c.nome if c.nome != f"{ativo.upper()}.SA" else ativo.upper()
            return c
        except FonteIndisponivel as erro_yahoo:
            dica = ""
            if "401" in str(erro_brapi) or "token" in str(erro_brapi).lower():
                dica = " — sem token, a brapi só libera alguns tickers: crie um token gratuito em brapi.dev e ponha BRAPI_TOKEN no .env"
            raise FonteIndisponivel(f"brapi e Yahoo sem dados para {ativo.upper()}{dica}") from erro_yahoo
