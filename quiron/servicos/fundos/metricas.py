"""Métricas de fundos a partir do índice mensal da CVM: rentabilidade por janela, risco, fluxo e pares.

Rentabilidade = razão entre cotas (líquida de taxas, antes do IR) — exatamente como a CVM publica no informe diário.
Risco com retornos mensais (volatilidade, Sharpe e Sortino sobre o CDI, pior queda, beta ao Ibovespa).
Pares = classes da mesma classificação ANBIMA, abertas, não exclusivas e com PL ≥ R$ 10 milhões.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from quiron.servicos.fundos import cvm

PL_MINIMO_PARES = 10_000_000


def date_today() -> date:  # separado para os testes fixarem o "hoje"
    return date.today()


@dataclass
class Janela:
    nome: str
    inicio: str  # data da cota inicial (AAAA-MM-DD)
    fim: str
    retorno: float | None  # decimal
    cdi: float | None
    benchmark: float | None
    cota_inicial: float | None = None
    cota_final: float | None = None

    @property
    def pct_cdi(self) -> float | None:
        if self.retorno is None or not self.cdi:
            return None
        return self.retorno / self.cdi


@dataclass
class Risco:
    meses: int
    vol_aa: float
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    pior_mes: float
    pior_mes_quando: str
    melhor_mes: float
    positivos: float  # fração de meses positivos
    acima_cdi: float  # fração de meses acima do CDI
    beta_ibov: float | None
    correlacao_ibov: float | None


@dataclass
class AnaliseFundo:
    classe: cvm.Classe
    sub: str
    extrato: dict | None
    nome_benchmark: str
    data_final: str
    janelas: list[Janela]
    risco: Risco | None
    pl: float | None
    cotistas: int | None
    cotistas_12m: int | None
    captacao_liquida_12m: float
    pl_12m: float | None
    retornos: pd.Series  # mensais (índice: Period)
    linhas: list[dict]
    percentis: dict[str, tuple[float, int]] = field(default_factory=dict)  # janela → (percentil, nº de pares)
    avisos: list[str] = field(default_factory=list)

    @property
    def nome(self) -> str:
        return self.classe.nome


def benchmark_de(c: cvm.Classe) -> str:
    texto = f"{c.classificacao} {c.anbima}".upper()
    if "AÇÕES" in texto or "ACOES" in texto:
        return "IBOV"
    return "CDI"


def _acum(r: pd.Series) -> float | None:
    r = r.dropna()
    return float((1 + r).prod() - 1) if len(r) else None


def retornos_mensais(linhas: list[dict]) -> pd.Series:
    if len(linhas) < 2:
        return pd.Series(dtype=float)
    idx = pd.PeriodIndex([l["mes"] for l in linhas], freq="M")
    cotas = pd.Series([l["cota"] for l in linhas], index=idx, dtype=float)
    # mês faltando no meio (fundo sem informe) quebra a série: só meses consecutivos contam
    r = cotas / cotas.shift(1) - 1
    consecutivo = pd.Series(idx, index=idx).diff().apply(lambda d: getattr(d, "n", 0) == 1)
    return r[consecutivo].dropna()


def _janela(nome: str, linhas: list[dict], meses: int | None, bench: pd.DataFrame, nome_bench: str,
            ano: bool = False) -> Janela:
    ult = linhas[-1]
    fim = pd.Period(ult["mes"], "M")
    if ano:
        base_mes = pd.Period(f"{fim.year - 1}-12", "M")
    else:
        base_mes = fim - meses
    base = next((l for l in reversed(linhas) if pd.Period(l["mes"], "M") <= base_mes), None)
    if base is None or pd.Period(base["mes"], "M") != base_mes:
        return Janela(nome, "", ult["data"], None, None, None)
    sel = bench[(bench.index > base_mes) & (bench.index <= fim)]
    cdi = _acum(sel["CDI"]) if "CDI" in sel else None
    b = _acum(sel[nome_bench]) if nome_bench in sel else None
    return Janela(nome, base["data"], ult["data"], ult["cota"] / base["cota"] - 1, cdi, b, base["cota"], ult["cota"])


def _risco(r: pd.Series, bench: pd.DataFrame) -> Risco | None:
    r = r.dropna()
    if len(r) < 6:
        return None
    cdi = bench["CDI"].reindex(r.index).fillna(0.0) if "CDI" in bench else pd.Series(0.0, index=r.index)
    exc = r - cdi
    vol = float(r.std(ddof=1) * np.sqrt(12))
    ret_aa = float((1 + r).prod() ** (12 / len(r)) - 1)
    cdi_aa = float((1 + cdi).prod() ** (12 / len(r)) - 1)
    neg = exc[exc < 0]
    down = float(np.sqrt((neg ** 2).sum() / len(exc)) * np.sqrt(12)) if len(neg) else 0.0
    curva = (1 + r).cumprod()
    dd = float((curva / curva.cummax().clip(lower=1.0) - 1).min())  # capital inicial também é pico
    beta = corr = None
    if "IBOV" in bench:
        ib = bench["IBOV"].reindex(r.index)
        ok = ib.notna()
        if ok.sum() >= 12 and ib[ok].var() > 0:
            beta = float(np.cov(r[ok], ib[ok])[0, 1] / ib[ok].var())
            corr = float(np.corrcoef(r[ok], ib[ok])[0, 1])
    return Risco(len(r), vol, (ret_aa - cdi_aa) / vol if vol > 0 else None, (ret_aa - cdi_aa) / down if down > 0 else None,
                 min(0.0, dd), float(r.min()), str(r.idxmin()), float(r.max()), float((r > 0).mean()),
                 float((exc > 0).mean()), beta, corr)


def analisar(cnpj: str, bench: pd.DataFrame, sub: str | None = None, meses_risco: int = 36,
             com_pares: bool = True) -> AnaliseFundo:
    c = cvm.classe(cnpj)
    linhas, sub = cvm.serie_mensal(cnpj, sub)
    if len(linhas) < 2:
        raise cvm.FundoNaoEncontrado(f"{c.nome}: menos de 2 meses de cotas no período baixado")
    nb = benchmark_de(c)
    # janelas terminam no último mês FECHADO (como os materiais das gestoras): o mês corrente incompleto fica fora
    if linhas[-1]["mes"] == f"{date_today():%Y-%m}" and len(linhas) > 2:
        linhas = linhas[:-1]
    janelas = [_janela("No mês", linhas, 1, bench, nb), _janela("No ano", linhas, None, bench, nb, ano=True),
               _janela("12 meses", linhas, 12, bench, nb), _janela("24 meses", linhas, 24, bench, nb),
               _janela("36 meses", linhas, 36, bench, nb), _janela("60 meses", linhas, 60, bench, nb)]
    r = retornos_mensais(linhas)
    risco = _risco(r.tail(meses_risco), bench)
    ult = linhas[-1]
    ref = next((l for l in reversed(linhas) if pd.Period(l["mes"], "M") <= pd.Period(ult["mes"], "M") - 12), None)
    ultimos12 = [l for l in linhas if pd.Period(l["mes"], "M") > pd.Period(ult["mes"], "M") - 12]
    avisos = []
    if sub:
        avisos.append(f"Série da subclasse {sub} (a classe tem subclasses com taxas diferentes).")
    if len(r) < 12:
        avisos.append(f"Só {len(r)} meses de histórico no período baixado.")
    a = AnaliseFundo(c, sub, cvm.extrato(cnpj), nb, ult["data"], janelas, risco, ult["pl"], ult["cotistas"],
                     ref["cotistas"] if ref else None, sum((l["captacao"] or 0) - (l["resgate"] or 0) for l in ultimos12),
                     ref["pl"] if ref else None, r, linhas, avisos=avisos)
    if com_pares and c.anbima:
        a.percentis = percentis(a)
    return a


def percentis(a: AnaliseFundo) -> dict[str, tuple[float, int]]:
    """Percentil do retorno do fundo entre os pares (100 = melhor) em 12 e 36 meses."""
    saida = {}
    pares = {k for k in cvm.pares(a.classe.anbima, a.classe.cnpj)}
    fim = a.linhas[-1]["mes"]
    for nome, meses in (("12 meses", 12), ("36 meses", 36)):
        j = next((x for x in a.janelas if x.nome == nome), None)
        if j is None or j.retorno is None:
            continue
        ini = str(pd.Period(fim, "M") - meses + 1)
        todos = cvm.retornos_mes(ini, fim)
        valores = [v[0] for k, v in todos.items() if k in pares and (v[1] or 0) >= PL_MINIMO_PARES]
        if len(valores) >= 5:
            saida[nome] = (100.0 * sum(1 for v in valores if v < j.retorno) / len(valores), len(valores))
    return saida


def acumulado_comum(analises: list[AnaliseFundo]) -> tuple[list[str], dict[str, list[float]]]:
    """R$ 100 aplicados no início do período comum a todos (para o gráfico)."""
    inicio = max(a.retornos.index.min() for a in analises if len(a.retornos))
    fim = min(a.retornos.index.max() for a in analises if len(a.retornos))
    idx = pd.period_range(inicio, fim, freq="M")
    saida = {}
    for a in analises:
        r = a.retornos.reindex(idx).fillna(0.0)
        saida[a.nome] = [100.0] + list(100 * (1 + r).cumprod())
    rot = [str(inicio - 1)] + [str(p) for p in idx]
    return rot, saida


