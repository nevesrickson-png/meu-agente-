"""Stress test: cenários hipotéticos (choques em fatores) e históricos (episódios reais) — `config/cenarios_stress.yaml`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import yaml

from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos.carteira import risco
from quiron.servicos.carteira.modelo import Carteira


def _n(v: float, casas: int = 2, sinal: bool = False) -> str:
    return (f"{v:+.{casas}f}" if sinal else f"{v:.{casas}f}").replace(".", ",")


def cenarios() -> dict:
    return yaml.safe_load((PASTA_CONFIG / "cenarios_stress.yaml").read_text(encoding="utf-8"))


@dataclass
class ImpactoPosicao:
    nome: str
    classe: str
    valor: float
    impacto: float  # R$
    regra: str  # como foi calculado
    em_12_meses: float = 0.0  # efeito adicional ao longo de 12 meses (carregamento de pós-fixados)


@dataclass
class Resultado:
    nome: str
    descricao: str
    impacto: float  # R$ (instantâneo)
    impacto_pct: float
    em_12_meses: float
    posicoes: list[ImpactoPosicao] = field(default_factory=list)


def hipotetico(carteira: Carteira, chave: str, cfg: dict, betas: dict[int, float], taxa_pre: float = 13.5,
               taxa_real: float = 7.0, hoje: date | None = None) -> Resultado:
    ch = {k: float(v) for k, v in cfg["choques"].items()}
    itens = []
    for i, p in enumerate(carteira.posicoes):
        extra = 0.0
        if p.classe == "prefixado":
            dmod = p.duration(hoje) / (1 + taxa_pre / 100)
            imp, regra = -dmod * ch.get("juros_pre", 0) / 100, f"−{_n(dmod)} (dur. mod.) × {_n(ch.get('juros_pre', 0), 1, True)} p.p."
        elif p.classe == "inflacao":
            dmod = p.duration(hoje) / (1 + taxa_real / 100)
            imp, regra = -dmod * ch.get("juro_real", 0) / 100, f"−{_n(dmod)} (dur. mod.) × {_n(ch.get('juro_real', 0), 1, True)} p.p. de juro real"
        elif p.classe == "pos_fixado":
            imp, regra = 0.0, "pós-fixado: sem perda no instante"
            extra = p.valor * ch.get("selic", 0) / 100  # passa a render Selic diferente por 12 meses
        elif p.classe == "acoes":
            b = betas.get(i, 1.0)
            imp, regra = b * ch.get("bolsa", 0) / 100, f"beta {_n(b)} × bolsa {_n(ch.get('bolsa', 0), 0, True)}%"
        elif p.classe == "fii":
            imp, regra = ch.get("fii", 0) / 100, f"FIIs {_n(ch.get('fii', 0), 0, True)}%"
        elif p.classe == "multimercado":
            imp, regra = ch.get("multimercado", 0) / 100, f"multimercados {_n(ch.get('multimercado', 0), 0, True)}%"
        elif p.classe == "internacional":
            imp = (1 + ch.get("spx", 0) / 100) * (1 + ch.get("dolar", 0) / 100) - 1
            regra = f"exterior {_n(ch.get('spx', 0), 0, True)}% com dólar {_n(ch.get('dolar', 0), 0, True)}%"
        else:  # cripto
            imp = (1 + ch.get("cripto", 0) / 100) * (1 + ch.get("dolar", 0) / 100) - 1
            regra = f"cripto {_n(ch.get('cripto', 0), 0, True)}% com dólar {_n(ch.get('dolar', 0), 0, True)}%"
        itens.append(ImpactoPosicao(p.nome, p.classe, p.valor, p.valor * imp, regra, extra))
    total = sum(x.impacto for x in itens)
    return Resultado(cfg["nome"], cfg.get("descricao", ""), total, total / (carteira.total or 1),
                     sum(x.em_12_meses for x in itens), itens)


def historico(carteira: Carteira, df: pd.DataFrame, nome: str, inicio: str, fim: str) -> Resultado | None:
    """Retorno acumulado de cada posição no episódio (ticker se existia; senão, a proxy da classe)."""
    ini, fi = pd.Period(inicio, "M"), pd.Period(fim, "M")
    janela = df[(df.index >= ini) & (df.index <= fi)]
    if janela.empty:
        return None
    itens = []
    for p in carteira.posicoes:
        s, origem = risco.serie_posicao(p, janela)
        acum = float((1 + s.fillna(0)).prod() - 1)
        itens.append(ImpactoPosicao(p.nome, p.classe, p.valor, p.valor * acum, f"{origem} no período"))
    total = sum(x.impacto for x in itens)
    return Resultado(nome, f"{inicio} a {fim}", total, total / (carteira.total or 1), 0.0, itens)


def rodar(carteira: Carteira, df: pd.DataFrame, taxa_pre: float, taxa_real: float,
          hoje: date | None = None) -> tuple[list[Resultado], list[Resultado]]:
    cfg = cenarios()
    b = risco.betas(carteira, df)
    hip = [hipotetico(carteira, k, v, b, taxa_pre, taxa_real, hoje) for k, v in cfg["hipoteticos"].items()]
    hist = [r for c in cfg["historicos"] if (r := historico(carteira, df, c["nome"], c["inicio"], c["fim"]))]
    return hip, hist
