"""Proteção: seguro de vida (método das necessidades), invalidez, reserva de emergência e saúde.

Necessidade de vida = renda da família pelo tempo até a independência dos filhos (valor presente, taxa real de
usufruto) + dívidas + educação dos filhos + funeral + custos da sucessão − recursos disponíveis − seguros atuais.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.servicos.planejamento.diagnostico import Diagnostico, premissas, taxa_mensal, vp_renda
from quiron.servicos.planejamento.ficha import Ficha
from quiron.servicos.planejamento.sucessao import Sucessao


@dataclass
class Protecao:
    anos_renda_familia: int
    renda_familia_mensal: float  # que precisa ser reposta (despesa da família − renda do cônjuge)
    necessidades: list[list]  # [item, R$]
    recursos: list[list]  # [item, R$]
    necessidade_vida: float
    cobertura_vida: float
    falta_vida: float
    necessidade_invalidez: float
    cobertura_invalidez: float
    falta_invalidez: float
    reserva_meta: float
    reserva_atual: float
    tem_saude: bool
    notas: list[str] = field(default_factory=list)


def planejar(f: Ficha, diag: Diagnostico, suc: Sucessao, p: dict | None = None) -> Protecao:
    p = p or premissas()
    c = p["protecao"]
    i_u = taxa_mensal(float(p["retorno_real_usufruto"]))
    notas = []
    filhos = f.filhos
    mais_novo = min((d.idade for d in filhos), default=None)
    anos = max(c["anos_minimos_renda_familia"] if (f.casado or filhos) else 0,
               (c["idade_independencia_filhos"] - mais_novo) if mais_novo is not None else 0)
    renda_conj = next((v for n, v in diag.renda.detalhes if n.startswith("Cônjuge")), 0.0)
    renda_familia = max(0.0, f.despesas_mensais * c["parcela_despesa_familia"] - renda_conj)  # dívidas quitadas à parte
    pv_renda = vp_renda(renda_familia, i_u, anos * 12)
    educacao = c["educacao_superior_por_filho"] * sum(1 for d in filhos if d.idade < 23)
    sucessao = suc.itcmd + suc.custos_inventario
    necessidades = [["Renda da família até a independência dos filhos", round(pv_renda, 2)],
                    ["Quitação de dívidas", round(f.dividas_total, 2)],
                    ["Educação superior dos filhos", round(educacao, 2)],
                    ["Funeral e despesas imediatas", round(c["despesas_funeral"], 2)],
                    ["ITCMD e custos do inventário", round(sucessao, 2)]]
    nec = sum(v for _, v in necessidades)
    recursos = [["Investimentos líquidos (ficam no inventário: demoram a chegar)", round(f.liquido, 2)],
                ["Previdência (vai direto aos beneficiários)", round(suc.previdencia, 2)]]
    disponivel = sum(v for _, v in recursos)
    cobertura = sum(s.cobertura for s in f.seguros if s.tipo == "vida")
    falta = max(0.0, nec - disponivel - cobertura)
    if not (f.casado or filhos or f.dependentes):
        notas.append("Sem dependentes: o seguro de vida serve basicamente à liquidez da sucessão e às dívidas.")
    # invalidez: o titular continua vivo e gastando — repor o que falta para as despesas (sem a renda do trabalho dele)
    # por N anos; o INSS por invalidez é complemento, não garantia
    falta_mensal = max(0.0, f.despesas_mensais + diag.parcelas - renda_conj - f.outras_rendas_mensais)
    nec_inv = vp_renda(falta_mensal, i_u, int(c["invalidez_anos_renda"]) * 12) if f.ocupacao != "aposentado" else 0.0
    cob_inv = sum(s.cobertura for s in f.seguros if s.tipo == "invalidez")
    tem_saude = any(s.tipo == "saude" for s in f.seguros)
    if not tem_saude:
        notas.append("Sem plano de saúde na ficha: uma internação longa pode consumir a reserva e os investimentos.")
    if f.ocupacao in {"autonomo", "profissional_liberal", "empresario"}:
        notas.append("Renda depende do trabalho do titular: considere seguro de diária por incapacidade temporária (DIT).")
    return Protecao(anos, renda_familia, necessidades, recursos, nec, cobertura, falta, nec_inv, cob_inv,
                    max(0.0, nec_inv - cob_inv), diag.reserva_meta, diag.reserva_atual, tem_saude, notas)
