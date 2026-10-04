"""Análise: diagnóstico completo de carteira (Fase 8) — usa o motor da Fase 7 (fila → Python → relatório).

Leitura (texto, planilha ou print já convertidos em `Carteira`) → enquadramento no perfil (`config/alocacao_perfis.yaml`)
→ risco (60 meses: volatilidade, VaR/CVaR, drawdown, beta, contribuição, duration) → stress hipotético e histórico
(`config/cenarios_stress.yaml`) → otimização média-variância dentro das bandas → rebalanceamento com IR estimado →
backtest de 10 anos. Toda conta é feita aqui, em Python; o texto é redigido depois a partir dos números.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np

from quiron.servicos.analise import redacao
from quiron.servicos.analise.fila import tipo
from quiron.servicos.analise.relatorio import Grafico, Relatorio, Secao, Tabela, brl, num, pct
from quiron.servicos.carteira import backtest, leitura, otimizacao, rebalanceamento, risco, series, stress
from quiron.servicos.carteira.modelo import CLASSES, ORDEM, Carteira, perfis

PERFIS_VALIDOS = ("conservador", "moderado", "arrojado")


def _p(x: float) -> float:
    """Decimal → % arredondado (para tabelas e fatos)."""
    return round(float(x) * 100, 2)


def obter_carteira(params: dict[str, Any], usar_cerebro: bool = True) -> Carteira:
    if params.get("carteira_id"):
        from quiron.servicos.carteira import arquivo

        c = arquivo.carregar(str(params["carteira_id"]))
    elif params.get("carteira"):
        c = Carteira.de_dict(params["carteira"])
    elif params.get("texto_carteira"):
        c = leitura.ler_texto(str(params["texto_carteira"]), usar_cerebro=usar_cerebro)
    else:
        raise ValueError("informe carteira_id (de ler_carteira), a carteira (dicionário com posicoes) ou texto_carteira")
    if params.get("perfil"):
        c.perfil = str(params["perfil"]).lower().strip()
    if params.get("cliente"):
        c.cliente = str(params["cliente"]).strip()
    if c.cliente and not c.cliente.upper().startswith("CLI-"):
        c.avisos.append("Cliente identificado só por código (CLI-XXX); o nome informado foi descartado.")
        c.cliente = ""
    if any(not p.valor and p.quantidade and p.ticker for p in c.posicoes):
        c = leitura.avaliar(c)
    c.posicoes = [p for p in c.posicoes if p.valor and p.valor > 0]
    if not c.posicoes:
        raise ValueError("a carteira não tem posições com valor")
    if c.perfil not in PERFIS_VALIDOS:
        c.avisos.append(f"Perfil “{c.perfil or 'não informado'}” — usei moderado como referência.")
        c.perfil = "moderado"
    return c


def _enquadramento(pesos: dict[str, float], bandas: dict[str, list[float]]) -> list[list[Any]]:
    linhas = []
    for c in ORDEM:
        mn, alvo, mx = bandas.get(c, [0, 0, 0])
        atual = pesos.get(c, 0.0) * 100
        if atual < mn - 0.05:
            status = f"abaixo ({pct(atual - mn, 1)})"
        elif atual > mx + 0.05:
            status = f"acima (+{pct(atual - mx, 1)})"
        else:
            status = "dentro"
        if atual == 0 and mx == 0:
            continue
        linhas.append([CLASSES[c]["nome"], round(atual, 2), mn, alvo, mx, status])
    return linhas


def montar_relatorio(c: Carteira, s: series.Series, mercado: otimizacao.Mercado, aporte: float = 0.0,
                     hoje: date | None = None) -> Relatorio:
    hoje = hoje or date.today()
    df = s.retornos
    total = c.total
    perfil = perfis()[c.perfil]
    bandas = perfil["classes"]
    pesos = c.pesos_por_classe()
    alvo = {k: bandas[k][1] / 100 for k in ORDEM if k in bandas}
    fora = [l for l in _enquadramento(pesos, bandas) if l[5] != "dentro"]

    # ---- risco (60 meses)
    r, origem = risco.retornos_carteira(c, df)
    m = risco.metricas(r, df["CDI"], df.get("IBOV"))
    contrib = risco.contribuicao_por_classe(c, df)
    dur = risco.duration_carteira(c, hoje)
    maior_risco = max(contrib, key=contrib.get)

    # ---- stress
    hip, hist = stress.rodar(c, df, mercado.pre_3a, mercado.real_7a, hoje)
    selic = next(x for x in hip if x.nome.startswith("Selic +"))
    pior_hip = min(hip, key=lambda x: x.impacto)
    pior_hist = min(hist, key=lambda x: x.impacto) if hist else None

    # ---- otimização (classes do perfil) + pontos de comparação com todas as classes
    otm = otimizacao.otimizar(df, c.perfil, mercado)
    er = otimizacao.retornos_esperados(mercado)
    mu_all = np.array([er[k] / 100 for k in ORDEM])
    cov_all = otimizacao.covariancia(df, ORDEM)

    def stats(w: dict[str, float]) -> tuple[float, float, float]:
        v = np.array([w.get(k, 0.0) for k in ORDEM])
        ret, vol = float(v @ mu_all), float(np.sqrt(v @ cov_all @ v))
        return ret, vol, (ret - otm.cdi) / vol if vol > 0 else 0.0

    w_otima, w_minvar = otm.pesos(otm.max_sharpe), otm.pesos(otm.min_var)
    st = {"Atual": stats(pesos), "Alvo do perfil": stats(alvo), "Mínima variância": stats(w_minvar),
          "Ótima (máx. Sharpe)": stats(w_otima)}

    # ---- rebalanceamento (para o alvo do perfil)
    plano = rebalanceamento.planejar(c, alvo, aporte, hoje)

    # ---- backtest 10 anos
    bt = backtest.rodar(df, {"Atual": pesos, "Alvo do perfil": alvo, "Ótima": w_otima}, meses=120)

    fatos = {
        "cliente": c.cliente or "não informado", "perfil": c.perfil, "patrimonio": round(total, 2),
        "n_posicoes": len(c.posicoes), "aporte": aporte,
        "pesos_atuais_pct": {k: _p(v) for k, v in pesos.items() if v},
        "fora_do_perfil": [{"classe": l[0], "atual_pct": l[1], "faixa": f"{l[2]}–{l[4]}%", "status": l[5]} for l in fora],
        "risco_60m": {"retorno_aa_pct": _p(m.retorno_aa), "vol_aa_pct": _p(m.vol_aa),
                      "sharpe": round(m.sharpe, 2) if m.sharpe is not None else None,
                      "max_drawdown_pct": _p(m.max_drawdown), "var95_mes_pct": _p(m.var95_mes),
                      "cvar95_mes_pct": _p(m.cvar95_mes), "pior_mes_pct": _p(m.pior_mes), "pior_mes": m.pior_mes_quando,
                      "beta_ibov": round(m.beta_ibov, 2) if m.beta_ibov is not None else None,
                      "var95_mes_reais": round(m.var95_mes * total, 2)},
        "contribuicao_risco_pct": {CLASSES[k]["nome"]: _p(v) for k, v in contrib.items() if abs(v) > 1e-4},
        "duration_rf_anos": round(dur["renda_fixa_taxa"], 2), "duration_carteira_anos": round(dur["carteira"], 2),
        "stress_hipotetico": [{"cenario": x.nome, "impacto_reais": round(x.impacto, 2), "impacto_pct": _p(x.impacto_pct),
                               "efeito_12m_reais": round(x.em_12_meses, 2)} for x in hip],
        "selic_mais_3": {"impacto_reais": round(selic.impacto, 2), "impacto_pct": _p(selic.impacto_pct),
                         "carregamento_12m_reais": round(selic.em_12_meses, 2),
                         "liquido_12m_reais": round(selic.impacto + selic.em_12_meses, 2),
                         "por_posicao": [{"posicao": i.nome, "impacto_reais": round(i.impacto, 2)} for i in selic.posicoes]},
        "stress_historico": [{"episodio": x.nome, "impacto_reais": round(x.impacto, 2), "impacto_pct": _p(x.impacto_pct)}
                             for x in hist],
        "mercado": {"cdi_esperado": round(mercado.cdi_esperado, 2), "pre_3a": round(mercado.pre_3a, 2),
                    "juro_real_7a": round(mercado.real_7a, 2), "ipca_esperado": round(mercado.ipca_esperado, 2)},
        "otimizacao": {n: {"retorno_esperado_pct": _p(v[0]), "vol_pct": _p(v[1]), "sharpe": round(v[2], 2)}
                       for n, v in st.items()},
        "pesos_otima_pct": {k: _p(v) for k, v in w_otima.items() if v > 1e-4},
        "rebalanceamento": {"ir_estimado": round(plano.ir_total, 2), "aporte_usado": round(plano.aporte_usado, 2),
                            "aporte_para_alvo_sem_vender": round(plano.aporte_sem_vender, 2),
                            "classe_que_limita": CLASSES[plano.classe_limitante]["nome"] if plano.classe_limitante else "",
                            "ordens": [{"acao": o.acao, "alvo": o.alvo, "valor": round(o.valor, 2), "ir": round(o.ir, 2)}
                                       for o in plano.ordens]},
        "backtest_10a": {b.nome: {"retorno_aa_pct": _p(b.metricas.retorno_aa), "vol_pct": _p(b.metricas.vol_aa),
                                  "max_drawdown_pct": _p(b.metricas.max_drawdown)} for b in bt},
    }

    nome_cart = c.cliente or c.nome
    rel = Relatorio(
        f"Diagnóstico de carteira — {nome_cart} ({c.perfil})",
        "carteira_diagnostico",
        subtitulo=f"{brl(total)} em {len(c.posicoes)} posições · referência: perfil {c.perfil}",
        fatos=fatos,
        resumo=[
            (f"Enquadramento: {len(fora)} classe(s) fora da faixa do perfil {c.perfil} — "
             + "; ".join(f"{l[0]} {pct(l[1], 1)} ({l[5]})" for l in fora) + ".") if fora
            else f"Enquadramento: todas as classes dentro das faixas do perfil {c.perfil}.",
            f"Risco (60 meses): volatilidade {pct(m.vol_aa * 100)} a.a., pior queda acumulada {pct(m.max_drawdown * 100)}, "
            f"VaR 95% de {pct(m.var95_mes * 100)} ao mês (≈ {brl(m.var95_mes * total)}). "
            f"{CLASSES[maior_risco]['nome']} responde por {pct(contrib[maior_risco] * 100, 1)} do risco "
            f"com {pct(pesos[maior_risco] * 100, 1)} do patrimônio.",
            f"Stress {selic.nome}: {'perda' if selic.impacto < 0 else 'ganho'} de {brl(abs(selic.impacto))} "
            f"({pct(selic.impacto_pct * 100)}) no instante, puxada por "
            + ", ".join(f"{i.nome} ({brl(abs(i.impacto))})" for i in sorted(selic.posicoes, key=lambda i: i.impacto)[:2])
            + f"; em compensação, o pós-fixado passa a render cerca de {brl(selic.em_12_meses)} a mais em 12 meses.",
            f"Pior cenário hipotético: {pior_hip.nome} ({pct(pior_hip.impacto_pct * 100)})"
            + (f"; pior episódio histórico: {pior_hist.nome} ({pct(pior_hist.impacto_pct * 100)})." if pior_hist else "."),
            f"Retorno esperado (premissas): atual {pct(st['Atual'][0] * 100)} a.a. com vol {pct(st['Atual'][1] * 100)}; "
            f"carteira ótima dentro do perfil {pct(st['Ótima (máx. Sharpe)'][0] * 100)} com vol "
            f"{pct(st['Ótima (máx. Sharpe)'][1] * 100)}.",
            f"Rebalancear para o alvo do perfil: IR estimado {brl(plano.ir_total)}"
            + (f", usando o aporte de {brl(aporte)}" if aporte else "")
            + (f"; sem vender nada, seria preciso aportar {brl(plano.aporte_sem_vender)} (limitado por "
               f"{CLASSES[plano.classe_limitante]['nome']})." if plano.classe_limitante else "."),
        ],
        premissas=[
            f"Perfil de referência: {c.perfil} — {perfil.get('descricao', '')} Faixas em config/alocacao_perfis.yaml "
            "(proposta inicial, ajuste à sua política).",
            "Risco com 60 meses de retornos mensais: cada posição usa o histórico do próprio ticker (≥ 24 meses); sem "
            "histórico, a proxy da classe (pós-fixado = CDI; prefixado/IPCA+ = índices sintéticos de duration "
            "constante a partir das taxas do Tesouro; multimercado = 70% CDI + 30% Ibovespa; FII = cesta de 5 FIIs; "
            "internacional = S&P 500 em reais).",
            f"Mercado hoje: CDI esperado {pct(mercado.cdi_esperado)} a.a., prefixado ~3 anos {pct(mercado.pre_3a)}, "
            f"juro real ~7 anos {pct(mercado.real_7a)}, IPCA esperado {pct(mercado.ipca_esperado)}.",
            "Retornos esperados por classe (opinião declarada, config/premissas_carteira.yaml): "
            + "; ".join(f"{CLASSES[k]['nome']} {pct(er[k])}" for k in ORDEM) + ".",
            "Stress hipotético: renda fixa = −duration modificada × choque de taxa; ações = beta histórico × choque da "
            "bolsa; FII/multimercado = choque da classe; exterior e cripto combinados com o dólar. Choques em "
            "config/cenarios_stress.yaml.",
            "Otimização: média-variância (covariância de 60 meses com encolhimento de 20%), dentro das faixas do perfil.",
            "Rebalanceamento: aporte primeiro nas classes abaixo do alvo; vendas começando pelo menor IR por real "
            "(prejuízo, isentos, isenção de R$ 20 mil/mês em ações); previdência não é vendida.",
            "Backtest: 120 meses, rebalanceamento mensal, sem custos nem impostos.",
        ],
        fontes=s.fontes + mercado.fontes + ["📊 Faixas, premissas e cenários: config/alocacao_perfis.yaml, "
                                            "premissas_carteira.yaml, cenarios_stress.yaml",
                                            "📊 Regras de IR: config/regras_mercado.yaml"],
        limitacoes=[
            "Risco medido com dados mensais: subestima quedas intramês e risco de liquidez.",
            "Proxies de classe não capturam o risco específico do ativo (crédito do emissor, gestor do fundo).",
            "Stress hipotético é linear (sem convexidade nem correlações dinâmicas); históricos usam a carteira de hoje.",
            "Retornos esperados são premissas: a otimização é sensível a elas — use como referência, não como verdade.",
            "IR e liquidez do rebalanceamento são estimativas: confira custos, carências e datas na corretora.",
            "Backtest olha para trás; desempenho passado não garante resultado futuro.",
        ],
        avisos=c.avisos + s.avisos + mercado.avisos + plano.avisos,
    )

    # ---- seções
    posicoes = Tabela("Posições", ["Posição", "Classe", "Valor (R$)", "Peso", "Série usada no risco"],
                      [[p.nome, CLASSES[p.classe]["nome"], round(p.valor, 2), _p(p.valor / total), origem.get(p.nome, "")]
                       for p in sorted(c.posicoes, key=lambda p: -p.valor)],
                      ["texto", "texto", "reais", "pct", "texto"])
    enq = Tabela(f"Enquadramento no perfil {c.perfil} (% do patrimônio)",
                 ["Classe", "Atual", "Mínimo", "Alvo", "Máximo", "Situação"],
                 _enquadramento(pesos, bandas), ["texto", "pct", "int", "int", "int", "texto"])
    classes_g = [k for k in ORDEM if pesos.get(k) or alvo.get(k)]
    g_aloc = Grafico("Alocação atual × alvo do perfil", "barras_h", [CLASSES[k]["nome"] for k in classes_g],
                     {"Atual": [_p(pesos.get(k, 0)) for k in classes_g], "Alvo": [_p(alvo.get(k, 0)) for k in classes_g]},
                     "pct")

    def opc(v: float | None) -> str:
        return num(v) if v is not None else "—"

    t_risco = Tabela("Métricas de risco (60 meses)", ["Métrica", "Valor"], [
        ["Retorno anualizado", pct(m.retorno_aa * 100)], ["Volatilidade anual", pct(m.vol_aa * 100)],
        ["Índice de Sharpe (sobre o CDI)", opc(m.sharpe)],
        ["Pior queda acumulada (drawdown)", f"{pct(m.max_drawdown * 100)} ({m.inicio_dd} a {m.fundo_dd})"],
        ["VaR 95% mensal (histórico)", f"{pct(m.var95_mes * 100)} (≈ {brl(m.var95_mes * total)})"],
        ["VaR 95% mensal (paramétrico)", pct(m.var95_param * 100)],
        ["CVaR 95% mensal (perda média nos piores 5%)", pct(m.cvar95_mes * 100)],
        ["Pior mês", f"{pct(m.pior_mes * 100)} ({m.pior_mes_quando})"],
        ["Meses negativos", pct(m.meses_negativos * 100, 0)],
        ["Beta em relação ao Ibovespa", opc(m.beta_ibov)],
        ["Duration da renda fixa com taxa (anos)", num(dur["renda_fixa_taxa"])],
        ["Duration da carteira toda (anos)", num(dur["carteira"])]],
        ["texto", "texto"], f"VaR 95%: em 1 de cada 20 meses a perda pode passar disso. Período: {m.meses} meses até {r.index[-1]}.")
    classes_c = [k for k in ORDEM if pesos.get(k) or abs(contrib.get(k, 0)) > 1e-4]
    g_contrib = Grafico("Peso no patrimônio × parcela do risco", "barras_h", [CLASSES[k]["nome"] for k in classes_c],
                        {"Peso": [_p(pesos.get(k, 0)) for k in classes_c],
                         "Parcela do risco": [_p(contrib.get(k, 0)) for k in classes_c]}, "pct",
                        nota="Parcela do risco = contribuição de cada classe para a variância total da carteira.")

    t_hip = Tabela("Cenários hipotéticos (choque instantâneo)", ["Cenário", "Impacto (R$)", "Impacto", "Efeito em 12 meses (R$)"],
                   [[x.nome, round(x.impacto, 2), _p(x.impacto_pct), round(x.em_12_meses, 2)] for x in hip],
                   ["texto", "reais", "pct", "reais"],
                   "Efeito em 12 meses: o pós-fixado passa a render mais (ou menos) com a nova Selic.")
    t_selic = Tabela(f"Detalhe: {selic.nome}", ["Posição", "Valor (R$)", "Impacto (R$)", "Como foi calculado"],
                     [[i.nome, round(i.valor, 2), round(i.impacto, 2), i.regra] for i in selic.posicoes],
                     ["texto", "reais", "reais", "texto"], next(
                         (v["descricao"] for v in stress.cenarios()["hipoteticos"].values() if v["nome"] == selic.nome), ""))
    g_hip = Grafico("Impacto dos cenários no patrimônio", "barras_h", [x.nome for x in hip] + [x.nome for x in hist],
                    {"Impacto": [_p(x.impacto_pct) for x in hip] + [_p(x.impacto_pct) for x in hist]}, "pct",
                    nota="Hipotéticos (choque instantâneo) e episódios históricos (carteira de hoje no período).")
    t_hist = Tabela("Episódios históricos (carteira de hoje)", ["Episódio", "Período", "Impacto (R$)", "Impacto"],
                    [[x.nome, x.descricao, round(x.impacto, 2), _p(x.impacto_pct)] for x in hist],
                    ["texto", "texto", "reais", "pct"])

    classes_o = [k for k in ORDEM if pesos.get(k) or alvo.get(k) or w_otima.get(k, 0) > 1e-4]
    t_otm = Tabela("Alocações por classe (%)", ["Classe", "Atual", "Alvo do perfil", "Mínima variância", "Ótima (máx. Sharpe)"],
                   [[CLASSES[k]["nome"], _p(pesos.get(k, 0)), _p(alvo.get(k, 0)), _p(w_minvar.get(k, 0)),
                     _p(w_otima.get(k, 0))] for k in classes_o], ["texto", "pct", "pct", "pct", "pct"])
    t_st = Tabela("Retorno esperado e risco (premissas)", ["Carteira", "Retorno esperado a.a.", "Volatilidade a.a.", "Sharpe"],
                  [[n, _p(v[0]), _p(v[1]), round(v[2], 2)] for n, v in st.items()], ["texto", "pct", "pct", "num"])
    g_front = Grafico("Fronteira eficiente dentro do perfil", "dispersao", [],
                      {"Fronteira eficiente": [_p(y) for _, y in otm.fronteira],
                       **{n: [_p(v[0])] for n, v in st.items() if n != "Mínima variância"}},
                      "pct", "volatilidade a.a.",
                      "Cada ponto da curva é a menor volatilidade para um retorno esperado, respeitando as faixas do perfil.",
                      x={"Fronteira eficiente": [_p(x) for x, _ in otm.fronteira],
                         **{n: [_p(v[1])] for n, v in st.items() if n != "Mínima variância"}}, formato_x="pct")

    t_ordens = Tabela("Ordens sugeridas para chegar ao alvo do perfil", ["Ação", "Posição / classe", "Valor (R$)",
                                                                         "Ganho (R$)", "IR estimado (R$)", "Regra"],
                      [[o.acao, o.alvo, round(o.valor, 2), round(o.ganho, 2) if o.acao == "vender" else None,
                        round(o.ir, 2) if o.acao == "vender" else None, o.nota] for o in plano.ordens],
                      ["texto", "texto", "reais", "reais", "reais", "texto"],
                      "Desvios de até 1 p.p. não geram ordem. Compras indicam a classe; o produto fica a seu critério.")
    t_final = Tabela("Pesos depois do rebalanceamento (%)", ["Classe", "Antes", "Depois", "Alvo"],
                     [[CLASSES[k]["nome"], _p(pesos.get(k, 0)), _p(plano.pesos_finais.get(k, 0)), _p(alvo.get(k, 0))]
                      for k in ORDEM if pesos.get(k) or alvo.get(k)], ["texto", "pct", "pct", "pct"])

    t_bt = Tabela("Backtest de 10 anos (rebalanceamento mensal, sem custos)",
                  ["Carteira", "Retorno a.a.", "Volatilidade a.a.", "Pior queda", "Sharpe"],
                  [[b.nome, _p(b.metricas.retorno_aa), _p(b.metricas.vol_aa), _p(b.metricas.max_drawdown),
                    round(b.metricas.sharpe, 2) if b.metricas.sharpe is not None else None] for b in bt],
                  ["texto", "pct", "pct", "pct", "num"],
                  f"De {bt[0].retornos.index[0]} a {bt[0].retornos.index[-1]}. Alocações por classe, usando as proxies.")
    idx = [str(p) for p in bt[0].retornos.index]
    passo = 3
    g_bt = Grafico("R$ 100 aplicados há 10 anos", "linhas", idx[::passo],
                   {b.nome: [round(100 * v, 1) for v in b.acumulado.values[::passo]] for b in bt}, "num", "mês")

    rel.secoes = [
        Secao("Composição e enquadramento", "", [posicoes, enq], [g_aloc]),
        Secao("Risco", "", [t_risco], [g_contrib]),
        Secao("Stress test", "", [t_hip, t_selic, t_hist], [g_hip]),
        Secao("Otimização", "", [t_otm, t_st], [g_front]),
        Secao("Rebalanceamento", "", [t_ordens, t_final] if plano.ordens else [t_final]),
        Secao("Backtest", "", [t_bt], [g_bt]),
    ]
    return rel


@tipo("carteira_diagnostico",
      descricao="Diagnóstico completo de uma carteira: enquadramento no perfil, risco (volatilidade, VaR, drawdown, "
                "beta, duration), stress test (Selic ±3 p.p., bolsa −20%, dólar +20%, inflação e crises históricas), "
                "otimização dentro do perfil, rebalanceamento com IR estimado e backtest de 10 anos.",
      parametros={"carteira_id": "id devolvido por ler_carteira (ex.: CART-20261004-101500) ou 'ultima' — preferido",
                  "carteira": "dicionário {nome, cliente (CLI-XXX), perfil, posicoes: [{nome, classe, valor, ticker, "
                              "quantidade, tipo, custo, data_aplicacao, vencimento, taxa}]} — use ler_carteira para montar",
                  "texto_carteira": "alternativa: a carteira em texto livre (uma posição por linha)",
                  "perfil": "conservador | moderado | arrojado (padrão: o da carteira ou moderado)",
                  "cliente": "código CLI-XXX (nunca nome)",
                  "aporte": "valor novo em R$ para usar no rebalanceamento (padrão 0)"})
def diagnostico(params: dict[str, Any], modo: str = "entregar", mercado: otimizacao.Mercado | None = None,
                dados: series.Series | None = None, hoje: date | None = None, redigir: bool = True) -> Relatorio:
    c = obter_carteira(params, usar_cerebro=redigir)
    aporte = float(params.get("aporte") or 0)
    if aporte < 0:
        raise ValueError("aporte não pode ser negativo")
    dados = dados or series.carregar([p.ticker for p in c.posicoes if p.ticker])
    mercado = mercado or otimizacao.mercado_atual()
    rel = montar_relatorio(c, dados, mercado, aporte, hoje)
    rel.parametros = {**params, "carteira": c.como_dict()}
    rel.parametros.pop("texto_carteira", None)
    return redacao.redigir(rel, modo) if redigir else rel
