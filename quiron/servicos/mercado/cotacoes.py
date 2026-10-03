"""Cotações: B3 pela brapi (token gratuito opcional) e mercado global pelo Yahoo Finance (yfinance).

Dados gratuitos têm atraso (B3 ~15 min); toda cotação traz o horário do próprio dado.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from quiron.servicos.mercado.http import FonteIndisponivel, obter

URL_BRAPI = "https://brapi.dev/api/quote/{ticker}"

# Nomes da watchlist → símbolo no Yahoo. Ativos da B3 sem mapeamento vão para a brapi.
YAHOO = {
    "IBOV": "^BVSP",
    "SMLL": "SMAL11.SA",  # ETF que replica o SMLL (o índice não tem símbolo estável no Yahoo)
    "^GSPC": "^GSPC",
    "^IXIC": "^IXIC",
    "USDBRL": "BRL=X",
    "EURBRL": "EURBRL=X",
    "petroleo_brent": "BZ=F",
    "ouro": "GC=F",
    "minerio_ferro": "TIO=F",
}
NOMES = {
    "IBOV": "Ibovespa", "SMLL": "Small Caps (via SMAL11)", "^GSPC": "S&P 500", "^IXIC": "Nasdaq",
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


def _historico_yahoo(simbolo: str):
    """Isolado para os testes poderem substituir (o yfinance usa a própria conexão)."""
    import yfinance as yf

    return yf.Ticker(simbolo).history(period="5d", interval="1d", auto_adjust=False)


def yahoo(ativo: str) -> Cotacao:
    simbolo = YAHOO.get(ativo, ativo)
    try:
        hist = _historico_yahoo(simbolo)
    except Exception as e:  # noqa: BLE001
        raise FonteIndisponivel(f"Yahoo indisponível para {simbolo}: {e}") from e
    if hist is None or len(hist) == 0:
        raise FonteIndisponivel(f"Yahoo sem dados para {simbolo}")
    fech = hist["Close"].dropna()
    preco = float(fech.iloc[-1])
    var = (preco / float(fech.iloc[-2]) - 1) * 100 if len(fech) >= 2 else None
    horario = fech.index[-1].to_pydatetime()
    moeda = "BRL" if simbolo.endswith((".SA", "BRL=X")) or simbolo in {"^BVSP", "BRL=X"} else "USD"
    return Cotacao(ativo, NOMES.get(ativo, simbolo), preco, var, moeda, horario, "Yahoo Finance", datetime.now(), "pode ter atraso")


def cotacao(ativo: str) -> Cotacao:
    """Escolhe a fonte: watchlist global/índices → Yahoo; ticker da B3 → brapi (Yahoo .SA como reserva)."""
    if ativo in YAHOO or ativo.startswith("^") or "=" in ativo:
        return yahoo(ativo)
    try:
        return brapi(ativo)
    except FonteIndisponivel:
        return yahoo(f"{ativo.upper()}.SA")
