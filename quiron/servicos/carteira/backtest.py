"""Backtest mensal de alocações por classe (rebalanceamento mensal, sem custos nem impostos) contra CDI e Ibovespa."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quiron.servicos.carteira import risco
from quiron.servicos.carteira.modelo import CLASSES


@dataclass
class Resultado:
    nome: str
    retornos: pd.Series
    metricas: risco.Metricas

    @property
    def acumulado(self) -> pd.Series:
        return (1 + self.retornos).cumprod()


def rodar(df: pd.DataFrame, alocacoes: dict[str, dict[str, float]], meses: int = 120) -> list[Resultado]:
    janela = df.tail(meses)
    cdi = janela["CDI"]
    ibov = janela.get("IBOV")
    saida = []
    for nome, pesos in alocacoes.items():
        r = pd.Series(0.0, index=janela.index)
        for classe, w in pesos.items():
            if w <= 0:
                continue
            proxy = CLASSES[classe]["proxy"]
            r = r + w * (janela[proxy] if proxy in janela else cdi).fillna(cdi)
        saida.append(Resultado(nome, r, risco.metricas(r, cdi, ibov)))
    for nome, col in (("CDI", "CDI"), ("Ibovespa", "IBOV")):
        if col in janela:
            s = janela[col].fillna(0.0)
            saida.append(Resultado(nome, s, risco.metricas(s, cdi, ibov)))
    return saida
