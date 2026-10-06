"""Rebalanceamento para uma alocação-alvo minimizando imposto (estimativa — confirme custos e datas com a corretora).

Ordem: (1) o aporte vai para as classes abaixo do alvo; (2) o que ainda sobra acima do alvo é vendido começando pelas
posições com MENOR imposto por real vendido (prejuízo, isentas, dentro da isenção de R$ 20 mil/mês em ações e
R$ 35 mil/mês em cripto); previdência não é vendida (use portabilidade). IR estimado:
ações 15% (isento se vendas de ações no mês ≤ R$ 20 mil) · ETF de renda variável 15% · FII 20% · renda fixa pela
tabela regressiva (dias desde a aplicação) · LCI/LCA/CRI/CRA/incentivadas isentas · fundos 15% (aprox., come-cotas já
pago em parte) · cripto 15% acima de R$ 35 mil/mês.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from quiron.servicos.calculadoras import aliquota_ir
from quiron.servicos.carteira.modelo import CLASSES, ORDEM, UNITS, Carteira, Posicao

TOLERANCIA = 0.01  # desvio de até 1 p.p. não gera ordem


@dataclass
class Ordem:
    acao: str  # vender | comprar
    alvo: str  # nome da posição (vender) ou classe (comprar)
    classe: str
    valor: float
    ganho: float = 0.0
    ir: float = 0.0
    nota: str = ""


@dataclass
class Plano:
    ordens: list[Ordem]
    ir_total: float
    aporte_usado: float
    aporte_sem_vender: float  # aporte necessário para chegar ao alvo sem vender nada
    pesos_finais: dict[str, float]
    classe_limitante: str = ""  # a classe mais acima do alvo, que define o aporte_sem_vender
    avisos: list[str] = field(default_factory=list)


def _aliquota(p: Posicao, hoje: date) -> tuple[float, str]:
    t = (p.tipo or "").lower()
    if p.isento and p.classe != "fii":
        return 0.0, "isento para PF"
    if p.classe == "fii":
        return 0.20, "FII: 20% sobre o ganho"
    unit = (p.ticker or "").upper().removesuffix(".SA") in UNITS  # TAEE11, KLBN11…: ações, não ETF
    if t == "etf" or (p.ticker and p.ticker.endswith("11") and not unit and p.classe in {"acoes", "internacional"}):
        return 0.15, "ETF: 15% sobre o ganho (sem isenção de R$ 20 mil)"
    if p.classe == "acoes" and t in {"acao", ""} and p.ticker:
        return 0.15, "ações: 15% sobre o ganho (isento se vendas no mês ≤ R$ 20 mil)"
    if p.classe == "cripto":
        return 0.15, "cripto: 15% sobre o ganho acima de R$ 35 mil/mês de vendas"
    if t in {"fundo", "previdencia"} or p.classe in {"multimercado", "acoes", "internacional"}:
        return 0.15, "fundo: ~15% sobre o ganho (aprox.)"
    if p.data_aplicacao:
        aliq, _ = aliquota_ir((hoje - p.data_aplicacao).days)
        return aliq, f"renda fixa: {aliq * 100:.1f}% ({(hoje - p.data_aplicacao).days} dias)"
    return 0.15, "renda fixa: 15% (data da aplicação não informada; assumido > 720 dias)"


def planejar(carteira: Carteira, alvo: dict[str, float], aporte: float = 0.0, hoje: date | None = None) -> Plano:
    hoje = hoje or date.today()
    avisos = []
    total_final = carteira.total + aporte
    atual = {c: sum(p.valor for p in carteira.posicoes if p.classe == c) for c in ORDEM}
    desejado = {c: alvo.get(c, 0.0) * total_final for c in ORDEM}
    ordens: list[Ordem] = []
    # 1) aporte nas classes abaixo do alvo (proporcional ao que falta)
    faltas = {c: max(0.0, desejado[c] - atual[c]) for c in ORDEM}
    soma_faltas = sum(faltas.values())
    usado = 0.0
    if aporte > 0 and soma_faltas > 0:
        for c in ORDEM:
            v = aporte * faltas[c] / soma_faltas if soma_faltas > aporte else faltas[c]
            if v > 1:
                ordens.append(Ordem("comprar", CLASSES[c]["nome"], c, v, nota="com o aporte"))
                atual[c] += v
                usado += v
    # 2) vender o excesso, priorizando menor imposto por real
    vendas_acoes = vendas_cripto = 0.0
    candidatos = []
    for p in carteira.posicoes:
        excesso = atual[p.classe] - desejado[p.classe]
        if excesso <= TOLERANCIA * total_final or p.tipo == "previdencia":
            continue
        aliq, regra = _aliquota(p, hoje)
        if p.custo is None:
            avisos.append(f"{p.nome}: custo não informado — IR estimado como zero (ganho desconhecido).")
        ganho_rel = (p.valor - p.custo) / p.valor if p.custo is not None and p.valor else 0.0
        candidatos.append((aliq * max(ganho_rel, 0) - (0.001 if ganho_rel < 0 else 0), p, aliq, regra, ganho_rel))
    candidatos.sort(key=lambda x: x[0])
    for _, p, aliq, regra, ganho_rel in candidatos:
        excesso = atual[p.classe] - desejado[p.classe]
        if excesso <= TOLERANCIA * total_final:
            continue
        v = min(p.valor, excesso)
        ganho = v * ganho_rel
        ir = max(0.0, ganho) * aliq
        if p.classe == "acoes" and "isento se vendas" in regra:
            vendas_acoes += v
        if p.classe == "cripto" and "35 mil" in regra:
            vendas_cripto += v
        ordens.append(Ordem("vender", p.nome, p.classe, v, ganho, ir, regra))
        atual[p.classe] -= v
    if vendas_acoes and vendas_acoes <= 20_000:
        for o in ordens:
            if o.acao == "vender" and "isento se vendas" in o.nota:
                o.ir, o.nota = 0.0, "ações: isento (vendas de ações no mês ≤ R$ 20 mil)"
    if vendas_cripto and vendas_cripto <= 35_000:
        for o in ordens:
            if o.acao == "vender" and o.classe == "cripto" and "35 mil" in o.nota:
                o.ir, o.nota = 0.0, "cripto: isento (vendas de cripto no mês ≤ R$ 35 mil)"
    # 3) o que foi vendido compra as classes ainda abaixo do alvo
    caixa = sum(o.valor for o in ordens if o.acao == "vender")
    faltas = {c: max(0.0, desejado[c] - atual[c]) for c in ORDEM}
    soma_faltas = sum(faltas.values())
    if caixa > 1 and soma_faltas > 0:
        for c in ORDEM:
            v = caixa * faltas[c] / soma_faltas
            if v > 1:
                ordens.append(Ordem("comprar", CLASSES[c]["nome"], c, v, nota="com o valor das vendas"))
                atual[c] += v
    total = sum(atual.values()) or 1
    # sem vender: o patrimônio precisa crescer até que a classe mais acima do alvo volte ao seu peso-alvo
    originais = {c: sum(p.valor for p in carteira.posicoes if p.classe == c) for c in ORDEM}
    necessarios = {c: originais[c] / alvo[c] for c in ORDEM if alvo.get(c, 0) > 0}
    limitante = max(necessarios, key=necessarios.get) if necessarios else ""
    sem_vender = max([*necessarios.values(), carteira.total]) - carteira.total
    if any(originais[c] > 0 and alvo.get(c, 0) <= 0 for c in ORDEM):
        avisos.append("Há classe com alvo zero no perfil: sem vender, ela nunca volta ao alvo (o aporte sem vender a ignora).")
    if any(p.classe in {"pos_fixado", "prefixado", "inflacao"} for o in ordens if o.acao == "vender"
           for p in carteira.posicoes if p.nome == o.alvo):
        avisos.append("Antes de vender renda fixa, confira liquidez/carência (CDB, LCI, LCA podem não ter resgate antecipado).")
    return Plano(ordens, sum(o.ir for o in ordens), usado, max(0.0, sem_vender), {c: v / total for c, v in atual.items()},
                 limitante if sem_vender > 0 else "", avisos)
