"""Sucessão: meação, herança, ITCMD por estado, custos de inventário e liquidez para os herdeiros.

Simplificações declaradas no relatório: um único falecimento (o titular); ITCMD com a alíquota MÁXIMA da faixa do
estado (conservador — as tabelas progressivas pós-EC 132/2023 variam); previdência (PGBL/VGBL) fora do inventário e
sem ITCMD (STF, Tema 1214 — confira a lei do estado); bens no exterior fora do cálculo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.nucleo import regras
from quiron.servicos.planejamento.diagnostico import premissas
from quiron.servicos.planejamento.ficha import Ficha

PREVIDENCIA = {"previdencia_pgbl", "previdencia_vgbl"}


@dataclass
class Sucessao:
    uf: str
    aliquota_itcmd: float
    aliquota_texto: str
    monte: float  # bens do titular/casal que entram no inventário
    meacao: float  # parte do cônjuge (não é herança, sem ITCMD)
    heranca: float
    itcmd: float
    custos_inventario: float
    manutencao_familia: float  # despesas da família enquanto os bens ficam bloqueados
    necessidade_liquidez: float
    previdencia: float  # vai direto aos beneficiários
    seguro_vida: float
    liquidez_fora_inventario: float
    falta_liquidez: float
    legitima: float  # 50% da herança reservada aos herdeiros necessários
    herdeiros: str
    custo_total_pct: float  # (ITCMD + custos) ÷ monte
    comparativo: list[list] = field(default_factory=list)  # alternativas e o efeito estimado
    notas: list[str] = field(default_factory=list)


def aliquota_itcmd(uf: str, r: dict | None = None) -> tuple[float, str]:
    estados = (r or regras.carregar_regras())["itcmd"]["estados"]
    v = estados.get(uf)
    if v is None:
        maxima = (r or regras.carregar_regras())["itcmd"]["aliquota_maxima_nacional"]
        return float(maxima), f"{uf or 'UF não informada'}: sem alíquota cadastrada — usei o teto nacional de {_pc(maxima)}"
    if isinstance(v, list):
        return float(v[1]), f"{uf}: faixa de {_pc(v[0])} a {_pc(v[1])} — usei a máxima (conservador)"
    return float(v), f"{uf}: {_pc(v)}"


def _pc(v: float) -> str:
    return f"{float(v) * 100:.2f}".replace(".", ",") + "%"


def herdeiros(f: Ficha) -> str:
    filhos = len(f.filhos)
    if filhos and f.casado:
        return f"{filhos} filho(s) e o cônjuge (concorre conforme o regime de bens)"
    if filhos:
        return f"{filhos} filho(s)"
    if f.casado:
        return "cônjuge (e ascendentes, se houver)"
    return "ascendentes; na falta, colaterais (sem testamento)"


def planejar(f: Ficha, p: dict | None = None, r: dict | None = None) -> Sucessao:
    p = p or premissas()
    cfg = p["sucessao"]
    aliq, texto = aliquota_itcmd(f.uf, r)
    notas = []
    bens = [b for b in f.patrimonio if b.tipo not in PREVIDENCIA]
    monte = sum(b.valor for b in bens)
    regime = f.regime_bens if f.casado else ""
    if regime == "comunhao_universal":
        meacao = 0.5 * sum(b.valor for b in bens if not b.particular)
    elif regime in {"comunhao_parcial", "participacao_final"}:
        meacao = 0.5 * sum(b.valor for b in bens if not b.particular)
        if regime == "participacao_final":
            notas.append("Participação final nos aquestos tratada como comunhão parcial (aproximação).")
    else:
        meacao = 0.0
    if f.casado and regime == "comunhao_parcial" and any(b.particular for b in bens):
        notas.append("Na comunhão parcial o cônjuge herda junto com os filhos nos bens particulares (art. 1.829 do Código Civil).")
    if f.casado and not regime:
        notas.append("Regime de bens não informado: calculado sem meação (conservador para o ITCMD).")
    heranca = monte - meacao
    dividas = f.dividas_total
    heranca_liq = max(0.0, heranca - dividas)  # dívidas saem do espólio antes da partilha
    itcmd = heranca_liq * aliq
    custos = monte * (cfg["honorarios_inventario"] + cfg["custas_inventario"])
    tem_dependentes = bool(f.dependentes) or f.casado
    manutencao = f.despesas_mensais * cfg["meses_inventario"] * p["protecao"]["parcela_despesa_familia"] if tem_dependentes else 0.0
    necessidade = itcmd + custos + manutencao
    previdencia = sum(b.valor for b in f.patrimonio if b.tipo in PREVIDENCIA)
    seguro = sum(s.cobertura for s in f.seguros if s.tipo == "vida")
    fora = previdencia + seguro
    falta = max(0.0, necessidade - fora)
    comp = []  # [alternativa, valor de referência (R$) ou None, o que é o valor e como funciona]
    if falta > 0:
        comp.append(["Seguro de vida para a liquidez", round(falta, 2),
                     "capital sugerido: chega em ~30 dias aos beneficiários, fora do inventário e sem ITCMD"])
    comp.append(["Previdência (VGBL/PGBL)", round(100_000 * aliq, 2),
                 "ITCMD evitado a cada R$ 100 mil em previdência (STF, Tema 1214) e sem inventário desses recursos"])
    if heranca_liq > 0:
        comp.append(["Doação em vida com reserva de usufruto", round(itcmd, 2),
                     "ITCMD antecipado (alíquota de hoje; a tendência é de alta com a progressividade); bens fora do inventário"])
    comp.append(["Inventário extrajudicial (cartório)", None,
                 "herdeiros maiores, capazes e de acordo: meses em vez de anos, custas menores"])
    comp.append(["Testamento", None, "dispõe de até 50% da herança (parte disponível); a legítima é dos herdeiros necessários"])
    return Sucessao(f.uf, aliq, texto, monte, meacao, heranca, itcmd, custos, manutencao, necessidade, previdencia, seguro,
                    fora, falta, heranca_liq * 0.5 if f.filhos or f.casado else 0.0, herdeiros(f),
                    (itcmd + custos) / monte if monte else 0.0, comp, notas)
