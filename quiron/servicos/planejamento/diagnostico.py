"""Diagnóstico financeiro (CFP): renda líquida, fluxo de caixa, balanço patrimonial, indicadores e objetivos.

Valores mensais em R$ de hoje. Renda líquida estimada pelas tabelas de `config/regras_mercado.yaml`; premissas em
`config/premissas_planejamento.yaml`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quiron.nucleo.config import ler_yaml
from quiron.servicos.planejamento import impostos
from quiron.servicos.planejamento.ficha import Ficha


def premissas() -> dict[str, Any]:
    return ler_yaml("premissas_planejamento") or {}


def taxa_mensal(anual_pct: float) -> float:
    return (1 + anual_pct / 100) ** (1 / 12) - 1


def vf(pv: float, pmt: float, i: float, n: int) -> float:
    """Valor futuro com aportes no fim de cada mês."""
    if i == 0:
        return pv + pmt * n
    return pv * (1 + i) ** n + pmt * ((1 + i) ** n - 1) / i


def pmt_para(alvo: float, pv: float, i: float, n: int) -> float:
    """Aporte mensal para chegar ao alvo em n meses (0 se o que já existe basta)."""
    if n <= 0:
        return max(0.0, alvo - pv)
    falta = alvo - pv * (1 + i) ** n
    if falta <= 0:
        return 0.0
    return falta / n if i == 0 else falta * i / ((1 + i) ** n - 1)


def vp_renda(renda: float, i: float, n: int) -> float:
    """Valor presente de uma renda mensal por n meses (paga no início de cada mês)."""
    if n <= 0:
        return 0.0
    if i == 0:
        return renda * n
    return renda * (1 - (1 + i) ** -n) / i * (1 + i)


def retorno_real(perfil: str, prazo_anos: float | None = None, p: dict | None = None) -> float:
    """% a.a. real pelo perfil; objetivos curtos usam uma carteira mais conservadora."""
    p = p or premissas()
    tab = p["retorno_real_aa"]
    perfil = perfil if perfil in tab else "moderado"
    if prazo_anos is not None and prazo_anos <= 2:
        return tab["conservador"]
    if prazo_anos is not None and prazo_anos <= 5:
        return min(tab[perfil], tab["moderado"])
    return tab[perfil]


# ---------------------------------------------------------------- renda líquida
@dataclass
class Renda:
    bruta: float  # mensal (titular + cônjuge + outras)
    inss: float
    ir: float
    liquida: float  # média mensal (inclui 13º/férias quando houver)
    detalhes: list[tuple[str, float]] = field(default_factory=list)


def renda_liquida(f: Ficha, r: dict | None = None) -> Renda:
    r = r or impostos._r()
    dep = r["irpf_tabela_mensal"]["deducoes_anuais"]["dependente"] / 12 * len(f.dependentes)
    detalhes = []
    bruto, inss = f.renda_mensal_bruta, 0.0
    if f.ocupacao in {"clt", "servidor"}:
        inss = impostos.inss_empregado(bruto, r) if f.contribui_inss else 0.0
    elif f.ocupacao in {"autonomo", "profissional_liberal"} and f.contribui_inss:
        inss = min(bruto, impostos.inss_teto(r)) * r["inss"]["contribuinte_individual"]
    elif f.ocupacao == "empresario" and f.contribui_inss:
        inss = min(f.pro_labore_mensal, impostos.inss_teto(r)) * r["inss"]["pro_labore_retido"]
    fator = 13.33 / 12 if f.tem_13 else 1.0  # 13º e 1/3 de férias (aproximação)
    if f.ocupacao == "empresario":  # lucros isentos; pró-labore tributado na tabela
        ir_trab = impostos.irpf_mensal(max(0.0, f.pro_labore_mensal - inss - dep), r=r)
        ir = impostos.irpf_mensal(max(0.0, f.pro_labore_mensal + f.outras_rendas_mensais - inss - dep), r=r)
    else:
        ir_trab = impostos.irpf_mensal(max(0.0, bruto - inss - dep), r=r)
        ir = impostos.irpf_mensal(max(0.0, bruto + f.outras_rendas_mensais - inss - dep), r=r)
    # o IR das outras rendas (aluguéis) é o acréscimo que elas causam sobre o IR do trabalho
    liquido_titular = (bruto - inss - ir_trab) * fator + f.outras_rendas_mensais - (ir - ir_trab)
    conj = f.renda_conjuge_mensal
    inss_c = impostos.inss_empregado(conj, r) if conj else 0.0
    ir_c = impostos.irpf_mensal(max(0.0, conj - inss_c), r=r) if conj else 0.0
    liquido_conj = (conj - inss_c - ir_c) * (13.33 / 12) if conj else 0.0
    detalhes += [("Titular líquido", liquido_titular)] + ([("Cônjuge líquido (estimado como CLT)", liquido_conj)] if conj else [])
    return Renda(bruto + conj + f.outras_rendas_mensais, inss + inss_c, ir + ir_c, liquido_titular + liquido_conj, detalhes)


# ---------------------------------------------------------------- diagnóstico
@dataclass
class ObjetivoPlano:
    nome: str
    valor: float
    prazo_anos: float
    prioridade: int
    retorno_real: float
    ja_acumulado: float
    aporte_mensal: float


@dataclass
class Diagnostico:
    renda: Renda
    despesas: float
    parcelas: float
    sobra: float  # capacidade de poupança mensal
    taxa_poupanca: float
    aporte_declarado: float
    reserva_meta: float
    reserva_atual: float
    meses_reserva: float
    comprometimento: float
    patrimonio: float
    dividas: float
    patrimonio_liquido: float
    financeiro: float
    anos_independencia: float  # quantos anos o patrimônio financeiro cobre as despesas
    objetivos: list[ObjetivoPlano]
    alertas: list[str]


def diagnosticar(f: Ficha, p: dict | None = None, r: dict | None = None) -> Diagnostico:
    p = p or premissas()
    renda = renda_liquida(f, r)
    parcelas = sum(d.parcela_mensal for d in f.dividas)
    sobra = renda.liquida - f.despesas_mensais - parcelas
    meses_meta = p["reserva_meses"].get(f.ocupacao, 6)
    reserva_meta = meses_meta * (f.despesas_mensais + parcelas)
    reserva_atual = f.liquido
    objetivos = []
    for o in sorted(f.objetivos, key=lambda o: (o.prioridade, o.prazo_anos)):
        rr = retorno_real(f.perfil, o.prazo_anos, p)
        n = max(1, round(o.prazo_anos * 12))
        objetivos.append(ObjetivoPlano(o.nome, o.valor, o.prazo_anos, o.prioridade, rr, o.ja_acumulado,
                                       pmt_para(o.valor, o.ja_acumulado, taxa_mensal(rr), n)))
    alertas = []
    if sobra < 0:
        alertas.append("As despesas e parcelas superam a renda líquida estimada: o orçamento está no vermelho.")
    if f.aporte_mensal > max(0.0, sobra) * 1.15 + 100:
        alertas.append("O aporte declarado é maior que a sobra calculada: confira renda, despesas ou o próprio aporte.")
    caras = [d for d in f.dividas if (d.taxa_am or 0) >= 2.0]
    if caras:
        alertas.append("Dívida cara (≥ 2% ao mês): " + ", ".join(d.nome for d in caras) + ".")
    desp_ano = (f.despesas_mensais + parcelas) * 12
    return Diagnostico(renda, f.despesas_mensais, parcelas, sobra, sobra / renda.liquida if renda.liquida else 0.0,
                       f.aporte_mensal, reserva_meta, reserva_atual,
                       reserva_atual / (f.despesas_mensais + parcelas) if f.despesas_mensais + parcelas else 0.0,
                       parcelas / renda.liquida if renda.liquida else 0.0, f.patrimonio_total, f.dividas_total,
                       f.patrimonio_total - f.dividas_total, f.investimentos, f.investimentos / desp_ano if desp_ano else 0.0,
                       objetivos, alertas)
