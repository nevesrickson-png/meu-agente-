"""Valuation de empresas (Fase 11) — USO INTERNO E DE ESTUDO (relatório de análise para terceiros é exclusivo de CNPI,
Resolução CVM 20). Dados oficiais da CVM (DFP/ITR/FCA) + preço (brapi/Yahoo) + custo de capital (Treasury, Damodaran,
Focus). Toda premissa sai com a fonte ou a conta que a gerou.

- valuation_dcf: raio-X (histórico, margens, múltiplos), custo de capital, projeção, DCF com ponte até o valor por
  ação, cenários, sensibilidade WACC × g, DCF reverso (crescimento e custo de capital implícitos) e tese para debate;
- setor_multiplos: a empresa contra os pares do setor (múltiplos, margens, crescimento, preço implícito pela mediana);
- resultado_trimestral: o último trimestre contra o mesmo trimestre do ano anterior (e o acumulado do ano).
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from quiron.servicos.analise import redacao
from quiron.servicos.analise.fila import tipo
from quiron.servicos.analise.relatorio import Grafico, Relatorio, Secao, Tabela, brl, pct
from quiron.servicos.valuation import cvm_cias, dcf
from quiron.servicos.valuation.cvm_cias import Empresa, Periodo

RODAPE = "Uso interno — não constitui relatório de análise (Resolução CVM 20) nem recomendação de investimento."
MI = 1e6


def _p(v: float | None, casas: int = 2) -> float | None:
    return None if v is None else round(float(v) * 100, casas)


def _mi(v: float | None) -> float | None:
    return None if v is None else round(float(v) / MI, 1)


def bi(v: float) -> str:
    """Valor grande legível: R$ 40,1 bi / R$ 850,3 mi."""
    a = abs(v)
    if a >= 1e9:
        return ("−" if v < 0 else "") + f"R$ {a / 1e9:.1f} bi".replace(".", ",")
    if a >= 1e6:
        return ("−" if v < 0 else "") + f"R$ {a / 1e6:.1f} mi".replace(".", ",")
    return brl(v)


def _fmt_mi(v: float | None) -> str:
    return "—" if v is None else f"{v / MI:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _n2(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _x(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}x".replace(".", ",")


# ---------------------------------------------------------------- coleta
@dataclass
class Coleta:
    empresa: Empresa
    ticker: str
    anuais: list[Periodo]
    trimestrais: list[Periodo]
    base: Periodo
    acoes: float
    data_acoes: str
    preco: float
    dividendos_12m: float | None
    fontes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _preco(ticker: str) -> tuple[float, str]:
    from quiron.servicos.mercado import cotacoes

    c = cotacoes.cotacao(ticker)
    return float(c.preco), getattr(c, "fonte", "brapi/Yahoo Finance")


def _dividendos(ticker: str) -> float | None:
    try:
        import pandas as pd
        import yfinance as yf

        d = yf.Ticker(f"{ticker}.SA").dividends
        return float(d[d.index > d.index.max() - pd.Timedelta(days=365)].sum()) if not d.empty else None
    except Exception:  # noqa: BLE001
        return None


def escala_acoes(total: float, tesouraria: float, preco: float, pl_controladores: float) -> tuple[float, float, bool]:
    """Algumas companhias informam a composição do capital em MILHARES de ações (sem indicar no arquivo): se o valor
    de mercado der menos de 2% do patrimônio (P/VP impossível), multiplica por 1.000."""
    if pl_controladores > 0 and (total - tesouraria) * preco / pl_controladores < 0.02:
        return total * 1000, tesouraria * 1000, True
    return total, tesouraria, False


def coletar(termo: str, anos: int = 5) -> Coleta:
    e = cvm_cias.empresa(termo)
    ticker = termo.strip().upper() if termo.strip().upper() in e.tickers else e.ticker
    if not ticker:
        raise cvm_cias.EmpresaNaoEncontrada(f"{e.nome} não tem ação negociada em bolsa no FCA")
    anuais, tri, avisos = cvm_cias.demonstracoes(e.cnpj, anos)
    base = cvm_cias.ltm(anuais, tri)
    total, tes, data = cvm_cias.acoes(e.cnpj)
    preco, fonte_p = _preco(ticker)
    total, tes, corrigiu = escala_acoes(total, tes, preco, base["pl"] - base["minoritarios"])
    if corrigiu:
        avisos.append("Quantidade de ações informada à CVM em milhares (P/VP impossível): multipliquei por 1.000.")
    fontes = [f"📊 {cvm_cias.FONTE} — DFP {anuais[0].rotulo}–{anuais[-1].rotulo}"
              + (f" e ITR até {tri[0].fim[8:10]}/{tri[0].fim[5:7]}/{tri[0].fim[:4]}" if tri else ""),
              f"📊 CVM — composição do capital em {data[8:10]}/{data[5:7]}/{data[:4]}",
              f"📊 {fonte_p} — cotação de {ticker}: {brl(preco)}"]
    if len(e.tickers) > 1:
        avisos.append(f"Mais de uma classe de ação ({', '.join(e.tickers)}): valor por ação calculado sobre o total de "
                      f"ações; o preço usado é o de {ticker}.")
    return Coleta(e, ticker, anuais, tri, base, total - tes, data, preco, _dividendos(ticker), fontes, avisos)


def beta_regressao(ticker: str) -> float | None:
    """β de 60 meses contra o Ibovespa (Yahoo, preços ajustados) — visão alternativa ao β de setor."""
    try:
        import pandas as pd

        from quiron.servicos.carteira.series import yahoo_mensal

        a, b = yahoo_mensal(f"{ticker}.SA"), yahoo_mensal("^BVSP")
        df = pd.concat([a, b], axis=1).dropna().tail(60)
        if len(df) < 36:
            return None
        return float(np.cov(df.iloc[:, 0], df.iloc[:, 1])[0, 1] / df.iloc[:, 1].var())
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- seções comuns
def tabela_historico(col: Coleta) -> Tabela:
    linhas = []
    for p in col.anuais + [col.base]:
        rec = p["receita"]
        linhas.append([p.rotulo, _mi(rec), _mi(p["ebitda"]), _mi(p["ebit"]), _mi(p["lucro_controladores"]),
                       _p(p["ebitda"] / rec if rec else None, 1), _p(p["lucro_controladores"] / rec if rec else None, 1),
                       _mi(p["capex"]), _mi(p["fco"]), _mi(p["divida_liquida"])])
    return Tabela("Histórico (R$ milhões)", ["Período", "Receita", "EBITDA", "EBIT", "Lucro (controladores)", "Margem EBITDA",
                                              "Margem líquida", "Capex", "Caixa operacional", "Dívida líquida"], linhas,
                  ["texto", "num", "num", "num", "num", "pct", "pct", "num", "num", "num"],
                  "EBITDA = EBIT + depreciação/amortização (DFC). Dívida líquida inclui arrendamentos e desconta caixa e "
                  "aplicações. Fonte: DFP/ITR consolidados na CVM.")


def tabela_multiplos(col: Coleta, mu: dcf.Multiplos) -> Tabela:
    return Tabela(f"Múltiplos e rentabilidade (preço {brl(col.preco)}, {col.base.rotulo})", ["Indicador", "Valor"], [
        ["Valor de mercado (R$ mi)", f"{_mi(mu.valor_mercado):,.0f}".replace(",", ".")],
        ["Valor da firma — EV (R$ mi)", f"{_mi(mu.ev):,.0f}".replace(",", ".")],
        ["P/L", _x(mu.pl)], ["EV/EBITDA", _x(mu.ev_ebitda)], ["P/VP", _x(mu.p_vp)],
        ["Dividend yield 12m", pct(mu.dy * 100) if mu.dy is not None else "—"],
        ["ROE", pct(mu.roe * 100) if mu.roe is not None else "—"],
        ["Margem EBITDA", pct(mu.margem_ebitda * 100) if mu.margem_ebitda is not None else "—"],
        ["Margem líquida", pct(mu.margem_liquida * 100) if mu.margem_liquida is not None else "—"],
        ["Dívida líquida / EBITDA", _x(mu.divida_liquida_ebitda)]], ["texto", "texto"],
        f"Ações em circulação: {col.acoes:,.0f} (sem tesouraria).".replace(",", "."))


def _base_relatorio(titulo: str, tipo_nome: str, col: Coleta) -> Relatorio:
    e = col.empresa
    rel = Relatorio(titulo, tipo_nome, subtitulo=f"{col.ticker} · {e.setor} · {e.segmento or 'segmento não informado'}",
                    rodape=RODAPE, avisos=list(col.avisos))
    rel.fontes = list(col.fontes)
    rel.limitacoes = ["Demonstrações padronizadas da CVM: itens não recorrentes não são ajustados automaticamente.",
                      "Contas variáveis (depreciação, capex, arrendamentos) são achadas pelo nome — confira nas notas.",
                      "Uso interno e de estudo: não é relatório de análise nem recomendação (Resolução CVM 20)."]
    return rel


# ---------------------------------------------------------------- valuation_dcf
@tipo("valuation_dcf", descricao="Valuation de empresa listada (USO INTERNO): raio-X com dados da CVM, múltiplos, custo de "
      "capital (Treasury, Damodaran, Focus), DCF de 10 anos, cenários, sensibilidade WACC × g, DCF reverso e tese para debate.",
      parametros={"empresa": "ticker (WEGE3), CNPJ ou nome", "tese": "opcional: a tese a ser debatida/contestada",
                  "crescimento_inicial": "opcional, decimal (padrão: CAGR de 3 anos)", "margem_ebit": "opcional, decimal",
                  "setor_damodaran": "opcional: indústria do Damodaran para o beta (padrão: pelo setor da CVM)"})
def valuation_dcf(params: dict[str, Any], modo: str = "entregar", coleta: Coleta | None = None,
                  mercado: dcf.Mercado | None = None, beta_reg: float | None = -1.0, redigir: bool = True) -> Relatorio:
    termo = str(params.get("empresa") or params.get("ticker") or "").strip()
    if not termo and coleta is None:
        raise ValueError("informe a empresa (ticker, CNPJ ou nome)")
    col = coleta or coletar(termo)
    e = col.empresa
    if cvm_cias.financeira(e, col.anuais):
        raise ValueError(f"{e.nome} é instituição financeira: o DCF da firma não se aplica (use P/L, P/VP e ROE em "
                         "setor_multiplos)")
    cfg = dcf.config()
    industria = dcf.industria_damodaran(e, str(params.get("setor_damodaran") or ""))
    m = mercado or dcf.mercado_atual(industria)
    h = dcf.historico(col.anuais, int(cfg["projecao"]["anos_historico"]))
    base = col.base
    vm = col.preco * col.acoes
    cc = dcf.custo_capital(base, vm, m)
    ajustes = {k: float(params[k]) for k in ("crescimento_inicial", "margem_ebit") if params.get(k) not in (None, "")}
    p = dcf.premissas_base(h, m, cc.wacc, ajustes)
    dl, mino = base["divida_liquida"], base["minoritarios"]
    res = dcf.projetar(base["receita"], p, cc.wacc, dl, mino, col.acoes)
    upside = res.por_acao / col.preco - 1
    # cenários
    cen = []
    for nome, d in cfg["projecao"]["cenarios"].items():
        q = dcf.Premissas(**{**p.__dict__, "crescimento_inicial": p.crescimento_inicial + d["crescimento"],
                             "margem_ebit": p.margem_ebit + d["margem"]})
        r = dcf.projetar(base["receita"], q, cc.wacc, dl, mino, col.acoes)
        cen.append([nome.capitalize(), _p(q.crescimento_inicial, 1), _p(q.margem_ebit, 1), round(r.por_acao, 2),
                    _p(r.por_acao / col.preco - 1, 1)])
    cen.insert(1, ["Base", _p(p.crescimento_inicial, 1), _p(p.margem_ebit, 1), round(res.por_acao, 2), _p(upside, 1)])
    br = beta_regressao(col.ticker) if beta_reg == -1.0 else beta_reg
    alt = None
    if br is not None:
        m_alt = dcf.Mercado(**{**m.__dict__, "beta_desalavancado": br / (1 + (1 - 0.34) * cc.divida / vm) if vm else br})
        cc_alt = dcf.custo_capital(base, vm, m_alt)
        p_alt = dcf.premissas_base(h, m_alt, cc_alt.wacc, ajustes)
        alt = (br, cc_alt, dcf.projetar(base["receita"], p_alt, cc_alt.wacc, dl, mino, col.acoes))
        cen.append([f"β de regressão ({_n2(br)})", _p(p_alt.crescimento_inicial, 1),
                    _p(p_alt.margem_ebit, 1), round(alt[2].por_acao, 2), _p(alt[2].por_acao / col.preco - 1, 1)])
    passos_w = (-0.04, -0.02, -0.01, 0.0, 0.01)
    sens = dcf.sensibilidade(base["receita"], p, cc.wacc, dl, mino, col.acoes, passos_wacc=passos_w)
    g_impl = dcf.dcf_reverso(base["receita"], p, cc.wacc, dl, mino, col.acoes, col.preco)
    w_impl = dcf.wacc_implicito(base["receita"], p, dl, mino, col.acoes, col.preco)
    mu = dcf.multiplos(base, col.preco, col.acoes, col.dividendos_12m)
    # pontos para debate: fatos calculados que sustentam os dois lados (a redação não pode ignorar nenhum)
    a_favor, contra = [], []
    if alt and alt[2].por_acao > res.por_acao:
        a_favor.append(f"Com o β de regressão de 60 meses ({_n2(br)}) no lugar do β de setor ({_n2(cc.beta_alavancado)}), o WACC "
                       f"cai para {pct(alt[1].wacc * 100)} e o valor sobe para {brl(alt[2].por_acao)}.")
    if w_impl:
        lado = a_favor if w_impl < cc.wacc else contra
        lado.append(f"O preço embute WACC de {pct(w_impl * 100)} contra {pct(cc.wacc * 100)} estimado: o mercado "
                    + ("aceita um custo de capital bem menor (qualidade, previsibilidade, receita em dólar)." if w_impl < cc.wacc
                       else "exige retorno maior que o estimado."))
    if h.roic > cc.wacc:
        a_favor.append(f"ROIC histórico de {pct(h.roic * 100, 1)} acima do WACC: crescer cria valor.")
    else:
        contra.append(f"ROIC histórico de {pct(h.roic * 100, 1)} abaixo do WACC: crescer destrói valor.")
    if g_impl and g_impl > h.cagr_receita * 1.5:
        contra.append(f"Para o preço fechar com o WACC estimado, a receita teria de crescer {pct(g_impl * 100, 1)} no início, "
                      f"contra CAGR histórico de {pct(h.cagr_receita * 100, 1)}.")
    if upside < 0:
        contra.append(f"Mesmo o cenário otimista ({brl(cen[2][3])}) fica abaixo do preço de {brl(col.preco)}.")
    contra.append(f"P/L de {_x(mu.pl)} e EV/EBITDA de {_x(mu.ev_ebitda)}: pouca margem para decepção nos resultados.")
    if res.peso_terminal > 0.6:
        contra.append(f"{pct(res.peso_terminal * 100, 0)} do valor está na perpetuidade: o resultado depende muito do longo prazo.")

    rel = _base_relatorio(f"Valuation (uso interno) — {e.nome} ({col.ticker})", "valuation_dcf", col)
    rel.fontes += m.fontes + ["📊 Premissas de projeção e tabela de rating sintético: config/valuation.yaml"]
    rel.avisos += m.avisos
    if not cfg.get("verificado_em"):
        rel.avisos.append("valuation.yaml: premissas NÃO revisadas — confira antes de usar.")
    tese = str(params.get("tese") or "").strip()
    rel.fatos = {
        "empresa": e.nome, "ticker": col.ticker, "setor": e.setor, "preco": round(col.preco, 2),
        "valor_por_acao_base": round(res.por_acao, 2), "upside_pct": _p(upside, 1),
        "cenarios": [{"cenario": c[0], "valor": c[3], "upside_pct": c[4]} for c in cen],
        "wacc_pct": _p(cc.wacc), "ke_pct": _p(cc.ke), "kd_liquido_pct": _p(cc.kd_liquido), "beta": round(cc.beta_alavancado, 2),
        "beta_regressao": round(br, 2) if br is not None else None,
        "crescimento_inicial_pct": _p(p.crescimento_inicial, 1), "crescimento_perpetuo_pct": _p(p.crescimento_perpetuo, 2),
        "margem_ebit_pct": _p(p.margem_ebit, 1), "aliquota_pct": _p(p.aliquota, 1), "roic_historico_pct": _p(h.roic, 1),
        "peso_valor_terminal_pct": _p(res.peso_terminal, 0), "ev_mi": _mi(res.ev), "equity_mi": _mi(res.equity),
        "crescimento_implicito_pct": _p(g_impl, 1), "wacc_implicito_pct": _p(w_impl, 2),
        "pl": round(mu.pl, 1) if mu.pl else None, "ev_ebitda": round(mu.ev_ebitda, 1) if mu.ev_ebitda else None,
        "p_vp": round(mu.p_vp, 1) if mu.p_vp else None, "roe_pct": _p(mu.roe, 1), "dy_pct": _p(mu.dy, 2),
        "tese_do_analista": tese or None,
        "pontos_para_debate": {"a_favor_do_preco": a_favor, "contra_o_preco": contra},
    }
    rel.resumo = [
        f"DCF base: {brl(res.por_acao)} por ação contra {brl(col.preco)} na bolsa ({pct(upside * 100, 1)}), com WACC de "
        f"{pct(cc.wacc * 100)} e {pct(res.peso_terminal * 100, 0)} do valor na perpetuidade.",
        f"Cenários: pessimista {brl(cen[0][3])}, otimista {brl(cen[2][3])}"
        + (f"; com o β de regressão ({_n2(br)}) o valor vai a {brl(alt[2].por_acao)} (WACC {pct(alt[1].wacc * 100)})."
           if alt else "."),
        (f"O preço de hoje embute custo de capital de {pct(w_impl * 100)}" if w_impl else "O preço não é alcançado com WACC razoável")
        + (f" ou crescimento inicial de {pct(g_impl * 100, 1)} ao ano." if g_impl else "."),
        f"Múltiplos: P/L {_x(mu.pl)}, EV/EBITDA {_x(mu.ev_ebitda)}, P/VP {_x(mu.p_vp)}, ROE "
        f"{pct(mu.roe * 100, 1) if mu.roe else '—'}.",
    ]
    rel.premissas = [
        f"Base: {base.rotulo} (receita {bi(base['receita'])}); projeção de {p.anos} anos, fluxos descontados no fim de cada ano.",
        f"Crescimento: de {pct(p.crescimento_inicial * 100, 1)} (CAGR da receita em {len(h.anos) - 1 if len(h.anos) <= 4 else 3} "
        f"anos{', ajustado' if 'crescimento_inicial' in ajustes else ''}) até {pct(p.crescimento_perpetuo * 100)} na perpetuidade "
        f"(IPCA de longo prazo + {pct(cfg['projecao']['crescimento_real_perpetuidade'] * 100, 1)} real).",
        f"Margem EBIT {pct(p.margem_ebit * 100, 1)}, capex {pct(p.capex_receita * 100, 1)} e depreciação "
        f"{pct(p.depreciacao_receita * 100, 1)} da receita, capital de giro {pct(p.giro_receita * 100, 1)} da receita "
        f"incremental — médias de {cfg['projecao']['anos_historico']} anos.",
        f"IR/CSLL {pct(p.aliquota * 100, 1)} (efetiva histórica; nominal 34%). ROIC na perpetuidade "
        f"{pct(p.roic_perpetuo * 100, 1)} (reinvestimento = g ÷ ROIC).",
        f"Custo de capital em US$ convertido para R$ pela inflação (Focus {pct(m.inflacao_br * 100)} × EUA "
        f"{pct(m.inflacao_eua * 100)}); β de setor ({industria}) realavancado pela estrutura de mercado.",
    ]
    rel.limitacoes += [
        "Valor muito sensível ao WACC e à perpetuidade — veja a tabela de sensibilidade e o DCF reverso.",
        "Médias históricas não capturam mudanças de ciclo, aquisições ou novos negócios.",
        "Não modela opções reais, ativos não operacionais nem contingências fora do balanço.",
    ]
    # tabelas
    t_cc = Tabela("Custo de capital (WACC)", ["Componente", "Valor", "Fonte / conta"], [
        ["Treasury 10 anos (US$)", pct(m.rf_eua * 100), "Yahoo Finance ^TNX"],
        ["ERP de mercado maduro", pct(m.erp_madura * 100), "Damodaran (ctryprem): ERP do Brasil − risco-país"],
        ["Risco-país (Brasil)", pct(m.risco_pais * 100), "Damodaran (ctryprem)"],
        ["β desalavancado do setor", f"{m.beta_desalavancado:.2f}".replace(".", ","), f"Damodaran emergentes — {industria}"],
        ["β alavancado", f"{cc.beta_alavancado:.2f}".replace(".", ","),
         f"β_u × (1 + (1 − 34%) × D/E); D/E = {pct(cc.divida / cc.valor_mercado * 100, 1)} a mercado"],
        ["Custo do capital próprio (US$)", pct(cc.ke_usd * 100), "Rf + β × ERP madura + risco-país"],
        ["Custo do capital próprio (R$)", pct(cc.ke * 100), "(1 + Ke US$) × (1 + IPCA LP) ÷ (1 + inflação EUA) − 1"],
        ["Cobertura de juros e rating sintético", f"{_x(cc.cobertura)} → {cc.rating}", "EBIT ÷ despesas financeiras (LTM)"],
        ["Custo da dívida líquido (R$)", pct(cc.kd_liquido * 100), "(Rf + spread país + spread rating) em R$ × (1 − 34%)"],
        ["Peso do capital próprio", pct(cc.peso_equity * 100, 1), "valor de mercado ÷ (valor de mercado + dívida + arrendamentos)"],
        ["WACC", pct(cc.wacc * 100), "média ponderada"]], ["texto", "texto", "texto"])
    t_proj = Tabela("Projeção (R$ milhões)", ["Ano", "Crescimento", "Receita", "EBIT", "NOPAT", "Depreciação", "Capex",
                                              "Capital de giro", "FCFF", "Valor presente"],
                    [[x["ano"], _p(x["crescimento"], 1), _mi(x["receita"]), _mi(x["ebit"]), _mi(x["nopat"]),
                      _mi(x["depreciacao"]), _mi(-x["capex"]), _mi(-x["capital_giro"]), _mi(x["fcff"]), _mi(x["vp"])]
                     for x in res.projecao], ["int", "pct", "num", "num", "num", "num", "num", "num", "num", "num"])
    t_ponte = Tabela("Do valor da firma ao valor por ação", ["Item", "R$ milhões"], [
        ["Valor presente dos fluxos (10 anos)", _mi(res.vp_fluxos)], ["Valor presente da perpetuidade", _mi(res.vp_terminal)],
        ["Valor da firma (EV)", _mi(res.ev)], ["(−) Dívida líquida (com arrendamentos)", _mi(-dl)],
        ["(−) Participação de minoritários", _mi(-mino)], ["Valor do capital próprio", _mi(res.equity)],
        ["Ações em circulação (milhões)", round(col.acoes / MI, 1)], ["Valor por ação (R$)", round(res.por_acao, 2)],
        ["Preço na bolsa (R$)", round(col.preco, 2)]], ["texto", "num"])
    t_cen = Tabela("Cenários", ["Cenário", "Crescimento inicial", "Margem EBIT", "Valor por ação (R$)", "Upside"], cen,
                   ["texto", "pct", "pct", "num", "pct"],
                   "Pessimista/otimista: deslocamentos de config/valuation.yaml. β de regressão: 60 meses contra o Ibovespa.")
    gs = [p.crescimento_perpetuo + d for d in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    t_debate = Tabela("Pontos para debate (calculados)", ["Lado", "Argumento"],
                      [["A favor do preço", x] for x in a_favor] + [["Contra o preço", x] for x in contra], ["texto", "texto"])
    t_sens = Tabela("Sensibilidade: valor por ação (R$) — WACC × crescimento na perpetuidade",
                    ["WACC \\ g", *[pct(g * 100) for g in gs]],
                    [[pct(l[0] * 100), *[round(v, 2) if v is not None else None for v in l[1:]]] for l in sens],
                    ["texto"] + ["num"] * 5)
    t_rev = Tabela("DCF reverso: o que o preço de hoje embute", ["Pergunta", "Resposta"], [
        ["Crescimento inicial da receita implícito (demais premissas iguais)", pct(g_impl * 100, 1) if g_impl else "fora do intervalo"],
        ["Custo de capital implícito (demais premissas iguais)", pct(w_impl * 100) if w_impl else "fora do intervalo"],
        ["Crescimento histórico (CAGR 3 anos)", pct(h.cagr_receita * 100, 1)], ["WACC estimado", pct(cc.wacc * 100)]],
        ["texto", "texto"])
    g_hist = Grafico("Receita e EBITDA (R$ milhões)", "barras_h", [p_.rotulo for p_ in col.anuais],
                     {"Receita": [_mi(p_["receita"]) for p_ in col.anuais], "EBITDA": [_mi(p_["ebitda"]) for p_ in col.anuais]}, "num")
    g_fcff = Grafico("Fluxo de caixa livre projetado (R$ milhões)", "linhas", [str(x["ano"]) for x in res.projecao],
                     {"FCFF": [_mi(x["fcff"]) for x in res.projecao], "Valor presente": [_mi(x["vp"]) for x in res.projecao]},
                     "num", "ano")
    g_cen = Grafico("Valor por ação por cenário × preço", "barras_h", [c[0] for c in cen] + ["Preço na bolsa"],
                    {"R$ por ação": [c[3] for c in cen] + [round(col.preco, 2)]}, "brl")
    secoes = [Secao("Raio-X", f"**{e.nome}** — {e.descricao[:600]}" if e.descricao else "", [tabela_historico(col),
                                                                                             tabela_multiplos(col, mu)], [g_hist]),
              Secao("Custo de capital", "", [t_cc]),
              Secao("Projeção e valor", "", [t_proj, t_ponte], [g_fcff]),
              Secao("Cenários, sensibilidade e DCF reverso", "", [t_cen, t_sens, t_rev, t_debate], [g_cen])]
    if tese:
        secoes.append(Secao("Tese para debate", f"> {tese}\n\nConfronte a tese com o DCF reverso: o preço de hoje exige "
                                                  "as premissas da tabela acima."))
    _com_perfil(rel, secoes, col)
    rel.secoes = secoes
    rel.parametros = {"empresa": col.ticker, **{k: v for k, v in params.items() if k != "empresa"}}
    return redacao.redigir(rel, modo) if redigir else rel


def _com_perfil(rel: Relatorio, secoes: list, col: Coleta) -> None:
    """Abre o relatório com o perfil da companhia (atividades, sede, controle, acionistas, controladas, empregados)."""
    try:
        from quiron.servicos.valuation import perfil

        p = perfil.perfil(col.empresa)
    except Exception as e:  # noqa: BLE001 — sem perfil o relatório sai do mesmo jeito
        logging.info("relatório sem perfil da empresa (%s)", type(e).__name__)
        return
    secoes.insert(0, perfil.secao(p))
    rel.fatos["perfil"] = perfil.fatos(p)
    rel.fontes += [f for f in p.fontes if f not in rel.fontes]


# ---------------------------------------------------------------- setor_multiplos
@tipo("setor_multiplos", descricao="Empresa contra os pares do setor (USO INTERNO): P/L, EV/EBITDA, P/VP, ROE, margens, "
      "crescimento e dívida, com a mediana do grupo e o preço implícito pelos múltiplos medianos.",
      parametros={"empresa": "ticker, CNPJ ou nome", "pares": "opcional: lista de tickers dos pares (padrão: mesmo setor na CVM)"})
def setor_multiplos(params: dict[str, Any], modo: str = "entregar", coletas: list[Coleta] | None = None,
                    redigir: bool = True) -> Relatorio:
    if coletas is None:
        alvo = coletar(str(params.get("empresa") or ""))
        pares = params.get("pares") or []
        if isinstance(pares, str):
            pares = [x for x in pares.replace(";", ",").replace(" ", ",").split(",") if x]
        if not pares:
            pares = [x.ticker for x in cvm_cias.setor_pares(alvo.empresa, 6)]
        coletas = [alvo]
        for t in pares[:7]:
            try:
                coletas.append(coletar(t, anos=2))
            except Exception as e:  # noqa: BLE001
                alvo.avisos.append(f"{t}: fora do comparativo ({type(e).__name__}).")
    alvo = coletas[0]
    linhas, mults = [], []
    for c in coletas:
        mu = dcf.multiplos(c.base, c.preco, c.acoes, c.dividendos_12m)
        cresc = None
        if len(c.anuais) >= 2 and c.anuais[-2]["receita"] > 0:
            cresc = c.anuais[-1]["receita"] / c.anuais[-2]["receita"] - 1
        mults.append(mu)
        linhas.append([c.ticker, _mi(mu.valor_mercado), mu.pl, mu.ev_ebitda, mu.p_vp, _p(mu.roe, 1), _p(mu.margem_ebitda, 1),
                       _p(cresc, 1), mu.divida_liquida_ebitda, _p(mu.dy, 2)])
    pares_m = mults[1:]

    def mediana(attr: str) -> float | None:
        vals = [getattr(x, attr) for x in pares_m if getattr(x, attr) is not None and getattr(x, attr) > 0]
        return float(np.median(vals)) if vals else None

    med = {a: mediana(a) for a in ("pl", "ev_ebitda", "p_vp")}
    b = alvo.base
    impl_pl = med["pl"] * b["lucro_controladores"] / alvo.acoes if med["pl"] and b["lucro_controladores"] > 0 else None
    impl_ev = ((med["ev_ebitda"] * b["ebitda"] - b["divida_liquida"] - b["minoritarios"]) / alvo.acoes
               if med["ev_ebitda"] and b["ebitda"] > 0 else None)
    rel = _base_relatorio(f"Setor e múltiplos (uso interno) — {alvo.ticker}", "setor_multiplos", alvo)
    for c in coletas[1:]:
        rel.fontes += [f for f in c.fontes if "cotação" in f]
        rel.avisos += [f"{c.ticker}: {a}" for a in c.avisos]
    rel.fatos = {"empresa": alvo.ticker, "pares": [c.ticker for c in coletas[1:]],
                 "mediana_pares": {k: round(v, 1) if v else None for k, v in med.items()},
                 "alvo": {"pl": round(mults[0].pl, 1) if mults[0].pl else None,
                          "ev_ebitda": round(mults[0].ev_ebitda, 1) if mults[0].ev_ebitda else None,
                          "p_vp": round(mults[0].p_vp, 1) if mults[0].p_vp else None},
                 "preco": round(alvo.preco, 2), "preco_implicito_pl": round(impl_pl, 2) if impl_pl else None,
                 "preco_implicito_ev_ebitda": round(impl_ev, 2) if impl_ev else None}
    rel.resumo = [f"{alvo.ticker}: P/L {_x(mults[0].pl)} e EV/EBITDA {_x(mults[0].ev_ebitda)} contra medianas de "
                  f"{_x(med['pl'])} e {_x(med['ev_ebitda'])} dos pares ({', '.join(c.ticker for c in coletas[1:]) or 'nenhum'}).",
                  (f"Preço implícito pelos múltiplos medianos: {brl(impl_pl) if impl_pl else '—'} (P/L) e "
                   f"{brl(impl_ev) if impl_ev else '—'} (EV/EBITDA), contra {brl(alvo.preco)} na bolsa.")]
    rel.premissas = ["Múltiplos com o LTM de cada empresa (DFP + ITR da CVM) e a cotação do dia.",
                     "Pares: mesmo setor de atividade no cadastro da CVM, ou a lista informada.",
                     "Mediana ignora múltiplos negativos (prejuízo/EBITDA negativo)."]
    t = Tabela("Comparativo", ["Ticker", "Valor de mercado (R$ mi)", "P/L", "EV/EBITDA", "P/VP", "ROE", "Margem EBITDA",
                               "Crescimento da receita", "DL/EBITDA", "DY 12m"],
               [[l[0], l[1], *[round(v, 1) if v is not None else None for v in l[2:5]], l[5], l[6], l[7],
                 round(l[8], 1) if l[8] is not None else None, l[9]] for l in linhas],
               ["texto", "num", "num", "num", "num", "pct", "pct", "pct", "num", "pct"])
    g = Grafico("EV/EBITDA", "barras_h", [l[0] for l in linhas if l[3]], {"EV/EBITDA": [round(l[3], 1) for l in linhas if l[3]]},
                "num")
    rel.secoes = [Secao("Comparativo do setor", "", [t], [g] if g.rotulos else [])]
    rel.parametros = {k: v for k, v in params.items()}
    return redacao.redigir(rel, modo) if redigir else rel


# ---------------------------------------------------------------- resultado_trimestral
@tipo("resultado_trimestral", descricao="Último resultado trimestral (ITR na CVM) contra o mesmo trimestre do ano anterior e "
      "o acumulado do ano: receita, EBIT, lucro, margens, caixa operacional, dívida e alavancagem (USO INTERNO).",
      parametros={"empresa": "ticker, CNPJ ou nome"})
def resultado_trimestral(params: dict[str, Any], modo: str = "entregar", coleta: Coleta | None = None,
                         redigir: bool = True) -> Relatorio:
    col = coleta or coletar(str(params.get("empresa") or ""), anos=2)
    if len(col.trimestrais) < 4:
        raise ValueError("ainda não há ITR mais recente que o último balanço anual — use valuation_dcf")
    ytd, tri, ytd_ant, tri_ant = col.trimestrais

    def var(a: float, b: float) -> float | None:
        return a / b - 1 if b else None

    def margem(p: Periodo, k: str) -> float | None:
        return p[k] / p["receita"] if p["receita"] else None

    itens = [("Receita", "receita"), ("Lucro bruto", "lucro_bruto"), ("EBIT", "ebit"), ("Resultado financeiro", "resultado_financeiro"),
             ("Lucro (controladores)", "lucro_controladores")]
    t_tri = Tabela(f"{tri.rotulo} × {tri_ant.rotulo} (R$ milhões)", ["Linha", tri.rotulo, tri_ant.rotulo, "Variação"],
                   [[n, _mi(tri[k]), _mi(tri_ant[k]), _p(var(tri[k], tri_ant[k]), 1)] for n, k in itens]
                   + [["Margem bruta", _p(margem(tri, "lucro_bruto"), 1), _p(margem(tri_ant, "lucro_bruto"), 1), None],
                      ["Margem EBIT", _p(margem(tri, "ebit"), 1), _p(margem(tri_ant, "ebit"), 1), None],
                      ["Margem líquida", _p(margem(tri, "lucro_controladores"), 1), _p(margem(tri_ant, "lucro_controladores"), 1), None]],
                   ["texto", "num", "num", "pct"], "Margens em % (colunas de valor).")
    itens_ytd = itens + [("EBITDA", "ebitda"), ("Caixa operacional", "fco"), ("Capex", "capex")]
    t_ytd = Tabela(f"Acumulado: {ytd.rotulo} × {ytd_ant.rotulo} (R$ milhões)", ["Linha", "Atual", "Ano anterior", "Variação"],
                   [[n, _mi(ytd[k]), _mi(ytd_ant[k]), _p(var(ytd[k], ytd_ant[k]), 1)] for n, k in itens_ytd],
                   ["texto", "num", "num", "pct"])
    b = col.base
    t_bal = Tabela("Balanço e alavancagem (R$ milhões)", ["Indicador", "Atual", "Fim do ano anterior"], [
        ["Dívida bruta + arrendamentos", _fmt_mi(ytd["divida_bruta"] + ytd["arrendamentos"]),
         _fmt_mi(ytd_ant["divida_bruta"] + ytd_ant["arrendamentos"])],
        ["Caixa e aplicações", _fmt_mi(ytd["caixa_total"]), _fmt_mi(ytd_ant["caixa_total"])],
        ["Dívida líquida", _fmt_mi(ytd["divida_liquida"]), _fmt_mi(ytd_ant["divida_liquida"])],
        ["Dívida líquida / EBITDA (12 meses)", _x(b["divida_liquida"] / b["ebitda"]) if b["ebitda"] > 0 else "—", "—"],
        ["Patrimônio líquido", _fmt_mi(ytd["pl"]), _fmt_mi(ytd_ant["pl"])]], ["texto", "texto", "texto"])
    rel = _base_relatorio(f"Resultado {tri.rotulo} (uso interno) — {col.empresa.nome} ({col.ticker})", "resultado_trimestral", col)
    rel.fatos = {"empresa": col.ticker, "trimestre": tri.rotulo,
                 "receita_tri_mi": _mi(tri["receita"]), "receita_var_pct": _p(var(tri["receita"], tri_ant["receita"]), 1),
                 "ebit_tri_mi": _mi(tri["ebit"]), "ebit_var_pct": _p(var(tri["ebit"], tri_ant["ebit"]), 1),
                 "lucro_tri_mi": _mi(tri["lucro_controladores"]),
                 "lucro_var_pct": _p(var(tri["lucro_controladores"], tri_ant["lucro_controladores"]), 1),
                 "margem_ebit_pct": _p(margem(tri, "ebit"), 1), "margem_ebit_ant_pct": _p(margem(tri_ant, "ebit"), 1),
                 "fco_ytd_mi": _mi(ytd["fco"]), "divida_liquida_mi": _mi(ytd["divida_liquida"]),
                 "dl_ebitda": round(b["divida_liquida"] / b["ebitda"], 2) if b["ebitda"] > 0 else None}
    rel.resumo = [f"{tri.rotulo}: receita {bi(tri['receita'])} ({pct((var(tri['receita'], tri_ant['receita']) or 0) * 100, 1)} "
                  f"contra {tri_ant.rotulo}); EBIT {bi(tri['ebit'])}; lucro {bi(tri['lucro_controladores'])} "
                  f"({pct((var(tri['lucro_controladores'], tri_ant['lucro_controladores']) or 0) * 100, 1)}).",
                  f"Margem EBIT {pct((margem(tri, 'ebit') or 0) * 100, 1)} contra {pct((margem(tri_ant, 'ebit') or 0) * 100, 1)} "
                  f"um ano antes; dívida líquida {bi(ytd['divida_liquida'])}."]
    rel.premissas = ["Trimestre isolado = demonstração de 3 meses do ITR; acumulado = desde janeiro.",
                     "Comparação com o mesmo período do ano anterior, como reapresentado no próprio ITR."]
    rel.secoes = [Secao("Resultado do trimestre", "", [t_tri, t_ytd, t_bal])]
    _com_perfil(rel, rel.secoes, col)
    rel.parametros = {k: v for k, v in params.items()}
    return redacao.redigir(rel, modo) if redigir else rel
