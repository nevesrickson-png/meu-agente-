"""Fase 11 — valuation (uso interno): extração das contas da CVM, LTM, DCF, custo de capital, múltiplos, DCF reverso
e os relatórios. Sem internet; contas conferíveis à mão."""

import pytest

from quiron.servicos.valuation import cvm_cias, dcf
from quiron.servicos.valuation.cvm_cias import Empresa, Periodo


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))


def linha(dem, cod, nome, valor, escala="MIL"):
    return {"_dem": dem, "CD_CONTA": cod, "DS_CONTA": nome, "VL_CONTA": str(valor), "ESCALA_MOEDA": escala}


def test_extracao_das_contas_padronizadas():
    v = cvm_cias._extrair([
        linha("DRE", "3.01", "Receita", 1000), linha("DRE", "3.05", "EBIT", 200), linha("DRE", "3.06.02", "Despesas Financeiras", -40),
        linha("DRE", "3.08", "IR", -50), linha("DRE", "3.11", "Lucro", 120), linha("DRE", "3.11.01", "Controladores", 110),
        linha("BPA", "1.01.01", "Caixa", 300), linha("BPA", "1.01.02", "Aplicações", 100), linha("BPA", "1.01.03", "Clientes", 150),
        linha("BPA", "1.01.04", "Estoques", 120),
        linha("BPP", "2.01.02", "Fornecedores", 70), linha("BPP", "2.01.04", "Empréstimos", 200), linha("BPP", "2.02.01", "Empréstimos", 400),
        linha("BPP", "2.01.05.02.07", "Arrendamentos", 20), linha("BPP", "2.02.02.02.05", "Arrendamentos", 60),
        linha("BPP", "2.03", "PL", 900), linha("BPP", "2.03.09", "Participação dos Acionistas Não Controladores", 50),
        linha("DFC", "6.01", "Caixa operacional", 250), linha("DFC", "6.01.01.02", "Depreciação, Amortização e Exaustão", 45),
        linha("DFC", "6.01.01.05", "Amortização de custos de captação", 3),  # não é D&A operacional
        linha("DFC", "6.02.02", "Aquisição de Imobilizado", -80), linha("DFC", "6.02.03", "Intangível", -10),
        linha("DFC", "6.02.04", "Recebimento na venda de Ativo Imobilizado", 5),  # venda não é capex
        linha("DFC", "6.03.04", "Pgto de Dividendos/Juros s/ Capital Próprio", -60),
    ])
    assert v["receita"] == 1_000_000 and v["ebit"] == 200_000 and v["lucro_controladores"] == 110_000  # MIL → R$
    assert v["depreciacao"] == 45_000 and v["capex"] == 90_000 and v["dividendos_pagos"] == 60_000
    assert v["arrendamentos"] == 80_000 and v["minoritarios"] == 50_000
    assert v["divida_liquida"] == (600_000 + 80_000) - 400_000
    assert v["ebitda"] == 245_000 and v["capital_giro"] == 150_000 + 120_000 - 70_000


def test_ltm_soma_ano_mais_acumulado_menos_acumulado_anterior():
    ano = Periodo("2025", "2025-12-31", "anual", {"receita": 100.0, "lucro": 10.0, "pl": 50.0})
    ytd = Periodo("2T26 acumulado", "2026-06-30", "ytd", {"receita": 60.0, "lucro": 7.0, "pl": 55.0})
    ytd_ant = Periodo("2T25 acumulado", "2025-06-30", "ytd", {"receita": 50.0, "lucro": 5.0, "pl": 48.0})
    l = cvm_cias.ltm([ano], [ytd, ytd, ytd_ant, ytd_ant])
    assert l["receita"] == 110 and l["lucro"] == 12 and l["pl"] == 55  # balanço do último ITR
    assert cvm_cias.ltm([ano], [])["receita"] == 100


def test_dcf_perpetuidade_sem_crescimento_conferida_a_mao():
    p = dcf.Premissas(crescimento_inicial=0.0, crescimento_perpetuo=0.0, margem_ebit=0.20, aliquota=0.25, capex_receita=0.05,
                      depreciacao_receita=0.05, giro_receita=0.0, roic_perpetuo=0.15, anos=2)
    r = dcf.projetar(100.0, p, 0.10, divida_liquida=50.0, minoritarios=10.0, acoes=10.0)
    # FCFF = 100 × 20% × (1 − 25%) = 15 todo ano; sem crescimento o EV é a perpetuidade 15 ÷ 10% = 150
    assert [x["fcff"] for x in r.projecao] == pytest.approx([15.0, 15.0])
    assert r.ev == pytest.approx(150.0) and r.equity == pytest.approx(90.0) and r.por_acao == pytest.approx(9.0)
    with pytest.raises(ValueError):
        dcf.projetar(100.0, p, 0.002, 0, 0, 1)
    # perpetuidade com crescimento: reinvestimento = g ÷ ROIC
    q = dcf.Premissas(**{**p.__dict__, "crescimento_perpetuo": 0.03})
    r2 = dcf.projetar(100.0, q, 0.10, 0, 0, 1)
    nopat = r2.projecao[-1]["ebit"] * 1.03 * 0.75
    assert r2.valor_terminal == pytest.approx(nopat * (1 - 0.03 / 0.15) / (0.10 - 0.03))


def test_custo_de_capital_conferido_a_mao():
    m = dcf.Mercado(rf_eua=0.04, erp_madura=0.05, risco_pais=0.03, spread_pais=0.02, inflacao_br=0.04, inflacao_eua=0.02,
                    beta_desalavancado=1.0, industria="Teste")
    base = Periodo("LTM", "2026-06-30", "ltm", {"divida_bruta": 0.0, "arrendamentos": 0.0, "ebit": 100.0,
                                                "despesas_financeiras": -10.0})
    cc = dcf.custo_capital(base, 1000.0, m)
    assert cc.beta_alavancado == 1.0 and cc.ke_usd == pytest.approx(0.04 + 0.05 + 0.03)
    assert cc.ke == pytest.approx(1.12 * 1.04 / 1.02 - 1) and cc.wacc == pytest.approx(cc.ke)
    assert cc.cobertura == 10 and cc.rating == "AAA"
    base2 = Periodo("LTM", "", "ltm", {"divida_bruta": 500.0, "arrendamentos": 0.0, "ebit": 100.0, "despesas_financeiras": -50.0})
    cc2 = dcf.custo_capital(base2, 1000.0, m)
    assert cc2.beta_alavancado == pytest.approx(1 + 0.66 * 0.5) and cc2.rating == "BB"  # cobertura 2,0
    assert cc2.peso_equity == pytest.approx(1000 / 1500)


def test_dcf_reverso_e_wacc_implicito_fecham_o_preco():
    p = dcf.Premissas(0.08, 0.04, 0.2, 0.25, 0.05, 0.04, 0.1, 0.15, 10)
    alvo = dcf.projetar(1000.0, p, 0.12, 100.0, 0.0, 10.0).por_acao * 1.5
    g = dcf.dcf_reverso(1000.0, p, 0.12, 100.0, 0.0, 10.0, alvo)
    assert dcf.projetar(1000.0, dcf.Premissas(**{**p.__dict__, "crescimento_inicial": g}), 0.12, 100, 0, 10).por_acao \
        == pytest.approx(alvo, rel=1e-6)
    w = dcf.wacc_implicito(1000.0, p, 100.0, 0.0, 10.0, alvo)
    assert w < 0.12


def test_multiplos_e_escala_de_acoes():
    from quiron.servicos.analise.tipos.valuation import escala_acoes

    base = Periodo("LTM", "", "ltm", {"divida_liquida": 200.0, "minoritarios": 50.0, "pl": 1050.0, "lucro_controladores": 100.0,
                                      "ebitda": 250.0, "receita": 1000.0})
    mu = dcf.multiplos(base, preco=10.0, acoes=150.0, dividendos_12m=0.5)
    assert mu.valor_mercado == 1500 and mu.ev == 1750 and mu.pl == 15 and mu.ev_ebitda == 7.0
    assert mu.p_vp == 1.5 and mu.roe == 0.1 and mu.dy == 0.05 and mu.divida_liquida_ebitda == 0.8
    assert escala_acoes(350_000, 0, 5.47, 3_300_000_000) == (350_000_000, 0, True)  # informado em milhares
    assert escala_acoes(4_197_317_998, 0, 51.45, 18_800_000_000)[2] is False


# ---------------------------------------------------------------- relatórios
def coleta_sintetica(receitas=(800, 900, 1000, 1100), financeira=False):
    from quiron.servicos.analise.tipos.valuation import Coleta

    anuais = []
    for i, r in enumerate(receitas):
        r *= 1e6
        anuais.append(Periodo(str(2022 + i), f"{2022 + i}-12-31", "anual", {
            "receita": r, "ebit": 0.2 * r, "ebitda": 0.24 * r, "depreciacao": 0.04 * r, "capex": 0.06 * r, "lucro": 0.14 * r,
            "lucro_controladores": 0.13 * r, "lair": 0.2 * r, "ir": -0.05 * r, "despesas_financeiras": -0.02 * r, "fco": 0.18 * r,
            "pl": 2 * r, "divida_liquida": 0.3 * r, "divida_bruta": 0.5 * r, "arrendamentos": 0.0, "minoritarios": 0.05 * r,
            "capital_giro": 0.25 * r, "caixa_total": 0.2 * r, "lucro_bruto": 0.4 * r, "resultado_financeiro": -0.01 * r}))
    tri = [Periodo("2T26 acumulado", "2026-06-30", "ytd", dict(anuais[-1].valores)),
           Periodo("2T26", "2026-06-30", "trimestre", {k: v / 4 for k, v in anuais[-1].valores.items()}),
           Periodo("2T25 acumulado", "2025-06-30", "ytd", dict(anuais[-2].valores)),
           Periodo("2T25", "2025-06-30", "trimestre", {k: v / 4 for k, v in anuais[-2].valores.items()})]
    e = Empresa("12345678000199", "999", "TESTE S.A.", "Bancos" if financeira else "Máqs. e Equip.", "Fabrica máquinas.", ["TEST3"])
    return Coleta(e, "TEST3", anuais, tri, cvm_cias.ltm(anuais, tri), 100e6, "2026-06-30", 25.0, 1.0, ["📊 teste"], [])


MERCADO = dcf.Mercado(0.045, 0.045, 0.03, 0.02, 0.035, 0.023, 1.0, "Machinery", ["📊 mercado de teste"])


def test_valuation_dcf_relatorio_completo(tmp_path):
    from quiron.servicos.analise.fila import carregar_tipos
    from quiron.servicos.analise.tipos import valuation as v

    assert {"valuation_dcf", "setor_multiplos", "resultado_trimestral"} <= set(carregar_tipos())
    rel = v.valuation_dcf({"tese": "Vai crescer 20% ao ano."}, coleta=coleta_sintetica(), mercado=MERCADO, beta_reg=0.7,
                          redigir=False)
    f = rel.fatos
    assert f["ticker"] == "TEST3" and f["preco"] == 25.0 and f["beta_regressao"] == 0.7
    assert f["crescimento_inicial_pct"] == pytest.approx(((1100 / 800) ** (1 / 3) - 1) * 100, abs=0.05)
    assert f["margem_ebit_pct"] == 20.0 and f["aliquota_pct"] == 25.0  # efetiva histórica: 5% ÷ 20%
    assert [c["cenario"] for c in f["cenarios"]][:3] == ["Pessimista", "Base", "Otimista"]
    assert f["cenarios"][0]["valor"] < f["cenarios"][1]["valor"] < f["cenarios"][2]["valor"]
    assert f["pontos_para_debate"]["contra_o_preco"] and "Uso interno" in rel.rodape
    assert any(s.titulo == "Tese para debate" for s in rel.secoes)
    assert rel.salvar(tmp_path / "r")["pdf"].stat().st_size > 20_000
    with pytest.raises(ValueError, match="financeira"):
        v.valuation_dcf({}, coleta=coleta_sintetica(financeira=True), mercado=MERCADO, beta_reg=None, redigir=False)


def test_resultado_trimestral_e_setor():
    from quiron.servicos.analise.tipos import valuation as v

    r = v.resultado_trimestral({}, coleta=coleta_sintetica(), redigir=False)
    assert r.fatos["trimestre"] == "2T26" and r.fatos["receita_var_pct"] == pytest.approx(10.0)
    s = v.setor_multiplos({}, coletas=[coleta_sintetica(), coleta_sintetica((500, 600, 700, 800)),
                                         coleta_sintetica((900, 950, 1000, 1050))], redigir=False)
    assert s.fatos["pares"] == ["TEST3", "TEST3"] and s.fatos["mediana_pares"]["pl"] > 0
    assert s.fatos["preco_implicito_pl"] is not None
