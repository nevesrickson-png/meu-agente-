"""Tributos brasileiros usados no planejamento — todas as tabelas vêm de `config/regras_mercado.yaml`.

IRPF (mensal e anual, com a redução de 2026), imposto mínimo de alta renda, INSS, Simples Nacional (anexos III e V,
fator R) e Lucro Presumido para serviços. Valores em R$; alíquotas em decimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quiron.nucleo import regras


def _r() -> dict[str, Any]:
    return regras.carregar_regras()


# ---------------------------------------------------------------- IRPF
def _tabela(faixas: list[dict], base: float, escala: float = 1.0) -> float:
    for f in faixas:
        if "ate" not in f or base <= f["ate"] * escala:
            return max(0.0, base * f["aliquota"] - f["deduzir"] * escala)
    return 0.0


def irpf_mensal(base: float, com_reducao: bool = True, r: dict | None = None, rendimento: float | None = None) -> float:
    """IR do mês sobre a base (rendimento tributável − INSS − dependentes…), com a redução de 2026 — que a lei calcula
    sobre o RENDIMENTO tributável bruto (sem `rendimento`, usa a própria base)."""
    t = (r or _r())["irpf_tabela_mensal"]
    imposto = _tabela(t["faixas"], base)
    if com_reducao and t.get("reducao_2026"):
        imposto = max(0.0, imposto - _reducao(t["reducao_2026"]["mensal"], base if rendimento is None else rendimento))
    return imposto


def ir_na_fonte(rendimento: float, deducoes: float = 0.0, r: dict | None = None) -> float:
    """IR retido no mês: base = rendimento − o maior entre as deduções legais (INSS, dependentes…) e o desconto
    simplificado mensal; redução de 2026 sobre o rendimento bruto."""
    r = r or _r()
    simplificado = float(r["irpf_tabela_mensal"]["deducoes_anuais"].get("desconto_simplificado_mensal") or 0)
    return irpf_mensal(max(0.0, rendimento - max(deducoes, simplificado)), r=r, rendimento=rendimento)


def irpf_anual(base: float, rendimento_tributavel: float | None = None, com_reducao: bool = True,
               r: dict | None = None) -> float:
    """IR anual (ajuste) sobre a base de cálculo; tabela anual = mensal × 12. A redução de 2026 usa o RENDIMENTO
    tributável (antes das deduções), como na lei."""
    t = (r or _r())["irpf_tabela_mensal"]
    imposto = _tabela(t["faixas"], base, 12)
    if com_reducao and t.get("reducao_2026"):
        imposto = max(0.0, imposto - _reducao(t["reducao_2026"]["anual"], rendimento_tributavel if rendimento_tributavel
                                               is not None else base))
    return imposto


def _reducao(cfg: dict, rendimento: float) -> float:
    if rendimento <= cfg["zera_ate"]:
        return cfg["reducao_maxima"]
    if rendimento <= cfg["faixa_ate"]:
        return max(0.0, cfg["constante"] - cfg["fator"] * rendimento)
    return 0.0


def irpf_minimo_alta_renda(renda_total_anual: float, ir_ja_pago: float, r: dict | None = None) -> float:
    """Imposto mínimo (Lei 15.270/2025): alíquota sobe de 0% em R$ 600 mil a 10% em R$ 1,2 mi; desconta o já pago."""
    c = (r or _r())["irpf_alta_renda"]
    if renda_total_anual <= c["renda_minima_anual"]:
        return 0.0
    frac = min(1.0, (renda_total_anual - c["renda_minima_anual"]) / (c["renda_aliquota_cheia"] - c["renda_minima_anual"]))
    return max(0.0, renda_total_anual * c["aliquota_maxima"] * frac - ir_ja_pago)


# ---------------------------------------------------------------- INSS
def inss_empregado(salario: float, r: dict | None = None) -> float:
    """Contribuição progressiva do empregado (CLT), por faixa, até o teto."""
    faixas = (r or _r())["inss"]["empregado_faixas"]
    total, anterior = 0.0, 0.0
    for f in faixas:
        if salario <= anterior:
            break
        total += (min(salario, f["ate"]) - anterior) * f["aliquota"]
        anterior = f["ate"]
    return total


def inss_teto(r: dict | None = None) -> float:
    return float((r or _r())["inss"]["teto_mensal"])


# ---------------------------------------------------------------- empresa
def simples_aliquota(rbt12: float, anexo: str, r: dict | None = None) -> float:
    """Alíquota efetiva do Simples (anexo 'iii' ou 'v') para a receita bruta de 12 meses."""
    cfg = (r or _r())["simples_nacional"]
    if rbt12 <= 0:
        return 0.0
    if rbt12 > cfg["limite_anual"]:
        raise ValueError("faturamento acima do limite do Simples Nacional")
    for f in cfg[f"anexo_{anexo}"]:
        if rbt12 <= f["ate"]:
            return (rbt12 * f["aliquota"] - f["deduzir"]) / rbt12
    raise ValueError("faixa do Simples não encontrada")


@dataclass
class Presumido:
    irpj: float
    adicional: float
    csll: float
    pis: float
    cofins: float
    iss: float

    @property
    def total(self) -> float:
        return self.irpj + self.adicional + self.csll + self.pis + self.cofins + self.iss


def lucro_presumido(faturamento_anual: float, iss: float | None = None, r: dict | None = None) -> Presumido:
    c = (r or _r())["lucro_presumido"]
    base = faturamento_anual * c["presuncao_servicos"]
    # LC 224/2025: presunção 10% maior só na parcela da receita acima de R$ 5 mi/ano (IRPJ desde 01/2026, CSLL desde 04/2026)
    base += max(0.0, faturamento_anual - c.get("acrescimo_limite_receita_anual", float("inf"))) \
        * c["presuncao_servicos"] * c.get("acrescimo_presuncao_lc224", 0.0)
    return Presumido(base * c["irpj"], max(0.0, base - c["irpj_adicional_acima_anual"]) * c["irpj_adicional"],
                     base * c["csll"], faturamento_anual * c["pis"], faturamento_anual * c["cofins"],
                     faturamento_anual * (c["iss_padrao"] if iss is None else iss))
