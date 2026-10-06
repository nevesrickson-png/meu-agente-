"""Módulo empresário (PF × PJ) para prestador de serviços intelectuais: quanto sobra para o dono em cada regime.

Cenários (o dono retira todo o resultado): PF autônoma (carnê-leão + INSS 20%), Simples Nacional no Anexo III com
fator R (pró-labore para chegar a 28%), Simples no Anexo V (pró-labore mínimo) e Lucro Presumido (pró-labore
mínimo + lucros). Lucros distribuídos são isentos na PF, mas entram no imposto mínimo de alta renda (Lei 15.270/2025).
Estimativa para conversar com o contador — não substitui o enquadramento formal (atividade, CNAE, município).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.servicos.planejamento import impostos
from quiron.servicos.planejamento.diagnostico import premissas
from quiron.servicos.planejamento.ficha import Empresa


@dataclass
class Cenario:
    nome: str
    tributos_empresa: float  # DAS / IRPJ+CSLL+PIS+COFINS+ISS / (PF: 0)
    inss: float  # do dono (+ patronal no Presumido)
    irpf: float  # sobre pró-labore ou rendimento PF
    imposto_minimo: float  # alta renda (sobre pró-labore + lucros)
    custos_extras: float  # contabilidade da PJ
    pro_labore: float  # anual
    lucros: float  # anual, distribuídos
    liquido_dono: float  # anual
    carga_total: float  # tudo o que foi para impostos ÷ faturamento
    aplicavel: bool = True
    nota: str = ""


@dataclass
class Empresario:
    faturamento: float
    despesas: float
    folha: float
    cenarios: list[Cenario]
    melhor: str
    economia_vs_pior: float
    economia_vs_atual: float | None
    regime_atual: str
    notas: list[str] = field(default_factory=list)


def _irpf_pro_labore(anual: float, r: dict) -> tuple[float, float]:
    """(INSS retido 11% até o teto, IRPF mensal × 12) sobre o pró-labore (sem 13º)."""
    mensal = anual / 12
    inss = min(mensal, impostos.inss_teto(r)) * r["inss"]["pro_labore_retido"]
    return inss * 12, impostos.ir_na_fonte(mensal, inss, r) * 12


def comparar(e: Empresa, p: dict | None = None, r: dict | None = None) -> Empresario:
    p = p or premissas()
    r = r or impostos._r()
    pe = p["empresario"]
    F, D, W = e.faturamento_anual, e.despesas_anuais, e.folha_anual
    pl_min = pe["pro_labore_minimo"] * 12
    contab = pe["contabilidade_pj_anual"]
    notas = []
    cen = []

    # PF autônoma: livro-caixa abate despesas; INSS de contribuinte individual 20% até o teto
    base_pf = max(0.0, F - D - W)
    inss_pf = min(base_pf / 12, impostos.inss_teto(r)) * r["inss"]["contribuinte_individual"] * 12
    ir_pf = impostos.irpf_anual(max(0.0, base_pf - inss_pf), base_pf, r=r)
    liq_pf = base_pf - inss_pf - ir_pf
    cen.append(Cenario("Pessoa física (autônomo)", 0.0, inss_pf, ir_pf, 0.0, 0.0, base_pf, 0.0, liq_pf,
                       (inss_pf + ir_pf) / F if F else 0.0, nota="carnê-leão; despesas pelo livro-caixa"))

    simples_ok = F <= r["simples_nacional"]["limite_anual"]
    fator_r = r["simples_nacional"]["fator_r_minimo"]
    for nome, anexo, pl in (("Simples — Anexo III (fator R)", "iii", max(pl_min, fator_r * F - W)),
                            ("Simples — Anexo V", "v", pl_min)):
        if not simples_ok:
            cen.append(Cenario(nome, 0, 0, 0, 0, 0, 0, 0, 0, 0, False, "faturamento acima do limite do Simples"))
            continue
        das = impostos.simples_aliquota(F, anexo, r) * F  # já inclui CPP (patronal) e ISS
        inss, ir = _irpf_pro_labore(pl, r)
        lucros = max(0.0, F - D - W - das - pl - contab)
        renda = pl + lucros
        minimo = impostos.irpf_minimo_alta_renda(renda, ir, r)
        liq = pl - inss - ir + lucros - minimo
        cen.append(Cenario(nome, das, inss, ir, minimo, contab, pl, lucros, liq,
                           (das + inss + ir + minimo) / F if F else 0.0,
                           nota=f"pró-labore de R$ {pl / 12:,.0f}/mês".replace(",", ".")
                           + (" para fator R ≥ 28%" if anexo == "iii" else "")))

    lp = impostos.lucro_presumido(F, e.iss, r)
    inss, ir = _irpf_pro_labore(pl_min, r)
    patronal = pl_min * r["inss"]["patronal_lucro_presumido"]
    lucros = max(0.0, F - D - W - lp.total - pl_min - patronal - contab)
    minimo = impostos.irpf_minimo_alta_renda(pl_min + lucros, ir, r)
    liq = pl_min - inss - ir + lucros - minimo
    cen.append(Cenario("Lucro Presumido", lp.total, inss + patronal, ir, minimo, contab, pl_min, lucros, liq,
                       (lp.total + inss + patronal + ir + minimo) / F if F else 0.0,
                       nota="IRPJ+CSLL sobre 32% presumido, PIS/COFINS cumulativos e ISS do município"))

    validos = [c for c in cen if c.aplicavel]
    melhor = max(validos, key=lambda c: c.liquido_dono)
    pior = min(validos, key=lambda c: c.liquido_dono)
    mapa = {"pf": "Pessoa física (autônomo)", "simples": None, "presumido": "Lucro Presumido"}
    atual_nome = mapa.get(e.regime_atual or "")
    if e.regime_atual == "simples":
        simples = [c for c in validos if c.nome.startswith("Simples")]
        atual_nome = max(simples, key=lambda c: c.liquido_dono).nome if simples else None
        notas.append("Regime atual “Simples”: comparado com o melhor anexo possível (confira o anexo de hoje).")
    atual = next((c for c in validos if c.nome == atual_nome), None)
    if any(c.imposto_minimo > 0 for c in validos):
        notas.append("Há imposto mínimo de alta renda: estimado sem o redutor que limita a soma IRPJ + CSLL + IRPF à "
                     "alíquota nominal da empresa — o valor real pode ser menor.")
    if F > 5_000_000:
        notas.append("Faturamento acima de R$ 5 mi: a LC 224/2025 aumenta a presunção do Lucro Presumido — confira.")
    notas.append("Serviços que não são intelectuais (ex.: alguns do Anexo III direto) e o Lucro Real não estão no comparativo.")
    return Empresario(F, D, W, cen, melhor.nome, melhor.liquido_dono - pior.liquido_dono,
                      (melhor.liquido_dono - atual.liquido_dono) if atual else None, e.regime_atual or "", notas)
