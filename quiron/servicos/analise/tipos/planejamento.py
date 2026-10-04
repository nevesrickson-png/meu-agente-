"""Análises de planejamento financeiro (Fase 9, padrão CFP) no motor da Fase 7.

Todas leem a ficha do cliente (`quiron-assessoria`, por CLI-XXX) e calculam em Python (`servicos/planejamento/`):
- planejamento_completo: diagnóstico, objetivos, aposentadoria, proteção, sucessão, tributário, PF × PJ e plano de ação;
- aposentadoria, sucessao, tributario, protecao, empresario: cada módulo sozinho, com mais detalhe.
O relatório é um RASCUNHO para revisão do planejador — não vai ao cliente sem a revisão do Rickson.
"""

from __future__ import annotations

from typing import Any

from quiron.nucleo import regras
from quiron.servicos.analise import redacao
from quiron.servicos.analise.fila import tipo
from quiron.servicos.analise.relatorio import Grafico, Relatorio, Secao, Tabela, brl, pct
from quiron.servicos.planejamento import ficha as fichas
from quiron.servicos.planejamento.diagnostico import premissas
from quiron.servicos.planejamento.ficha import TIPOS_BEM
from quiron.servicos.planejamento.plano import Plano, montar

RODAPE = ("Rascunho de planejamento para revisão do planejador — não entregar ao cliente sem revisão. Estimativas "
          "com premissas declaradas; não constitui recomendação individual.")
NOMES_BEM = {"residencia": "Residência", "imovel": "Imóveis", "investimento": "Investimentos",
             "previdencia_pgbl": "Previdência PGBL", "previdencia_vgbl": "Previdência VGBL", "empresa": "Empresa",
             "veiculo": "Veículos", "outro": "Outros"}
NOMES_REGIME = {"pf": "Pessoa física (autônomo)", "simples": "Simples Nacional", "presumido": "Lucro Presumido"}
BLOCOS_REGRAS = ("irpf", "inss", "simples", "lucro_presumido", "itcmd", "previdencia")
PARAMETROS = {"cliente": "código CLI-XXX com ficha salva no quiron-assessoria (salvar_ficha)"}


def _r(v: float, casas: int = 2) -> float:
    return round(float(v), casas)


# ---------------------------------------------------------------- seções
def secao_diagnostico(pl: Plano) -> Secao:
    f, d = pl.ficha, pl.diag
    fluxo = Tabela("Fluxo de caixa mensal (média, R$)", ["Item", "Valor (R$)"],
                   [["Renda bruta (titular + cônjuge + outras)", _r(d.renda.bruta)],
                    *[[n, _r(v)] for n, v in d.renda.detalhes],
                    ["Renda líquida (com 13º/férias quando houver)", _r(d.renda.liquida)],
                    ["Despesas da família", _r(-d.despesas)], ["Parcelas de dívidas", _r(-d.parcelas)],
                    ["Sobra (capacidade de poupança)", _r(d.sobra)], ["Aporte que já faz hoje", _r(d.aporte_declarado)]],
                   ["texto", "reais"], "Renda líquida estimada pelas tabelas de IR e INSS de config/regras_mercado.yaml.")
    por_tipo = {t: sum(b.valor for b in f.patrimonio if b.tipo == t) for t in TIPOS_BEM}
    balanco = Tabela("Balanço patrimonial", ["Item", "Valor (R$)", "Participação"],
                     [[NOMES_BEM[t], _r(v), _r(v / f.patrimonio_total * 100) if f.patrimonio_total else 0]
                      for t, v in por_tipo.items() if v]
                     + [["Dívidas", _r(-d.dividas), None], ["Patrimônio líquido", _r(d.patrimonio_liquido), None]],
                     ["texto", "reais", "pct"])
    p = premissas()
    ind = Tabela("Indicadores", ["Indicador", "Valor", "Referência", "Situação"], [
        ["Taxa de poupança (sobra ÷ renda líquida)", pct(d.taxa_poupanca * 100, 1), f"≥ {p['poupanca_minima']:.0%}",
         "ok" if d.taxa_poupanca >= p["poupanca_minima"] else "abaixo"],
        ["Investimentos líquidos (meses de despesa)", f"{d.meses_reserva:.1f}".replace(".", ","),
         f"reserva: {d.reserva_meta / max(1, d.despesas + d.parcelas):.0f} meses",
         "ok" if d.reserva_atual >= d.reserva_meta else "abaixo"],
        ["Comprometimento com dívidas", pct(d.comprometimento * 100, 1), f"≤ {p['comprometimento_dividas_max']:.0%}",
         "ok" if d.comprometimento <= p["comprometimento_dividas_max"] else "acima"],
        ["Patrimônio financeiro ÷ despesa anual", f"{d.anos_independencia:.1f} anos".replace(".", ","), "—", "—"]],
        ["texto", "texto", "texto", "texto"])
    ind.nota = (f"Reserva de emergência separada: {brl(min(d.reserva_meta, d.reserva_atual))}. O que passa disso já conta "
                f"como patrimônio da aposentadoria ({brl(pl.capital_aposentadoria)}) — não está parado.")
    g = Grafico("Patrimônio por tipo", "barras_h", [NOMES_BEM[t] for t, v in por_tipo.items() if v],
                {"Valor": [_r(v, 0) for v in por_tipo.values() if v]}, "brl")
    texto = "\n".join(f"- ⚠ {a}" for a in d.alertas)
    return Secao("Diagnóstico financeiro", texto, [fluxo, balanco, ind], [g])


def secao_objetivos(pl: Plano) -> Secao:
    d = pl.diag
    linhas = [[o.nome, o.prioridade, _r(o.valor), o.prazo_anos, _r(o.retorno_real), _r(o.ja_acumulado), _r(o.aporte_mensal)]
              for o in d.objetivos]
    t = Tabela("Objetivos (valores de hoje)", ["Objetivo", "Prioridade", "Valor (R$)", "Prazo (anos)", "Retorno real a.a.",
                                               "Já acumulado (R$)", "Aporte mensal (R$)"], linhas,
               ["texto", "int", "reais", "num", "pct", "reais", "reais"],
               "Prioridade 1 essencial · 2 importante · 3 desejável. Prazos até 2 anos usam carteira conservadora.")
    orc = Tabela("Orçamento de aportes × sobra", ["Destino", "Aporte mensal (R$)"],
                 [[n, _r(v)] for n, v in pl.orcamento] + [["Total necessário", _r(pl.total_aportes)],
                                                          ["Sobra mensal disponível", _r(d.sobra)],
                                                          ["Diferença", _r(d.sobra - pl.total_aportes)]],
                 ["texto", "reais"])
    graficos = []
    if pl.orcamento:
        graficos.append(Grafico("Aporte mensal necessário por destino", "barras_h", [n for n, _ in pl.orcamento],
                                {"Aporte": [_r(v, 0) for _, v in pl.orcamento]}, "brl",
                                nota=f"Sobra mensal disponível: {brl(d.sobra)}."))
    return Secao("Objetivos e orçamento de aportes", "", [t, orc] if linhas else [orc], graficos)


def secao_aposentadoria(pl: Plano) -> Secao:
    a = pl.apos
    t = Tabela("Independência financeira (R$ de hoje)", ["Item", "Valor"], [
        ["Idade hoje → aposentadoria → fim do plano", f"{a.idade} → {a.idade_aposentadoria} → {a.idade_fim} anos"],
        ["Renda desejada (mensal)", brl(a.renda_desejada)],
        ["INSS estimado (mensal, a partir de)", f"{brl(a.inss)} aos {a.idade_inss} anos"],
        ["Patrimônio destinado à aposentadoria hoje", brl(a.capital_inicial)],
        ["Aporte mensal atual", brl(a.aporte_atual)],
        ["Retorno real: acumulação / usufruto", f"{pct(a.retorno_acumulacao, 1)} / {pct(a.retorno_usufruto, 1)} a.a."],
        ["Capital necessário na aposentadoria", brl(a.capital_necessario)],
        ["Capital projetado com o aporte atual", brl(a.capital_projetado)],
        ["Aporte necessário (cenário médio)", brl(a.aporte_necessario)],
        [f"Aporte para {a.sucesso_alvo:.0%} de chance (Monte Carlo)", brl(a.aporte_alvo) if a.aporte_alvo is not None else "—"],
        ["Renda sustentável com o aporte atual (cenário médio)", brl(a.renda_sustentavel)],
        [f"Renda sustentável com {a.sucesso_alvo:.0%} de chance", brl(a.renda_alvo)],
        ["Com o aporte atual, o dinheiro acaba aos", f"{a.idade_esgota:.0f} anos" if a.idade_esgota else f"não acaba até {a.idade_fim}"],
        ["Chance de a renda durar até o fim do plano (aporte atual)", pct(a.prob_sucesso_atual * 100, 0)],
        ["Chance com o aporte do cenário médio", pct(a.prob_sucesso_necessario * 100, 0)],
        *([["Aporte que cabe no orçamento (sobra − reserva − objetivos 1 e 2)", brl(a.aporte_viavel)],
           ["Chance da renda desejada com esse aporte", pct(a.prob_viavel * 100, 0)],
           [f"Renda sustentável com esse aporte ({a.sucesso_alvo:.0%} de chance)", brl(a.renda_viavel)]]
          if a.renda_viavel is not None else [])],
        ["texto", "texto"], "Cenário médio = retornos constantes; Monte Carlo = 3.000 trajetórias com a volatilidade do perfil.")
    sens = Tabela("Sensibilidade do aporte necessário (cenário médio)", ["Cenário", "Aporte mensal (R$)", "Capital necessário (R$)"],
                  a.sensibilidade, ["texto", "reais", "reais"])
    perc = Tabela("Capital na aposentadoria com o aporte atual (Monte Carlo)", ["Cenário", "Capital (R$)"],
                  [["Pessimista (P10)", _r(a.percentis_capital["P10"])], ["Mediano (P50)", _r(a.percentis_capital["P50"])],
                   ["Otimista (P90)", _r(a.percentis_capital["P90"])]], ["texto", "reais"])
    passo = 1 if len(a.idades) <= 40 else 2
    g = Grafico("Patrimônio para a aposentadoria ao longo da vida (R$ de hoje)", "linhas",
                [str(x) for x in a.idades[::passo]], {k: [_r(v, 0) for v in vs[::passo]] for k, vs in a.trajetoria.items()},
                "brl", "idade", "P10 = em 9 de cada 10 trajetórias o patrimônio fica acima desta linha.")
    texto = "\n".join(f"- {n}" for n in a.notas)
    return Secao("Aposentadoria", texto, [t, perc, sens], [g])


def secao_protecao(pl: Plano) -> Secao:
    pr = pl.prot
    t = Tabela("Seguro de vida — método das necessidades (R$)", ["Item", "Valor (R$)"],
               [*[[n, v] for n, v in pr.necessidades], ["Total de necessidades", _r(pr.necessidade_vida)],
                *[[f"(−) {n}", -v] for n, v in pr.recursos], ["(−) Seguros de vida atuais", -_r(pr.cobertura_vida)],
                ["Capital adicional sugerido", _r(pr.falta_vida)]], ["texto", "reais"],
               f"Renda da família a repor: {brl(pr.renda_familia_mensal)}/mês por {pr.anos_renda_familia} anos "
               "(valor presente à taxa real de usufruto).")
    inv = Tabela("Invalidez, reserva e saúde", ["Proteção", "Necessidade (R$)", "Atual (R$)", "Falta (R$)"], [
        ["Invalidez permanente (repor o que falta para as despesas)", _r(pr.necessidade_invalidez), _r(pr.cobertura_invalidez),
         _r(pr.falta_invalidez)],
        ["Reserva de emergência", _r(pr.reserva_meta), _r(pr.reserva_atual), _r(max(0.0, pr.reserva_meta - pr.reserva_atual))],
        ["Plano de saúde", None, "sim" if pr.tem_saude else "não", None]], ["texto", "reais", "reais", "reais"])
    g = Grafico("Necessidade × cobertura atual", "barras_h", ["Vida", "Invalidez"],
                {"Necessidade líquida": [_r(max(0.0, pr.necessidade_vida - sum(v for _, v in pr.recursos)), 0),
                                         _r(pr.necessidade_invalidez, 0)],
                 "Cobertura atual": [_r(pr.cobertura_vida, 0), _r(pr.cobertura_invalidez, 0)]}, "brl")
    return Secao("Proteção (gestão de riscos)", "\n".join(f"- {n}" for n in pr.notas), [t, inv], [g])


def secao_sucessao(pl: Plano) -> Secao:
    s = pl.suc
    t = Tabela("Sucessão hoje (falecimento do titular)", ["Item", "Valor (R$)"], [
        ["Bens no inventário (sem previdência)", _r(s.monte)], ["(−) Meação do cônjuge (não é herança)", _r(-s.meacao)],
        ["Herança", _r(s.heranca)], [f"ITCMD ({s.aliquota_texto})", _r(s.itcmd)],
        ["Honorários e custas do inventário", _r(s.custos_inventario)],
        ["Despesas da família enquanto os bens ficam bloqueados", _r(s.manutencao_familia)],
        ["Necessidade de liquidez", _r(s.necessidade_liquidez)],
        ["(−) Previdência (vai direto aos beneficiários)", _r(-s.previdencia)],
        ["(−) Seguro de vida", _r(-s.seguro_vida)], ["Falta de liquidez", _r(s.falta_liquidez)]],
        ["texto", "reais"], f"Herdeiros: {s.herdeiros}. Legítima (50% da herança líquida): {brl(s.legitima)}.")
    alt = Tabela("Instrumentos para planejar a sucessão", ["Instrumento", "Valor de referência (R$)", "Como funciona"],
                 s.comparativo, ["texto", "reais", "texto"])
    g = Grafico("Para onde vai o patrimônio do inventário", "barras_h",
                ["Meação do cônjuge", "Herança líquida de ITCMD e custos", "ITCMD", "Inventário"],
                {"Valor": [_r(s.meacao, 0), _r(max(0.0, s.heranca - s.itcmd - s.custos_inventario), 0), _r(s.itcmd, 0),
                           _r(s.custos_inventario, 0)]}, "brl")
    return Secao("Sucessão", "\n".join(f"- {n}" for n in s.notas), [t, alt], [g])


def secao_tributario(pl: Plano) -> Secao:
    tr = pl.trib
    t = Tabela("Declaração anual do titular: completa × simplificada", ["Modelo", "Rendimento tributável (R$)",
                                                                       "Deduções (R$)", "Base (R$)", "IR devido (R$)",
                                                                       "Alíquota efetiva"],
               [[d.modelo, _r(d.rendimento), _r(d.deducoes), _r(d.base), _r(d.imposto), _r(d.aliquota_efetiva * 100)]
                for d in (tr.completa, tr.simplificada)], ["texto", "reais", "reais", "reais", "reais", "pct"],
               "IR com a redução da Lei 15.270/2025; 13º com tributação exclusiva fica fora do ajuste.")
    ded = Tabela("Deduções da completa", ["Dedução", "Valor (R$)"], [[n, _r(v)] for n, v in tr.deducoes], ["texto", "reais"])
    pgbl = Tabela("PGBL", ["Item", "Valor"], [
        ["Limite dedutível (12% do rendimento tributável)", brl(tr.pgbl_limite)], ["Aporte atual no ano", brl(tr.pgbl_atual)],
        ["Economia de IR se completar até o limite", brl(tr.pgbl_economia_adicional)],
        ["Vale a pena?", "sim — usar a declaração completa" if tr.pgbl_vale else "não (simplificada é melhor ou não há IR a deduzir)"]],
        ["texto", "texto"], "PGBL difere o imposto: no resgate tributa o total (tabela regressiva chega a 10% após 10 anos).")
    tabelas = [t, ded, pgbl]
    if tr.imposto_minimo:
        tabelas.append(Tabela("Imposto mínimo de alta renda (estimativa)", ["Item", "Valor (R$)"],
                              [["Renda total anual", _r(tr.renda_total_anual)], ["Imposto mínimo adicional", _r(tr.imposto_minimo)]],
                              ["texto", "reais"]))
    return Secao("Tributário", "\n".join(f"- {n}" for n in tr.notas), tabelas)


def secao_empresario(pl: Plano) -> Secao | None:
    e = pl.emp
    if not e:
        return None
    validos = [c for c in e.cenarios if c.aplicavel]
    t = Tabela(f"PF × PJ — faturamento {brl(e.faturamento)}/ano, despesas {brl(e.despesas)}, folha {brl(e.folha)}",
               ["Regime", "Tributos da empresa (R$)", "INSS (R$)", "IRPF (R$)", "Imposto mínimo (R$)", "Pró-labore (R$)",
                "Lucros (R$)", "Líquido do dono (R$)", "Carga total"],
               [[c.nome, _r(c.tributos_empresa), _r(c.inss), _r(c.irpf), _r(c.imposto_minimo), _r(c.pro_labore), _r(c.lucros),
                 _r(c.liquido_dono), _r(c.carga_total * 100)] for c in validos],
               ["texto", "reais", "reais", "reais", "reais", "reais", "reais", "reais", "pct"],
               "; ".join(f"{c.nome}: {c.nota}" for c in e.cenarios if c.nota))
    g = Grafico("Quanto sobra para o dono por ano", "barras_h", [c.nome for c in validos],
                {"Líquido": [_r(c.liquido_dono, 0) for c in validos]}, "brl")
    texto = [f"- Melhor regime estimado: **{e.melhor}** ({brl(e.economia_vs_pior)} por ano a mais que o pior)."]
    if e.economia_vs_atual is not None:
        texto.append(f"- Regime atual: {NOMES_REGIME.get(e.regime_atual, e.regime_atual)}; diferença para o melhor: "
                     f"{brl(e.economia_vs_atual)} por ano.")
    texto += [f"- {n}" for n in e.notas]
    return Secao("Empresário: pessoa física × pessoa jurídica", "\n".join(texto), [t], [g])


def secao_acoes(pl: Plano) -> Secao:
    t = Tabela("Plano de ação (prioridade 1 = fazer primeiro)", ["Prioridade", "Ação", "Valor de referência (R$)", "Por quê"],
               [[a[0], a[1], _r(a[2]) if a[2] is not None else None, a[3]] for a in pl.acoes], ["int", "texto", "reais", "texto"])
    return Secao("Plano de ação", "", [t])


def secao_investimentos(pl: Plano) -> Secao | None:
    f = pl.ficha
    from quiron.servicos.carteira.modelo import CLASSES, perfis

    if f.perfil not in perfis():
        return None
    bandas = perfis()[f.perfil]["classes"]
    t = Tabela(f"Alocação de referência do perfil {f.perfil} (%)", ["Classe", "Mínimo", "Alvo", "Máximo"],
               [[CLASSES[c]["nome"], b[0], b[1], b[2]] for c, b in bandas.items() if b[2] > 0], ["texto", "int", "int", "int"],
               "Faixas de config/alocacao_perfis.yaml. Para o diagnóstico da carteira real use a análise carteira_diagnostico"
               + (f" (carteira {f.carteira_id})." if f.carteira_id else "."))
    return Secao("Investimentos", "", [t])


# ---------------------------------------------------------------- montagem
def _base(pl: Plano, titulo: str, tipo_nome: str) -> Relatorio:
    f = pl.ficha
    p = premissas()
    avisos = [f"Ficha incompleta — {x}" for x in f.validar()]
    avisos += [a for a in regras.avisos() if a.startswith(BLOCOS_REGRAS)]
    if not p.get("verificado_em"):
        avisos.append("premissas_planejamento.yaml: NÃO verificado — revise as premissas.")
    rel = Relatorio(titulo, tipo_nome, subtitulo=f"{f.cliente} · {f.idade} anos · {f.uf} · {f.ocupacao} · perfil {f.perfil}",
                    rodape=RODAPE, avisos=avisos)
    rel.premissas = [
        "Valores em R$ de hoje; retornos REAIS (acima da inflação, líquidos de IR e custos): "
        + ", ".join(f"{k} {pct(v, 1)}" for k, v in p["retorno_real_aa"].items())
        + f" a.a.; usufruto {pct(p['retorno_real_usufruto'], 1)} a.a.",
        f"Plano até os {p['expectativa_vida_plano']} anos; probabilidade-alvo {p['sucesso_minimo']:.0%} no Monte Carlo "
        f"({p['simulacoes_monte_carlo']} trajetórias, volatilidade por perfil: "
        + ", ".join(f"{k} {pct(v, 0)}" for k, v in p["volatilidade_aa"].items()) + ").",
        f"Patrimônio da aposentadoria = financeiro − reserva de emergência − já acumulado nos objetivos ({brl(pl.capital_aposentadoria)}).",
        "IR, INSS, Simples, Presumido e ITCMD pelas tabelas de config/regras_mercado.yaml (ITCMD: alíquota máxima da faixa do estado).",
        f"Sucessão: honorários {pct(p['sucessao']['honorarios_inventario'] * 100, 1)} e custas "
        f"{pct(p['sucessao']['custas_inventario'] * 100, 1)} do monte; família mantida por {p['sucessao']['meses_inventario']} meses.",
        f"Proteção: família gasta {p['protecao']['parcela_despesa_familia']:.0%} das despesas sem o titular; "
        f"independência dos filhos aos {p['protecao']['idade_independencia_filhos']} anos; "
        f"graduação {brl(p['protecao']['educacao_superior_por_filho'])} por filho.",
    ]
    rel.fontes = ["📊 Ficha do cliente (quiron-assessoria) — " + f.atualizado_em[:16].replace("T", " "),
                  "📊 Regras tributárias: config/regras_mercado.yaml · premissas: config/premissas_planejamento.yaml",
                  "📊 Cálculos em Python: quiron/servicos/planejamento/"]
    rel.limitacoes = [
        "Estimativas a partir da ficha: confira renda, despesas e patrimônio com documentos antes de apresentar.",
        "Retornos constantes no cenário médio; o Monte Carlo usa distribuição lognormal sem caudas gordas.",
        "Sucessão com um falecimento (titular), sem bens no exterior, testamento ou doações anteriores.",
        "Tributação simplificada (sem carnê-leão detalhado, ganho de capital, dependentes do cônjuge e regras estaduais).",
        "PF × PJ: estimativa para conversar com o contador (enquadramento real depende de CNAE, município e atividade).",
    ]
    return rel


def _fatos(pl: Plano) -> dict[str, Any]:
    f, d, a, s, tr, pr = pl.ficha, pl.diag, pl.apos, pl.suc, pl.trib, pl.prot
    fatos = {
        "cliente": f.cliente, "idade": f.idade, "perfil": f.perfil,
        "renda_liquida_mensal": _r(d.renda.liquida), "despesas_mensais": _r(d.despesas), "parcelas": _r(d.parcelas),
        "sobra_mensal": _r(d.sobra), "taxa_poupanca_pct": _r(d.taxa_poupanca * 100, 1), "aporte_atual": f.aporte_mensal,
        "patrimonio": _r(d.patrimonio), "patrimonio_liquido": _r(d.patrimonio_liquido), "financeiro": _r(d.financeiro),
        "reserva_meta": _r(d.reserva_meta), "investimentos_liquidos": _r(d.reserva_atual),
        "patrimonio_destinado_aposentadoria": _r(pl.capital_aposentadoria),
        "observacao_reserva": "o que passa da reserva de emergência já foi somado ao patrimônio da aposentadoria",
        "objetivos": [{"nome": o.nome, "valor": o.valor, "prazo_anos": o.prazo_anos, "aporte_mensal": _r(o.aporte_mensal)}
                      for o in d.objetivos],
        "total_aportes_necessarios": _r(pl.total_aportes), "diferenca_sobra_aportes": _r(d.sobra - pl.total_aportes),
        "aposentadoria": {"idade": a.idade_aposentadoria, "renda_desejada": a.renda_desejada, "inss": a.inss,
                          "capital_necessario": _r(a.capital_necessario), "capital_projetado": _r(a.capital_projetado),
                          "aporte_necessario_medio": _r(a.aporte_necessario),
                          "aporte_para_85pct": _r(a.aporte_alvo) if a.aporte_alvo is not None else None,
                          "renda_sustentavel_media": _r(a.renda_sustentavel), "renda_sustentavel_85pct": _r(a.renda_alvo),
                          "idade_esgota": _r(a.idade_esgota, 1) if a.idade_esgota else None,
                          "chance_aporte_atual_pct": _r(a.prob_sucesso_atual * 100, 0),
                          "chance_aporte_medio_pct": _r(a.prob_sucesso_necessario * 100, 0),
                          "aporte_viavel": _r(a.aporte_viavel) if a.aporte_viavel is not None else None,
                          "renda_viavel_85pct": _r(a.renda_viavel) if a.renda_viavel is not None else None,
                          "chance_aporte_viavel_pct": _r(a.prob_viavel * 100, 0) if a.prob_viavel is not None else None},
        "protecao": {"necessidade_vida": _r(pr.necessidade_vida), "cobertura_vida": _r(pr.cobertura_vida),
                     "falta_vida": _r(pr.falta_vida), "falta_invalidez": _r(pr.falta_invalidez), "tem_saude": pr.tem_saude},
        "sucessao": {"uf": s.uf, "aliquota_itcmd_pct": _r(s.aliquota_itcmd * 100), "monte": _r(s.monte), "meacao": _r(s.meacao),
                     "heranca": _r(s.heranca), "itcmd": _r(s.itcmd), "custos_inventario": _r(s.custos_inventario),
                     "necessidade_liquidez": _r(s.necessidade_liquidez), "falta_liquidez": _r(s.falta_liquidez)},
        "tributario": {"melhor_declaracao": tr.melhor, "ir_completa": _r(tr.completa.imposto),
                       "ir_simplificada": _r(tr.simplificada.imposto), "pgbl_limite": _r(tr.pgbl_limite),
                       "pgbl_economia": _r(tr.pgbl_economia_adicional), "imposto_minimo": _r(tr.imposto_minimo)},
        "acoes": [{"prioridade": x[0], "acao": x[1], "valor": _r(x[2]) if x[2] is not None else None} for x in pl.acoes],
    }
    if pl.emp:
        fatos["empresario"] = {"regime_atual": NOMES_REGIME.get(pl.emp.regime_atual, "não informado"),
                               "melhor": pl.emp.melhor, "economia_vs_atual": pl.emp.economia_vs_atual,
                               "liquido_por_regime": {c.nome: _r(c.liquido_dono) for c in pl.emp.cenarios if c.aplicavel}}
    return fatos


def _resumo(pl: Plano, partes: tuple[str, ...]) -> list[str]:
    d, a, s, tr, pr = pl.diag, pl.apos, pl.suc, pl.trib, pl.prot
    linhas = []
    if "diagnostico" in partes:
        linhas.append(f"Sobra de {brl(d.sobra)}/mês ({pct(d.taxa_poupanca * 100, 0)} da renda líquida de "
                      f"{brl(d.renda.liquida)}); hoje aporta {brl(pl.ficha.aporte_mensal)}. Os aportes necessários somam "
                      f"{brl(pl.total_aportes)}/mês.")
    if "aposentadoria" in partes:
        linhas.append(f"Aposentadoria aos {a.idade_aposentadoria} com {brl(a.renda_desejada)}/mês: precisa de "
                      f"{brl(a.capital_necessario)}; com o aporte atual chega a {brl(a.capital_projetado)} e a chance de a "
                      f"renda durar até os {a.idade_fim} é {pct(a.prob_sucesso_atual * 100, 0)}."
                      + (f" Para {a.sucesso_alvo:.0%} de chance: aportar {brl(a.aporte_alvo)}/mês." if a.aporte_alvo else ""))
    if "protecao" in partes:
        linhas.append(f"Seguro de vida: necessidade de {brl(pr.necessidade_vida)}, cobertura atual {brl(pr.cobertura_vida)}"
                      + (f" — faltam {brl(pr.falta_vida)}." if pr.falta_vida else " — coberto."))
    if "sucessao" in partes:
        linhas.append(f"Sucessão hoje: ITCMD de {brl(s.itcmd)} e inventário de {brl(s.custos_inventario)} "
                      f"({pct(s.custo_total_pct * 100, 1)} do monte)"
                      + (f"; faltam {brl(s.falta_liquidez)} de liquidez fora do inventário." if s.falta_liquidez
                         else "; a liquidez fora do inventário cobre."))
    if "tributario" in partes:
        linhas.append(f"IR do titular: declaração {tr.melhor.lower()} ({brl(min(tr.completa.imposto, tr.simplificada.imposto))}/ano)"
                      + (f"; PGBL até o limite economiza {brl(tr.pgbl_economia_adicional)}/ano." if tr.pgbl_vale else "."))
    if "empresario" in partes and pl.emp:
        linhas.append(f"Empresa: melhor regime estimado {pl.emp.melhor}"
                      + (f" ({brl(pl.emp.economia_vs_atual)}/ano a mais que o atual)." if pl.emp.economia_vs_atual else "."))
    return linhas


def _relatorio(params: dict[str, Any], modo: str, redigir: bool, titulo: str, tipo_nome: str,
               secoes: tuple[str, ...]) -> Relatorio:
    cliente = fichas.codigo(str(params.get("cliente", "")))
    f = fichas.carregar(cliente)
    pl = montar(f)
    rel = _base(pl, f"{titulo} — {f.cliente}", tipo_nome)
    construtores = {"diagnostico": secao_diagnostico, "objetivos": secao_objetivos, "aposentadoria": secao_aposentadoria,
                    "protecao": secao_protecao, "sucessao": secao_sucessao, "tributario": secao_tributario,
                    "empresario": secao_empresario, "investimentos": secao_investimentos, "acoes": secao_acoes}
    rel.secoes = [s for nome in secoes if (s := construtores[nome](pl))]
    rel.fatos = _fatos(pl)
    rel.resumo = _resumo(pl, secoes)
    rel.parametros = {"cliente": cliente}
    return redacao.redigir(rel, modo) if redigir else rel


COMPLETO = ("acoes", "diagnostico", "objetivos", "aposentadoria", "protecao", "sucessao", "tributario", "empresario",
            "investimentos")


@tipo("planejamento_completo", descricao="Planejamento financeiro completo padrão CFP a partir da ficha do cliente: "
      "diagnóstico, objetivos, aposentadoria (Monte Carlo), proteção, sucessão (ITCMD), tributário, PF × PJ e plano de ação.",
      parametros=PARAMETROS)
def completo(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    return _relatorio(params, modo, redigir, "Planejamento financeiro", "planejamento_completo", COMPLETO)


@tipo("aposentadoria", descricao="Aposentadoria/independência financeira: capital necessário, aporte (médio e com 85% de "
      "chance), renda sustentável, sensibilidade e Monte Carlo.", parametros=PARAMETROS)
def aposentadoria(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    return _relatorio(params, modo, redigir, "Aposentadoria", "aposentadoria", ("aposentadoria", "diagnostico", "objetivos"))


@tipo("sucessao", descricao="Sucessão: meação, herança, ITCMD do estado, custos de inventário, liquidez para os herdeiros "
      "e instrumentos (previdência, seguro, doação, testamento).", parametros=PARAMETROS)
def sucessao(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    return _relatorio(params, modo, redigir, "Planejamento sucessório", "sucessao", ("sucessao", "protecao"))


@tipo("tributario", descricao="Tributário PF: declaração completa × simplificada, PGBL ideal, imposto mínimo de alta "
      "renda e (se houver empresa) PF × PJ.", parametros=PARAMETROS)
def tributario(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    return _relatorio(params, modo, redigir, "Planejamento tributário", "tributario", ("tributario", "empresario"))


@tipo("protecao", descricao="Proteção: seguro de vida pelo método das necessidades, invalidez, reserva de emergência e "
      "saúde.", parametros=PARAMETROS)
def protecao(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    return _relatorio(params, modo, redigir, "Proteção e seguros", "protecao", ("protecao", "diagnostico"))


@tipo("empresario", descricao="Empresário/profissional liberal: PF autônomo × Simples (Anexo III com fator R e Anexo V) × "
      "Lucro Presumido — quanto sobra para o dono em cada regime.", parametros=PARAMETROS)
def empresario(params: dict[str, Any], modo: str = "entregar", redigir: bool = True) -> Relatorio:
    cliente = fichas.carregar(fichas.codigo(str(params.get("cliente", ""))))
    if not cliente.empresa or not cliente.empresa.faturamento_anual:
        raise ValueError("a ficha não tem dados da empresa (faturamento_anual, despesas_anuais, folha_anual)")
    return _relatorio(params, modo, redigir, "Pessoa física × pessoa jurídica", "empresario", ("empresario", "tributario"))
