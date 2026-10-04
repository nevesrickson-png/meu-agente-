"""Tributário PF: declaração completa × simplificada, PGBL ideal e imposto mínimo de alta renda (titular).

Rendimento tributável anual = renda bruta × 12 (+ outras rendas); o 13º tem tributação exclusiva e fica fora do
ajuste. Empresário: as retiradas como lucro são isentas na PF — o módulo PF × PJ cuida do regime da empresa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.servicos.planejamento import impostos
from quiron.servicos.planejamento.ficha import Ficha


@dataclass
class Declaracao:
    modelo: str
    rendimento: float
    deducoes: float
    base: float
    imposto: float
    aliquota_efetiva: float


@dataclass
class Tributario:
    rendimento_tributavel: float
    completa: Declaracao
    simplificada: Declaracao
    melhor: str
    pgbl_limite: float  # 12% do rendimento tributável
    pgbl_atual: float
    pgbl_economia_ideal: float  # IR a menos se aportar o limite (vs. sem PGBL), na completa
    pgbl_economia_adicional: float  # IR a menos se completar do aporte atual até o limite
    pgbl_vale: bool
    imposto_minimo: float  # IRPF mínimo de alta renda (estimado)
    renda_total_anual: float
    deducoes: list[list] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


def _declaracoes(rend: float, inss: float, dependentes: int, educacao: float, saude: float, pgbl: float,
                 r: dict) -> tuple[Declaracao, Declaracao, list[list]]:
    d = r["irpf_tabela_mensal"]["deducoes_anuais"]
    ded = [["Previdência oficial (INSS)", inss], ["Dependentes", dependentes * d["dependente"]],
           ["Educação (até o limite por pessoa)", min(educacao, d["educacao_por_pessoa"] * (dependentes + 1))],
           ["Saúde (sem limite)", saude], ["PGBL (até 12%)", min(pgbl, rend * d["pgbl_maximo_renda_tributavel"])]]
    total = sum(v for _, v in ded)
    base_c = max(0.0, rend - total)
    ir_c = impostos.irpf_anual(base_c, rend, r=r)
    desc = min(rend * d["desconto_simplificado"], d["desconto_simplificado_teto"])
    base_s = max(0.0, rend - desc)
    ir_s = impostos.irpf_anual(base_s, rend, r=r)
    ef = lambda ir: ir / rend if rend else 0.0  # noqa: E731
    return (Declaracao("Completa", rend, total, base_c, ir_c, ef(ir_c)),
            Declaracao("Simplificada", rend, desc, base_s, ir_s, ef(ir_s)), ded)


def planejar(f: Ficha, r: dict | None = None) -> Tributario:
    r = r or impostos._r()
    notas = []
    if f.ocupacao == "empresario":
        notas.append("Empresário: lucros distribuídos são isentos na PF; entram no ajuste o pró-labore e as outras rendas. "
                     "O regime da empresa está no módulo PF × PJ.")
        rend = (f.pro_labore_mensal + f.outras_rendas_mensais) * 12
        inss = (min(f.pro_labore_mensal, impostos.inss_teto(r)) * r["inss"]["pro_labore_retido"] * 12
                if f.contribui_inss else 0.0)
    else:
        rend = (f.renda_mensal_bruta + f.outras_rendas_mensais) * 12
        if f.ocupacao in {"clt", "servidor"} and f.contribui_inss:
            inss = impostos.inss_empregado(f.renda_mensal_bruta, r) * 12
        elif f.ocupacao in {"autonomo", "profissional_liberal"} and f.contribui_inss:
            inss = min(f.renda_mensal_bruta, impostos.inss_teto(r)) * r["inss"]["contribuinte_individual"] * 12
        else:
            inss = 0.0
    n_dep = len(f.dependentes)
    comp, simp, ded = _declaracoes(rend, inss, n_dep, f.gastos_educacao_anual, f.gastos_saude_anual, f.aporte_pgbl_anual, r)
    melhor = "Completa" if comp.imposto < simp.imposto else "Simplificada"
    limite = rend * r["irpf_tabela_mensal"]["deducoes_anuais"]["pgbl_maximo_renda_tributavel"]
    pode_pgbl = f.contribui_inss or f.ocupacao == "aposentado"
    sem, _, _ = _declaracoes(rend, inss, n_dep, f.gastos_educacao_anual, f.gastos_saude_anual, 0.0, r)
    ideal, _, _ = _declaracoes(rend, inss, n_dep, f.gastos_educacao_anual, f.gastos_saude_anual, limite, r)
    economia_ideal = max(0.0, min(sem.imposto, simp.imposto) - ideal.imposto) if pode_pgbl else 0.0
    economia_adic = max(0.0, min(comp.imposto, simp.imposto) - ideal.imposto) if pode_pgbl else 0.0
    if not pode_pgbl:
        notas.append("PGBL só deduz para quem contribui ao INSS ou a regime próprio.")
    lucros = max(0.0, f.renda_mensal_bruta - f.pro_labore_mensal) * 12 if f.ocupacao == "empresario" else 0.0
    renda_total = rend + (f.renda_mensal_bruta if f.tem_13 else 0.0) + lucros
    minimo = impostos.irpf_minimo_alta_renda(renda_total, min(comp.imposto, simp.imposto), r)
    if renda_total > r["irpf_alta_renda"]["renda_minima_anual"]:
        notas.append("Renda anual acima de R$ 600 mil: sujeito ao imposto mínimo da Lei 15.270/2025 (estimativa sem o "
                     "redutor que considera o IR já pago pela empresa — confira com o contador).")
    return Tributario(rend, comp, simp, melhor, limite, f.aporte_pgbl_anual, economia_ideal, economia_adic,
                      economia_adic > 0 and pode_pgbl, minimo, renda_total, ded, notas)
