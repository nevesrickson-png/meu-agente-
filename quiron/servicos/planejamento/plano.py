"""Plano completo: junta diagnóstico, objetivos, aposentadoria, proteção, sucessão, tributário e PF × PJ, monta o
orçamento de aportes e o plano de ação priorizado (o que fazer primeiro e por quê, com números)."""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.servicos.analise.relatorio import brl, pct
from quiron.servicos.planejamento import aposentadoria, diagnostico, empresario, protecao, sucessao, tributario
from quiron.servicos.planejamento.ficha import Ficha


@dataclass
class Plano:
    ficha: Ficha
    diag: diagnostico.Diagnostico
    apos: aposentadoria.Aposentadoria
    suc: sucessao.Sucessao
    trib: tributario.Tributario
    prot: protecao.Protecao
    emp: empresario.Empresario | None
    capital_aposentadoria: float
    orcamento: list[list]  # [destino, aporte mensal]
    total_aportes: float
    acoes: list[list] = field(default_factory=list)  # [prioridade, ação, valor de referência, porquê]


def montar(f: Ficha, p: dict | None = None, r: dict | None = None) -> Plano:
    p = p or diagnostico.premissas()
    diag = diagnostico.diagnosticar(f, p, r)
    reservado = min(diag.reserva_meta, f.liquido) + sum(o.ja_acumulado for o in f.objetivos)
    capital = max(0.0, f.investimentos - reservado)
    falta_reserva = max(0.0, diag.reserva_meta - diag.reserva_atual)
    # o que sobra para a aposentadoria depois da reserva e dos objetivos essenciais/importantes (prioridade 1 e 2)
    viavel = max(0.0, diag.sobra - falta_reserva / 12 - sum(o.aporte_mensal for o in diag.objetivos if o.prioridade <= 2))
    apos = aposentadoria.planejar(f, capital, p, aporte_viavel=viavel)
    suc = sucessao.planejar(f, p, r)
    trib = tributario.planejar(f, r)
    prot = protecao.planejar(f, diag, suc, p)
    emp = empresario.comparar(f.empresa, p, r) if f.empresa and f.empresa.faturamento_anual > 0 else None

    orc = []
    if falta_reserva:
        orc.append(["Completar a reserva de emergência (em 12 meses)", falta_reserva / 12])
    for o in diag.objetivos:
        orc.append([f"Objetivo: {o.nome}", o.aporte_mensal])
    if apos.aporte_alvo is not None:
        orc.append([f"Aposentadoria ({apos.sucesso_alvo:.0%} de chance)", apos.aporte_alvo])
    total = sum(v for _, v in orc)

    acoes = []
    if diag.sobra < 0:
        acoes.append([1, "Equilibrar o orçamento", -diag.sobra, "As despesas superam a renda; nenhum plano se sustenta assim."])
    for d in f.dividas:
        if (d.taxa_am or 0) >= 2.0:
            acoes.append([1, f"Quitar {d.nome}", d.saldo, f"Custa {pct(d.taxa_am)} ao mês — nenhum investimento seguro paga isso."])
    if falta_reserva:
        acoes.append([1, "Completar a reserva de emergência", falta_reserva,
                      f"Meta de {diag.reserva_meta / max(1, f.despesas_mensais + diag.parcelas):.0f} meses de despesas para a ocupação."])
    if prot.falta_vida > 0:
        acoes.append([1, "Contratar/aumentar seguro de vida", prot.falta_vida,
                      "A família ficaria sem a renda necessária até a independência dos filhos."])
    if prot.falta_invalidez > 0 and f.ocupacao != "aposentado":
        acoes.append([2, "Seguro de invalidez permanente", prot.falta_invalidez,
                      "Repõe o que falta para as despesas se o titular não puder mais trabalhar."])
    if not prot.tem_saude:
        acoes.append([1, "Plano de saúde", None, "Sem plano, uma internação longa consome reserva e investimentos."])
    if apos.aporte_alvo is not None and apos.prob_sucesso_atual < apos.sucesso_alvo:
        acoes.append([2, "Aumentar o aporte para a aposentadoria", apos.aporte_alvo - f.aporte_mensal,
                      f"Com o aporte atual a chance de a renda durar até {apos.idade_fim} anos é "
                      f"{apos.prob_sucesso_atual:.0%}; a renda sustentável com {apos.sucesso_alvo:.0%} de chance é "
                      f"{brl(apos.renda_alvo)}/mês."])
    if total > max(0.0, diag.sobra) and total > 0:
        viavel_txt = ""
        if apos.renda_viavel is not None:
            viavel_txt = (f" Destinando à aposentadoria o que sobra depois da reserva e dos objetivos 1 e 2 "
                          f"({brl(apos.aporte_viavel)}/mês), a renda sustentável com {apos.sucesso_alvo:.0%} de chance é "
                          f"{brl(apos.renda_viavel)}/mês.")
        acoes.append([2, "Rever metas ou prazos (os aportes necessários passam da sobra)", total - max(0.0, diag.sobra),
                      "Alternativas: adiar objetivos de prioridade 3, aposentar mais tarde ou reduzir a renda desejada."
                      + viavel_txt])
    if suc.falta_liquidez > 0:
        acoes.append([2, "Garantir liquidez para a sucessão", suc.falta_liquidez,
                      "ITCMD, inventário e despesas da família precisam de dinheiro fora do inventário (seguro/previdência)."])
    if trib.pgbl_vale:
        acoes.append([3, "Aportar no PGBL até 12% da renda tributável", trib.pgbl_limite - trib.pgbl_atual,
                      f"Reduz o IR em cerca de {brl(trib.pgbl_economia_adicional)} por ano (diferimento: tributação na saída)."])
    if emp and emp.economia_vs_atual and emp.economia_vs_atual > 6000:
        acoes.append([2, f"Avaliar com o contador a mudança para {emp.melhor}", emp.economia_vs_atual,
                      "Diferença estimada no líquido anual do dono em relação ao regime atual."])
    if f.casado or f.filhos:
        acoes.append([3, "Organizar a sucessão (testamento, beneficiários da previdência e do seguro)", None,
                      f"Herdeiros: {suc.herdeiros}. Custo estimado da sucessão hoje: {brl(suc.itcmd + suc.custos_inventario)}."])
    acoes.sort(key=lambda a: a[0])
    return Plano(f, diag, apos, suc, trib, prot, emp, capital, orc, total, acoes)
