"""Risco da carteira com séries mensais: volatilidade, VaR/CVaR, drawdown, beta, contribuição ao risco, duration.

Cada posição usa o histórico do próprio ticker (se houver ≥ 24 meses); senão, a proxy da classe. Meses em que o
ticker ainda não existia são preenchidos com a proxy. Janela padrão: 60 meses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from quiron.servicos.carteira.modelo import CLASSES, ORDEM, Carteira, Posicao

Z95 = 1.6449


def serie_posicao(p: Posicao, df: pd.DataFrame, historia: pd.DataFrame | None = None) -> tuple[pd.Series, str]:
    """Série do próprio ativo se ele tem ≥ 24 meses de histórico (contados em `historia`, ou em `df`), senão a proxy."""
    proxy = CLASSES[p.classe]["proxy"]
    base = df[proxy] if proxy in df else df["CDI"]
    h = df if historia is None else historia
    if p.ticker and p.ticker in df and p.ticker in h and h[p.ticker].count() >= 24:
        return df[p.ticker].combine_first(base), p.ticker
    return base, proxy


def matriz_posicoes(carteira: Carteira, df: pd.DataFrame, meses: int = 60) -> tuple[pd.DataFrame, dict[str, str]]:
    janela = df.tail(meses)
    colunas, origem = {}, {}
    for i, p in enumerate(carteira.posicoes):
        s, o = serie_posicao(p, janela)
        colunas[i], origem[p.nome] = s, o
    return pd.DataFrame(colunas).fillna(0.0), origem


def pesos(carteira: Carteira) -> np.ndarray:
    total = carteira.total or 1
    return np.array([p.valor / total for p in carteira.posicoes])


@dataclass
class Metricas:
    retorno_aa: float
    vol_aa: float
    sharpe: float | None
    max_drawdown: float
    inicio_dd: str
    fundo_dd: str
    var95_mes: float  # histórico (perda no pior 5% dos meses), positivo = perda
    var95_param: float
    cvar95_mes: float
    pior_mes: float
    pior_mes_quando: str
    melhor_mes: float
    meses_negativos: float
    beta_ibov: float | None
    meses: int
    extras: dict = field(default_factory=dict)


def metricas(r: pd.Series, cdi: pd.Series | None = None, ibov: pd.Series | None = None) -> Metricas:
    r = r.dropna()
    n = len(r)
    if not n:
        raise ValueError("série de retornos vazia")
    acumulado = float((1 + r).prod())
    ret_aa = acumulado ** (12 / n) - 1 if n else 0.0
    vol = float(r.std(ddof=1) * np.sqrt(12)) if n > 1 else 0.0
    sharpe = None
    if cdi is not None and vol > 0:
        cdi_aa = float((1 + cdi.reindex(r.index).fillna(0)).prod()) ** (12 / n) - 1
        sharpe = (ret_aa - cdi_aa) / vol
    curva = (1 + r).cumprod()
    pico = curva.cummax().clip(lower=1.0)  # o capital inicial (1,0) também é pico: queda logo no 1º mês conta
    dd = curva / pico - 1
    fundo = dd.idxmin()
    inicio = curva[:fundo].idxmax() if curva[:fundo].max() >= 1.0 else r.index[0]
    q = float(np.quantile(r, 0.05))
    beta = None
    if ibov is not None:
        b = ibov.reindex(r.index)
        ok = b.notna()
        if ok.sum() > 12 and b[ok].var() > 0:
            beta = float(np.cov(r[ok], b[ok])[0, 1] / b[ok].var())
    return Metricas(ret_aa, vol, sharpe, float(dd.min()), str(inicio), str(fundo), -q,
                    -(float(r.mean()) - Z95 * float(r.std(ddof=1))), -float(r[r <= q].mean()), float(r.min()),
                    str(r.idxmin()), float(r.max()), float((r < 0).mean()), beta, n)


def retornos_carteira(carteira: Carteira, df: pd.DataFrame, meses: int = 60) -> tuple[pd.Series, dict[str, str]]:
    m, origem = matriz_posicoes(carteira, df, meses)
    return pd.Series(m.values @ pesos(carteira), index=m.index), origem


def contribuicao_por_classe(carteira: Carteira, df: pd.DataFrame, meses: int = 60) -> dict[str, float]:
    """Parcela do risco (variância) total vinda de cada classe: wᵢ·cov(rᵢ, r_carteira) / var(r_carteira)."""
    m, _ = matriz_posicoes(carteira, df, meses)
    w = pesos(carteira)
    port = m.values @ w
    var = float(np.var(port, ddof=1))
    contrib = {c: 0.0 for c in ORDEM}
    if var <= 0:
        return contrib
    for i, p in enumerate(carteira.posicoes):
        contrib[p.classe] += float(w[i]) * float(np.cov(m[i].values, port, ddof=1)[0, 1]) / var
    return contrib



def betas(carteira: Carteira, df: pd.DataFrame, meses: int = 60) -> dict[int, float]:
    """Beta de cada posição de ações em relação ao Ibovespa (1,0 se não houver histórico)."""
    saida = {}
    janela = df.tail(meses)
    for i, p in enumerate(carteira.posicoes):
        if p.classe != "acoes":
            continue
        s, _ = serie_posicao(p, janela)
        ib = janela["IBOV"] if "IBOV" in janela else None
        if ib is None or s.count() < 24:
            saida[i] = 1.0
            continue
        ok = s.notna() & ib.notna()
        saida[i] = float(np.cov(s[ok], ib[ok])[0, 1] / ib[ok].var()) if ib[ok].var() > 0 else 1.0
    return saida


def duration_carteira(carteira: Carteira, hoje: date | None = None) -> dict[str, float]:
    """Duration média (anos) da renda fixa com risco de taxa e da carteira toda."""
    total = carteira.total or 1
    rf = [p for p in carteira.posicoes if p.classe in {"prefixado", "inflacao"}]
    soma_rf = sum(p.valor for p in rf)
    dur_rf = sum(p.valor * p.duration(hoje) for p in rf) / soma_rf if soma_rf else 0.0
    return {"renda_fixa_taxa": dur_rf, "carteira": sum(p.valor * p.duration(hoje) for p in rf) / total,
            "peso_renda_fixa_taxa": soma_rf / total}
