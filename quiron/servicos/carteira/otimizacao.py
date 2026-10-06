"""Otimização por classe (média-variância) dentro das bandas do perfil — referência, não verdade.

- Retornos esperados: `config/premissas_carteira.yaml` (CDI do Focus, taxas do Tesouro do dia, prêmios declarados).
- Covariância: 60 meses das proxies das classes, com encolhimento de 20% para a diagonal (estabilidade).
- Resolve com scipy (SLSQP): máximo índice de Sharpe (sobre o CDI), mínima variância e a fronteira eficiente.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from quiron.servicos.carteira.modelo import CLASSES, ORDEM, perfis, premissas


def _pc(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + "%"


@dataclass
class Mercado:
    cdi_esperado: float  # % a.a. (próximos 12 meses)
    pre_3a: float  # % a.a.
    real_7a: float  # % a.a. acima do IPCA
    ipca_esperado: float  # % a.a.
    fontes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def mercado_atual() -> Mercado:
    """Taxas de hoje para as premissas: Focus (Selic e IPCA) e Tesouro (prefixado ~3a, IPCA+ ~7a)."""
    from datetime import date

    from quiron.servicos.mercado import bcb, tesouro

    fontes, avisos = [], []
    hoje = date.today()
    try:
        selic = bcb.sgs("selic_meta", 1).ultimo.valor
        f1 = bcb.focus("selic", hoje.year).mediana
        f2 = bcb.focus("selic", hoje.year + 1).mediana
        frac = (12 - hoje.month) / 12
        cdi = (selic + f1) / 2 * frac + (f1 + f2) / 2 * (1 - frac) - 0.10
        fontes.append(f"📊 Banco Central — Selic {_pc(selic)} e Focus Selic {hoje.year}: {_pc(f1)}, {hoje.year + 1}: {_pc(f2)}")
    except Exception as e:  # noqa: BLE001
        cdi = 12.0
        avisos.append(f"Selic/Focus indisponível ({type(e).__name__}): CDI esperado de 12% a.a. (premissa manual).")
    try:
        ipca = bcb.focus("ipca", hoje.year + 1).mediana
        fontes.append(f"📊 Banco Central (Focus) — IPCA {hoje.year + 1}: {_pc(ipca)}")
    except Exception:  # noqa: BLE001
        ipca = 4.5
        avisos.append("Focus IPCA indisponível: 4,5% a.a. (premissa manual).")
    pre, real = cdi + 1.0, 6.5
    try:
        tab = tesouro.titulos_atuais()

        def mais_proximo(chave: str, anos: float) -> float:
            ts = [t for t in tesouro.por_tipo(tab, chave) if t.taxa_compra]
            return min(ts, key=lambda t: abs((t.vencimento - tab.data_base).days - anos * 365.25)).taxa_compra

        pre, real = mais_proximo("prefixado", 3), mais_proximo("ipca_mais", 7)
        fontes.append(f"📊 Tesouro Transparente — prefixado ~3 anos {_pc(pre)}, IPCA+ ~7 anos {_pc(real)} ({tab.data_base:%d/%m/%Y})")
    except Exception as e:  # noqa: BLE001
        avisos.append(f"Tesouro indisponível ({type(e).__name__}): prefixado = CDI + 1 p.p. e juro real 6,5% (premissas).")
    return Mercado(cdi, pre, real, ipca, fontes, avisos)


def retornos_esperados(m: Mercado) -> dict[str, float]:
    """% a.a. por classe, pelas premissas declaradas."""
    saida = {}
    for classe, p in premissas()["retorno_esperado"].items():
        forma = p.get("forma")
        if forma == "cdi":
            saida[classe] = m.cdi_esperado + float(p.get("acima", 0))
        elif forma == "tesouro_prefixado":
            saida[classe] = m.pre_3a
        elif forma == "tesouro_ipca":
            saida[classe] = ((1 + m.real_7a / 100) * (1 + m.ipca_esperado / 100) - 1) * 100
        else:
            saida[classe] = float(p.get("valor", m.cdi_esperado))
    return saida


def covariancia(df: pd.DataFrame, classes: list[str], meses: int = 60, encolher: float = 0.2) -> np.ndarray:
    janela = df.tail(meses)
    # proxy que não veio (Yahoo/Tesouro fora do ar) usa o CDI, como em risco.serie_posicao — em vez de KeyError
    sub = pd.DataFrame({i: janela[CLASSES[c]["proxy"]] if CLASSES[c]["proxy"] in janela else janela["CDI"]
                        for i, c in enumerate(classes)}).fillna(janela["CDI"].mean())
    cov = np.cov(sub.values.T, ddof=1) * 12
    return (1 - encolher) * cov + encolher * np.diag(np.diag(cov))


@dataclass
class Carteiras:
    classes: list[str]
    mu: np.ndarray  # decimal a.a.
    cov: np.ndarray
    max_sharpe: np.ndarray
    min_var: np.ndarray
    fronteira: list[tuple[float, float]]  # (vol, retorno) decimais
    cdi: float

    def stats(self, w: np.ndarray) -> tuple[float, float, float]:
        ret = float(w @ self.mu)
        vol = float(np.sqrt(w @ self.cov @ w))
        return ret, vol, (ret - self.cdi) / vol if vol > 0 else 0.0

    def pesos(self, w: np.ndarray) -> dict[str, float]:
        return {c: float(x) for c, x in zip(self.classes, w)}


def otimizar(df: pd.DataFrame, perfil: str, mercado: Mercado, pontos: int = 15) -> Carteiras:
    bandas = perfis()[perfil]["classes"]
    classes = [c for c in ORDEM if c in bandas and bandas[c][2] > 0]
    limites = [(bandas[c][0] / 100, bandas[c][2] / 100) for c in classes]
    er = retornos_esperados(mercado)
    mu = np.array([er[c] / 100 for c in classes])
    cov = covariancia(df, classes)
    cdi = mercado.cdi_esperado / 100
    soma1 = {"type": "eq", "fun": lambda w: w.sum() - 1}
    w0 = np.array([bandas[c][1] / 100 for c in classes])
    w0 = w0 / w0.sum()

    def resolver(objetivo, extras=()) -> np.ndarray:
        r = minimize(objetivo, w0, method="SLSQP", bounds=limites, constraints=[soma1, *extras],
                     options={"maxiter": 500, "ftol": 1e-10})
        return np.clip(r.x, 0, 1) / np.clip(r.x, 0, 1).sum()

    var = lambda w: float(w @ cov @ w)  # noqa: E731
    min_var = resolver(var)
    max_sharpe = resolver(lambda w: -((w @ mu - cdi) / np.sqrt(w @ cov @ w)))
    r_min = float(min_var @ mu)
    r_max = float(resolver(lambda w: -(w @ mu)) @ mu)
    fronteira = []
    for alvo in np.linspace(r_min, r_max, pontos):
        w = resolver(var, ({"type": "eq", "fun": lambda w, a=alvo: w @ mu - a},))
        fronteira.append((float(np.sqrt(w @ cov @ w)), float(w @ mu)))
    return Carteiras(classes, mu, cov, max_sharpe, min_var, fronteira, cdi)
