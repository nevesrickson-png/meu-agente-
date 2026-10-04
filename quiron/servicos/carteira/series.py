"""Séries históricas MENSAIS de retorno (decimal) por proxy de classe e por ticker — base de risco, stress e backtest.

Proxies (declarados no relatório):
- CDI: SGS 4391 (CDI acumulado no mês) · IPCA: SGS 433.
- PRE3 / IPCA7: índices sintéticos de duration constante a partir do histórico de taxas do Tesouro (título com prazo
  mais próximo de 3 anos / 7 anos): retorno ≈ carregamento − duration modificada × variação da taxa (+ IPCA no IPCA+).
- IBOV (^BVSP), SPX_BRL (^GSPC × dólar), BTC_BRL (BTC-USD × dólar), dólar (BRL=X): Yahoo, preços ajustados.
- FII: cesta igual de FIIs grandes (HGLG11, KNRI11, XPML11, MXRF11, HGRU11) · MULTI: 70% CDI + 30% Ibovespa.
Mês corrente (incompleto) fica de fora.
"""

from __future__ import annotations

import logging
import pickle
import time
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from quiron.nucleo.config import pasta_dados

CESTA_FII = ["HGLG11", "KNRI11", "XPML11", "MXRF11", "HGRU11"]
TTL = 12 * 3600


@dataclass
class Series:
    retornos: pd.DataFrame  # índice: Period mensal; colunas: proxies e tickers
    fontes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _cache(nome: str, func, ttl: int = TTL):
    """Cache em disco (dados/cache_series) — séries longas não são baixadas a cada análise."""
    pasta = pasta_dados() / "cache_series"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{nome.replace('^', '_').replace('=', '_')}.pkl"
    if arq.exists() and time.time() - arq.stat().st_mtime < ttl:
        try:
            return pickle.loads(arq.read_bytes())
        except Exception:  # noqa: BLE001
            pass
    valor = func()
    arq.write_bytes(pickle.dumps(valor))
    return valor


def _mes_fechado(serie: pd.Series) -> pd.Series:
    atual = pd.Period(date.today(), "M")
    return serie[serie.index < atual].sort_index()


def bcb_mensal(codigo: int, inicio: date = date(2006, 1, 1)) -> tuple[pd.Series, str]:
    from quiron.servicos.mercado import bcb

    def baixar():
        pontos, fonte = bcb.sgs_periodo(codigo, inicio)
        s = pd.Series({pd.Period(p.data, "M"): p.valor / 100 for p in pontos})
        return s.groupby(level=0).last(), fonte

    s, fonte = _cache(f"sgs_{codigo}", baixar)
    return _mes_fechado(s), fonte


CORRECOES: dict[str, int] = {}  # símbolo → meses descartados por erro de dado (desdobramento não ajustado etc.)


def yahoo_mensal(simbolo: str, limite: float | None = 0.6) -> pd.Series:
    """Retorno mensal com preço AJUSTADO (inclui dividendos/rendimentos — importante para FIIs).
    Variação mensal acima de `limite` (60%) fora de cripto é tratada como erro de dado e descartada."""
    from quiron.servicos.mercado import cotacoes

    def baixar():
        h = cotacoes._historico_yahoo(simbolo, "max")  # noqa: SLF001
        if h is None or len(h) == 0:
            raise ValueError(f"Yahoo sem histórico para {simbolo}")
        col = "Adj Close" if "Adj Close" in h.columns else "Close"
        preco = h[col].dropna()
        preco.index = pd.to_datetime(preco.index).tz_localize(None) if preco.index.tz is not None else pd.to_datetime(preco.index)
        mensal = preco.resample("ME").last().dropna()
        mensal.index = mensal.index.to_period("M")
        return mensal.pct_change().dropna()

    serie = _mes_fechado(_cache(f"yahoo_{simbolo}", baixar))
    if limite is not None:
        ruins = serie.abs() > limite
        if ruins.any():
            CORRECOES[simbolo] = int(ruins.sum())
            serie = serie[~ruins]
    return serie


def tesouro_sintetico(chave: str, prazo_anos: float, ipca: pd.Series | None = None) -> tuple[pd.Series, str]:
    """Índice de duration constante a partir das taxas do Tesouro (ver docstring do módulo)."""
    from quiron.servicos.mercado import tesouro

    def baixar():
        historico, fonte = tesouro.historico_taxas(chave)
        por_mes: dict[pd.Period, tuple[date, list[tuple[date, float]]]] = {}
        for base, venc, taxa in historico:
            mes = pd.Period(base, "M")
            if mes not in por_mes or base > por_mes[mes][0]:
                por_mes[mes] = (base, [])
            if base == por_mes[mes][0]:
                por_mes[mes][1].append((venc, taxa))
        taxas = {}
        for mes, (base, titulos) in por_mes.items():
            alvo = prazo_anos * 365.25
            venc, taxa = min(titulos, key=lambda t: abs((t[0] - base).days - alvo))
            taxas[mes] = taxa / 100
        return pd.Series(taxas).sort_index(), fonte

    y, fonte = _cache(f"tesouro_{chave}_{prazo_anos}", baixar)
    dmod = prazo_anos / (1 + y.shift(1))
    real = (1 + y.shift(1)) ** (1 / 12) - 1 - dmod * (y - y.shift(1))
    if ipca is not None:
        real = (1 + real) * (1 + ipca.reindex(real.index).fillna(0)) - 1
    return _mes_fechado(real.dropna()), fonte


def carregar(tickers: list[str] | None = None, inicio: str = "2007-01") -> Series:
    """DataFrame mensal com as proxies das classes (+ tickers da carteira, se houver histórico)."""
    fontes, avisos, colunas = [], [], {}
    cdi, f_cdi = bcb_mensal(4391)
    ipca, f_ipca = bcb_mensal(433)
    colunas["CDI"], colunas["IPCA"] = cdi, ipca
    fontes += [f"📊 {f_cdi} — CDI mensal", f"📊 {f_ipca} — IPCA mensal"]
    for nome, chave, prazo, com_ipca in (("PRE3", "prefixado", 3.0, False), ("IPCA7", "ipca_mais", 7.0, True)):
        try:
            colunas[nome], f = tesouro_sintetico(chave, prazo, ipca if com_ipca else None)
            fontes.append(f"📊 {f} — índice sintético {nome} (taxas históricas do Tesouro)")
        except Exception as e:  # noqa: BLE001
            avisos.append(f"Índice {nome} indisponível ({type(e).__name__}).")
    yahoo = {"IBOV": "^BVSP", "USD": "BRL=X", "SPX": "^GSPC", "BTC": "BTC-USD"}
    CORRECOES.clear()
    for nome, simbolo in yahoo.items():
        try:
            colunas[nome] = yahoo_mensal(simbolo, None if nome == "BTC" else 0.6)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"{nome} ({simbolo}) indisponível no Yahoo ({type(e).__name__}).")
    fontes.append("📊 Yahoo Finance — Ibovespa, S&P 500, dólar, bitcoin e ativos da B3 (preços ajustados)")
    df = pd.DataFrame(colunas)
    if {"SPX", "USD"} <= set(df):
        df["SPX_BRL"] = (1 + df["SPX"]) * (1 + df["USD"]) - 1
    if {"BTC", "USD"} <= set(df):
        df["BTC_BRL"] = (1 + df["BTC"]) * (1 + df["USD"]) - 1
    if {"CDI", "IBOV"} <= set(df):
        df["MULTI"] = 0.7 * df["CDI"] + 0.3 * df["IBOV"]
    cesta = {}
    for t in CESTA_FII:
        try:
            cesta[t] = yahoo_mensal(f"{t}.SA")
        except Exception:  # noqa: BLE001
            pass
    if cesta:
        df["FII"] = pd.DataFrame(cesta).mean(axis=1, skipna=True)
    for t in tickers or []:
        if t in df:
            continue
        try:
            df[t] = yahoo_mensal(f"{t}.SA")
        except Exception as e:  # noqa: BLE001
            logging.info("sem histórico de %s: %s", t, e)
            avisos.append(f"{t}: sem histórico no Yahoo — usei a proxy da classe.")
    df = df[df.index >= pd.Period(inicio, "M")]
    if CORRECOES:
        avisos.append("Meses descartados por erro no histórico do Yahoo (variação > 60%, ex.: desdobramento não ajustado): "
                      + ", ".join(f"{k.replace('.SA', '')} ({v})" for k, v in CORRECOES.items()))
    return Series(df, fontes, avisos)
