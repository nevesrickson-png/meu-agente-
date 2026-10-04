"""Fase 8 — carteira: leitura, risco, stress, otimização, rebalanceamento com IR, backtest e o relatório completo.
Sem internet: séries sintéticas (determinísticas) e mercado fixo; as contas principais são conferíveis à mão."""

import asyncio
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quiron.servicos.analise.relatorio import Grafico, desenhar
from quiron.servicos.carteira import arquivo, backtest, leitura, otimizacao, rebalanceamento, risco, stress
from quiron.servicos.carteira.modelo import Carteira, Posicao, _data, classe_por_ticker, perfis
from quiron.servicos.carteira.series import Series

HOJE = date(2026, 10, 4)
MERCADO = otimizacao.Mercado(cdi_esperado=12.0, pre_3a=13.5, real_7a=7.0, ipca_esperado=4.5,
                             fontes=["📊 teste — mercado fixo"])


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def series_sinteticas() -> Series:
    idx = pd.period_range("2007-01", "2026-09", freq="M")
    g = np.random.default_rng(42)
    n = len(idx)
    df = pd.DataFrame(index=idx)
    df["CDI"] = 0.008
    df["IPCA"] = 0.004
    df["PRE3"] = 0.009 + g.normal(0, 0.008, n)
    df["IPCA7"] = 0.009 + g.normal(0, 0.015, n)
    df["IBOV"] = 0.008 + g.normal(0, 0.06, n)
    df["USD"] = 0.002 + g.normal(0, 0.035, n)
    df["SPX"] = 0.008 + g.normal(0, 0.04, n)
    df["BTC"] = 0.03 + g.normal(0, 0.2, n)
    df["SPX_BRL"] = (1 + df["SPX"]) * (1 + df["USD"]) - 1
    df["BTC_BRL"] = (1 + df["BTC"]) * (1 + df["USD"]) - 1
    df["MULTI"] = 0.7 * df["CDI"] + 0.3 * df["IBOV"]
    df["FII"] = 0.008 + g.normal(0, 0.03, n)
    return Series(df, ["📊 teste — séries sintéticas"], [])


def carteira_teste() -> Carteira:
    return Carteira("Teste", [
        Posicao("CDB 110% CDI", "pos_fixado", 100_000, tipo="cdb", custo=90_000, data_aplicacao=date(2025, 10, 4)),
        Posicao("Tesouro Prefixado", "prefixado", 50_000, tipo="tesouro_prefixado", vencimento=date(2029, 10, 4)),
        Posicao("Tesouro IPCA+", "inflacao", 50_000, tipo="tesouro_ipca", vencimento=date(2033, 10, 4)),
        Posicao("Ações (fundo)", "acoes", 40_000, tipo="fundo", custo=30_000),
        Posicao("FII", "fii", 20_000, custo=25_000),
        Posicao("Multimercado", "multimercado", 20_000, tipo="fundo"),
        Posicao("IVVB11", "internacional", 20_000, ticker="IVVB11", tipo="etf", custo=15_000),
    ], perfil="moderado", cliente="CLI-900")


# ---------------------------------------------------------------- leitura
def test_leitura_numeros_datas_classes_e_mascara():
    assert leitura.numero("120 mil") == 120_000 and leitura.numero("R$ 1,2 mi") == 1_200_000
    assert leitura.numero("R$ 45.000,50") == 45_000.5 and leitura.numero("2 milhões") == 2_000_000
    assert _data("2027-08") == date(2027, 8, 15) and _data("08/2027") == date(2027, 8, 15) and _data("2035") == date(2035, 12, 31)
    assert classe_por_ticker("PETR4") == "acoes" and classe_por_ticker("HGLG11") == "fii"
    assert classe_por_ticker("IVVB11") == "internacional" and classe_por_ticker("TAEE11") == "acoes"
    texto, n = leitura.mascarar_identificadores("CPF 123.456.789-09, e-mail a@b.com, CDB 50 mil")
    assert n == 2 and "123.456" not in texto and "a@b.com" not in texto and "50 mil" in texto


def test_leitura_por_regras_e_planilha():
    c = leitura.ler_por_regras("CDB Banco X 110% CDI R$ 50 mil venc 2027\nPETR4 200\nLCA 94% CDI R$ 30.000")
    assert [p.classe for p in c.posicoes] == ["pos_fixado", "acoes", "pos_fixado"]
    assert c.posicoes[0].valor == 50_000 and c.posicoes[0].vencimento == date(2027, 12, 31)
    assert c.posicoes[1].ticker == "PETR4" and c.posicoes[1].quantidade == 200 and c.posicoes[2].isento
    csv = "Ativo;Valor;Custo;Vencimento\nTesouro IPCA+ 2035;90.000,00;85.000,00;15/05/2035\nHGLG11;44.370;48.000;\nTotal;134.370;;\n"
    p = leitura.ler_planilha(csv.encode(), "carteira.csv")
    assert [x.nome for x in p.posicoes] == ["Tesouro IPCA+ 2035", "HGLG11"]
    assert p.posicoes[0].classe == "inflacao" and p.posicoes[0].valor == 90_000 and p.posicoes[0].vencimento == date(2035, 5, 15)
    assert p.posicoes[1].classe == "fii" and p.posicoes[1].custo == 48_000 and p.posicoes[1].ticker == "HGLG11"
    j = leitura._do_json({"perfil": "vazio", "cliente": "Maria", "posicoes": [{"nome": "PETR4 - Petrobras", "valor": "10 mil"}]})
    assert j.perfil == "" and j.cliente == "" and j.posicoes[0].ticker == "PETR4" and j.posicoes[0].valor == 10_000


def test_carteira_guardada_por_id():
    c = carteira_teste()
    ident = arquivo.salvar(c)
    assert ident.startswith("CART-") and arquivo.carregar(ident).total == c.total
    assert arquivo.carregar("ultima").cliente == "CLI-900"
    assert "Pós-fixado" in arquivo.descrever(c, ident) and "R$ 300.000,00" in arquivo.descrever(c, ident)
    with pytest.raises(ValueError):
        arquivo.carregar("../../etc/passwd")


def test_perfis_somam_100_e_bandas_coerentes():
    for nome, p in perfis().items():
        assert sum(b[1] for b in p["classes"].values()) == 100, nome
        assert all(b[0] <= b[1] <= b[2] for b in p["classes"].values()), nome


# ---------------------------------------------------------------- risco
def test_metricas_conferidas_a_mao():
    idx = pd.period_range("2021-01", periods=24, freq="M")
    m = risco.metricas(pd.Series(0.01, index=idx))
    assert m.retorno_aa == pytest.approx(1.01 ** 12 - 1) and m.vol_aa == 0 and m.max_drawdown == 0
    r = pd.Series([0.10, -0.10, 0.05, -0.20, 0.30] + [0.0] * 19, index=idx)
    m = risco.metricas(r)
    # pico em 1,10; fundo em 1,10 × 0,9 × 1,05 × 0,8 = 0,8316 → drawdown 0,8316/1,10 − 1 = −24,4%
    assert m.max_drawdown == pytest.approx(0.8316 / 1.10 - 1) and m.pior_mes == pytest.approx(-0.20)
    assert m.pior_mes_quando == "2021-04"


def test_duration_e_contribuicao_ao_risco():
    c = carteira_teste()
    d = risco.duration_carteira(c, HOJE)
    prazo_pre, prazo_ipca = 1096 / 365.25, 2557 / 365.25
    assert d["renda_fixa_taxa"] == pytest.approx((prazo_pre + prazo_ipca) / 2)
    contrib = risco.contribuicao_por_classe(c, series_sinteticas().retornos)
    assert sum(contrib.values()) == pytest.approx(1.0) and all(isinstance(v, float) for v in contrib.values())
    assert contrib["pos_fixado"] == pytest.approx(0.0, abs=1e-9)  # CDI constante não tem risco
    assert max(contrib, key=contrib.get) == "acoes"


# ---------------------------------------------------------------- stress
def test_stress_selic_mais_3_conferido_a_mao():
    c = carteira_teste()
    df = series_sinteticas().retornos
    hip, hist = stress.rodar(c, df, taxa_pre=13.5, taxa_real=7.0, hoje=HOJE)
    s = next(x for x in hip if x.nome == "Selic +3 p.p.")
    por = {i.nome: i for i in s.posicoes}
    prazo_pre, prazo_ipca = 1096 / 365.25, 2557 / 365.25
    assert por["CDB 110% CDI"].impacto == 0 and por["CDB 110% CDI"].em_12_meses == pytest.approx(3_000)
    assert por["Tesouro Prefixado"].impacto == pytest.approx(-50_000 * prazo_pre / 1.135 * 0.03)
    assert por["Tesouro IPCA+"].impacto == pytest.approx(-50_000 * prazo_ipca / 1.07 * 0.015)
    beta = risco.betas(c, df)[3]
    assert beta == pytest.approx(1.0)  # sem ticker: a própria proxy (Ibovespa)
    assert por["Ações (fundo)"].impacto == pytest.approx(-4_000)
    assert por["FII"].impacto == pytest.approx(-1_600) and por["Multimercado"].impacto == pytest.approx(-400)
    assert por["IVVB11"].impacto == pytest.approx(1_000)  # exterior 0% com dólar +5%
    assert s.impacto == pytest.approx(sum(i.impacto for i in s.posicoes)) and s.impacto < 0
    corte = next(x for x in hip if x.nome.startswith("Selic −"))
    assert corte.impacto == pytest.approx(-s.impacto)  # choques simétricos
    assert {x.nome for x in hist} >= {"Crise de 2008", "Covid-19 (2020)"}
    covid = next(x for x in hist if x.nome.startswith("Covid"))
    janela = df.loc[pd.Period("2020-02", "M"):pd.Period("2020-03", "M")]
    assert por["CDB 110% CDI"].valor * ((1 + janela["CDI"]).prod() - 1) == pytest.approx(covid.posicoes[0].impacto)


# ---------------------------------------------------------------- otimização, rebalanceamento e backtest
def test_otimizacao_respeita_bandas_do_perfil():
    df = series_sinteticas().retornos
    o = otimizacao.otimizar(df, "moderado", MERCADO)
    bandas = perfis()["moderado"]["classes"]
    for w in (o.max_sharpe, o.min_var):
        assert w.sum() == pytest.approx(1.0)
        for c, x in o.pesos(w).items():
            assert bandas[c][0] / 100 - 1e-6 <= x <= bandas[c][2] / 100 + 1e-6, c
    assert o.stats(o.max_sharpe)[2] >= o.stats(o.min_var)[2] - 1e-9
    assert o.stats(o.min_var)[1] <= o.stats(o.max_sharpe)[1] + 1e-9
    vols = [v for v, _ in o.fronteira]
    assert len(vols) == 15 and o.fronteira[0][1] < o.fronteira[-1][1]
    er = otimizacao.retornos_esperados(MERCADO)
    assert er["acoes"] == pytest.approx(17.0) and er["inflacao"] == pytest.approx((1.07 * 1.045 - 1) * 100)


def test_aliquotas_do_rebalanceamento():
    al = rebalanceamento._aliquota
    assert al(Posicao("LCA", "pos_fixado", 1, tipo="lca"), HOJE)[0] == 0
    assert al(Posicao("HGLG11", "fii", 1, ticker="HGLG11"), HOJE)[0] == 0.20
    assert al(Posicao("IVVB11", "internacional", 1, ticker="IVVB11", tipo="etf"), HOJE)[0] == 0.15
    assert al(Posicao("CDB", "pos_fixado", 1, tipo="cdb", data_aplicacao=date(2026, 6, 1)), HOJE)[0] == 0.225  # 125 dias
    assert al(Posicao("CDB", "pos_fixado", 1, tipo="cdb", data_aplicacao=date(2024, 1, 1)), HOJE)[0] == 0.15


def test_rebalanceamento_com_ir_e_aporte_conferido_a_mao():
    c = Carteira("R", [Posicao("CDB", "pos_fixado", 50_000, tipo="cdb", custo=40_000, data_aplicacao=date(2024, 1, 1)),
                       Posicao("Ações", "acoes", 50_000, tipo="fundo", custo=40_000)])
    alvo = {"pos_fixado": 0.8, "acoes": 0.2}
    p = rebalanceamento.planejar(c, alvo, 0, HOJE)
    venda = next(o for o in p.ordens if o.acao == "vender")
    # vender 30 mil do fundo de ações (ganho de 20% → 6 mil) com IR de 15% = R$ 900
    assert venda.alvo == "Ações" and venda.valor == pytest.approx(30_000) and venda.ir == pytest.approx(900)
    assert p.ir_total == pytest.approx(900) and p.pesos_finais["acoes"] == pytest.approx(0.2)
    # sem vender: patrimônio precisa ir a 50 mil / 0,2 = 250 mil → aporte de 150 mil
    assert p.aporte_sem_vender == pytest.approx(150_000) and p.classe_limitante == "acoes"
    p2 = rebalanceamento.planejar(c, alvo, 150_000, HOJE)
    assert not [o for o in p2.ordens if o.acao == "vender"] and p2.ir_total == 0 and p2.aporte_usado == pytest.approx(150_000)
    # ações abaixo de R$ 20 mil vendidas no mês: isentas
    c3 = Carteira("A", [Posicao("PETR4", "acoes", 30_000, ticker="PETR4", tipo="acao", custo=20_000),
                        Posicao("CDB", "pos_fixado", 70_000, tipo="cdb")])
    p3 = rebalanceamento.planejar(c3, {"pos_fixado": 0.85, "acoes": 0.15}, 0, HOJE)
    v3 = next(o for o in p3.ordens if o.acao == "vender")
    assert v3.valor == pytest.approx(15_000) and v3.ir == 0 and "isento" in v3.nota


def test_backtest_cdi_puro_igual_ao_cdi():
    df = series_sinteticas().retornos
    r = {b.nome: b for b in backtest.rodar(df, {"Caixa": {"pos_fixado": 1.0}, "Misto": {"pos_fixado": 0.5, "acoes": 0.5}})}
    assert r["Caixa"].metricas.retorno_aa == pytest.approx(1.008 ** 12 - 1) == pytest.approx(r["CDI"].metricas.retorno_aa)
    esperado = 0.5 * df.tail(120)["CDI"] + 0.5 * df.tail(120)["IBOV"]
    assert r["Misto"].acumulado.iloc[-1] == pytest.approx((1 + esperado).prod())
    assert len(r["Misto"].retornos) == 120


# ---------------------------------------------------------------- relatório completo
def test_graficos_agrupados_com_negativos_e_dispersao():
    png = desenhar(Grafico("Atual × alvo", "barras_h", ["A", "B"], {"Atual": [10, -5], "Alvo": [8, 2]}, "pct"))
    assert png[:4] == b"\x89PNG"
    png = desenhar(Grafico("Fronteira", "dispersao", [], {"Fronteira": [1, 2, 3], "Atual": [2.5]}, "pct", "vol",
                           x={"Fronteira": [1, 2, 4], "Atual": [3]}, formato_x="pct"))
    assert png[:4] == b"\x89PNG"


def test_diagnostico_completo_sem_internet(tmp_path):
    from quiron.servicos.analise.fila import carregar_tipos
    from quiron.servicos.analise.tipos.carteira import diagnostico

    assert "carteira_diagnostico" in carregar_tipos()
    ident = arquivo.salvar(carteira_teste())
    rel = diagnostico({"carteira_id": ident, "aporte": 10_000}, mercado=MERCADO, dados=series_sinteticas(), hoje=HOJE,
                      redigir=False)
    assert [s.titulo for s in rel.secoes] == ["Composição e enquadramento", "Risco", "Stress test", "Otimização",
                                              "Rebalanceamento", "Backtest"]
    f = rel.fatos
    assert f["patrimonio"] == 300_000 and f["perfil"] == "moderado" and f["cliente"] == "CLI-900"
    assert f["selic_mais_3"]["carregamento_12m_reais"] == pytest.approx(3_000)
    assert f["selic_mais_3"]["impacto_reais"] < 0 and "Selic +3 p.p." in rel.resumo[2]
    # prefixado = 50/300 = 16,7% > máximo de 15% do moderado; o resto está dentro das faixas
    assert [(x["classe"], x["atual_pct"]) for x in f["fora_do_perfil"]] == [("Prefixado", 16.67)]
    caminhos = rel.salvar(tmp_path / "rel")
    assert caminhos["pdf"].stat().st_size > 30_000 and caminhos["planilha"].exists()
    import pymupdf

    texto = "".join(p.get_text() for p in pymupdf.open(caminhos["pdf"]))
    assert "Stress test" in texto and "Backtest" in texto and "Rebalanceamento" in texto and "Uso interno" in texto


def test_diagnostico_recusa_carteira_vazia_e_nome_de_cliente():
    from quiron.servicos.analise.tipos.carteira import obter_carteira

    with pytest.raises(ValueError):
        obter_carteira({}, usar_cerebro=False)
    c = obter_carteira({"carteira": carteira_teste().como_dict(), "cliente": "João da Silva", "perfil": "ousado"},
                       usar_cerebro=False)
    assert c.cliente == "" and c.perfil == "moderado" and len(c.avisos) == 2


def test_bot_le_planilha_e_passa_so_o_id_ao_agente(monkeypatch):
    from quiron.nucleo import cerebro
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    recebidos = []

    def conversar(mensagens, ferramentas=None, **kw):
        recebidos.append(list(mensagens))
        return cerebro.Turno("Leitura conferida; pedido #1 na fila.", [], {"role": "assistant", "content": "ok"}, "sim")

    class SemMCP:
        ferramentas = []

        async def chamar(self, nome, args):
            return "ok"

    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    csv = "Ativo;Valor\nCDB 110% CDI;100.000\nIVVB11;20.000\n".encode()
    saidas = asyncio.run(bot.tratar_arquivo(111, 1, csv, "carteira.csv", "perfil moderado"))
    assert "📥 Li a carteira" in saidas[0].texto and "R$ 120.000,00" in saidas[0].texto
    assert saidas[-1].texto == "Leitura conferida; pedido #1 na fila."
    pedido = recebidos[0][-1]["content"]
    assert "carteira_id='CART-" in pedido and "Pedido: perfil moderado" in pedido
    assert asyncio.run(bot.tratar_arquivo(999, 1, csv, "carteira.csv")) == []
    assert "print (foto)" in asyncio.run(bot.tratar_arquivo(111, 1, b"%PDF", "livro.pdf"))[0].texto
