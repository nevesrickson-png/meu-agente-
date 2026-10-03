"""Calculadoras financeiras básicas (usadas no Terminal e, na Fase 7, também pelo agente via `CALC`).

Regra do projeto: número sempre calculado em Python, com a memória de cálculo visível.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.nucleo import regras


@dataclass
class Resultado:
    titulo: str
    linhas: list[tuple[str, str]]  # (rótulo, valor formatado)
    memoria: list[str] = field(default_factory=list)  # como foi calculado
    avisos: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"titulo": self.titulo, "linhas": self.linhas, "memoria": self.memoria, "avisos": self.avisos}


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",") + "%"


def taxa_mensal(taxa_aa: float) -> float:
    return ((1 + taxa_aa / 100) ** (1 / 12) - 1) * 100


def taxa_anual(taxa_am: float) -> float:
    return ((1 + taxa_am / 100) ** 12 - 1) * 100


def juros_compostos(valor_inicial: float, aporte_mensal: float, taxa_aa: float, anos: float) -> Resultado:
    meses = round(anos * 12)
    i = taxa_mensal(taxa_aa) / 100
    fator = (1 + i) ** meses
    vf_inicial = valor_inicial * fator
    vf_aportes = aporte_mensal * ((fator - 1) / i) if i else aporte_mensal * meses  # aporte no fim de cada mês
    total = vf_inicial + vf_aportes
    investido = valor_inicial + aporte_mensal * meses
    return Resultado(
        "Juros compostos",
        [("Valor final", _brl(total)), ("Total investido", _brl(investido)), ("Juros ganhos", _brl(total - investido))],
        [f"Taxa mensal equivalente: {_pct(i * 100, 4)} a.m. = (1 + {_pct(taxa_aa)})^(1/12) − 1",
         f"{meses} meses; aportes no fim de cada mês",
         f"VF = VP·(1+i)^n + PMT·((1+i)^n − 1)/i"],
    )


def equivalencia(taxa: float, periodo: str = "aa") -> Resultado:
    """Converte taxa ao ano ↔ ao mês ↔ ao dia útil (252)."""
    aa = taxa if periodo == "aa" else taxa_anual(taxa)
    am = taxa_mensal(aa)
    ad = ((1 + aa / 100) ** (1 / 252) - 1) * 100
    return Resultado(
        "Equivalência de taxas",
        [("Ao ano", _pct(aa, 4)), ("Ao mês", _pct(am, 4)), ("Ao dia útil (252)", _pct(ad, 6))],
        ["Capitalização composta: (1 + taxa)^(período novo / período original) − 1"],
    )


def aliquota_ir(dias: int) -> tuple[float, list[str]]:
    """Alíquota da tabela regressiva de renda fixa (config/regras_mercado.yaml)."""
    r = regras.carregar_regras()
    tabela = r["renda_fixa"]["ir_tabela_regressiva"]
    avisos = [a for a in regras.avisos(r) if a.startswith("renda_fixa")]
    for faixa in tabela:
        if "ate_dias" in faixa and dias <= faixa["ate_dias"]:
            return float(faixa["aliquota"]), avisos
    return float(tabela[-1]["aliquota"]), avisos


def cdb_x_isento(taxa_isenta_aa: float, taxa_cdb_aa: float, dias: int) -> Resultado:
    """Compara uma aplicação isenta (LCI/LCA) com um CDB tributado no mesmo prazo."""
    aliq, avisos = aliquota_ir(dias)
    cdb_liquido = taxa_cdb_aa * (1 - aliq)  # aproximação usual sobre a taxa anual
    cdb_equivalente = taxa_isenta_aa / (1 - aliq)
    melhor = "Isento (LCI/LCA)" if taxa_isenta_aa > cdb_liquido else "CDB" if cdb_liquido > taxa_isenta_aa else "Empate"
    return Resultado(
        "CDB × LCI/LCA",
        [("Alíquota de IR no prazo", _pct(aliq * 100, 1)), ("CDB líquido", _pct(cdb_liquido) + " a.a."),
         ("CDB precisa render (bruto) para empatar", _pct(cdb_equivalente) + " a.a."), ("Melhor no prazo", melhor)],
        [f"{dias} dias → alíquota {_pct(aliq * 100, 1)} (tabela regressiva)",
         "CDB líquido ≈ taxa bruta × (1 − alíquota); equivalente = taxa isenta ÷ (1 − alíquota)",
         "Aproximação sobre a taxa anual; não considera FGC, liquidez nem risco do emissor"],
        avisos,
    )


def taxa_real(nominal_aa: float, inflacao_aa: float) -> Resultado:
    real = ((1 + nominal_aa / 100) / (1 + inflacao_aa / 100) - 1) * 100
    return Resultado(
        "Taxa real (Fisher)",
        [("Taxa real", _pct(real) + " a.a."), ("Diferença simples (aproximação)", _pct(nominal_aa - inflacao_aa) + " a.a.")],
        ["(1 + nominal) ÷ (1 + inflação) − 1"],
    )


def percentual_cdi(percentual: float, cdi_aa: float) -> Resultado:
    """Taxa anual de uma aplicação que paga X% do CDI (base 252)."""
    diario_cdi = (1 + cdi_aa / 100) ** (1 / 252) - 1
    diario = diario_cdi * percentual / 100
    aa = ((1 + diario) ** 252 - 1) * 100
    return Resultado(
        f"{_pct(percentual, 0)} do CDI",
        [("Taxa equivalente", _pct(aa) + " a.a."), ("CDI usado", _pct(cdi_aa) + " a.a.")],
        ["CDI diário = (1 + CDI)^(1/252) − 1; aplica o percentual ao diário e capitaliza 252 dias"],
    )


CALCULADORAS = {
    "juros_compostos": juros_compostos,
    "equivalencia": equivalencia,
    "cdb_x_isento": cdb_x_isento,
    "taxa_real": taxa_real,
    "percentual_cdi": percentual_cdi,
}
