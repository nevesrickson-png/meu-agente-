"""Simulador de patrimônio (quanto investir, quando parar, tempo até a meta, imóvel × aplicações) + interface do agente
(Telegram formatado, botões rápidos). Sem internet."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quiron.servicos.planejamento import simulador as s
from quiron.servicos.planejamento.diagnostico import premissas, taxa_mensal, vf


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.setenv("QUIRON_EMBEDDINGS", "lexico")
    return tmp_path


def test_motor_bate_com_as_formulas():
    serie = s.projetar(100_000, 2_000, 6.0, 10)
    assert serie[-1] == pytest.approx(vf(100_000, 2_000, taxa_mensal(6.0), 120), rel=1e-9)
    m = s.meses_ate(1_000_000, 100_000, 2_000, 6.0)
    assert vf(100_000, 2_000, taxa_mensal(6.0), m) >= 1_000_000 > vf(100_000, 2_000, taxa_mensal(6.0), m - 1)
    assert s.meses_ate(50_000, 100_000, 0, 5) == 0 and s.meses_ate(10**9, 0, 100, 1) is None
    p = premissas()
    assert s.capital_para_renda(10_000, 65, p) > 10_000 * 12 * 15  # 30 anos de renda consumindo o capital
    mc = s.monte_carlo(100_000, 1_000, 5.0, 8.0, 10, n=4000)
    assert mc.shape == (4000, 11) and abs(float(mc[:, -1].mean()) / s.projetar(100_000, 1_000, 5.0, 10)[-1] - 1) < 0.03


def test_responde_as_quatro_perguntas_com_cenarios_coerentes():
    e = s.Entrada(patrimonio=500_000, aporte_mensal=5_000, idade=40, meta=5_000_000, renda_desejada=20_000, imovel_valor=800_000)
    sim = s.simular(e, 800)
    assert sim.series["pessimista"][-1] < sim.series["base"][-1] < sim.series["otimista"][-1]
    assert sim.faixa["p10"][-1] < sim.faixa["p50"][-1] < sim.faixa["p90"][-1]
    r = {x["chave"]: x for x in sim.respostas}
    assert set(r) == {"aporte_necessario", "independencia", "tempo_meta", "imovel"}
    ap = r["aporte_necessario"]
    assert ap["cenarios"]["otimista"] < ap["valor"] < ap["cenarios"]["pessimista"]
    anos = sim.anos[-1] - 40  # o aporte calculado chega na meta no prazo
    assert s.projetar(500_000, ap["valor"], sim.retorno_base, anos)[-1] == pytest.approx(5_000_000, rel=1e-3)
    ind = r["independencia"]
    assert ind["cenarios"]["otimista"] <= ind["valor"] <= ind["cenarios"]["pessimista"] and 0 < ind["chance"] <= 1
    assert r["tempo_meta"]["cenarios"]["otimista"] < r["tempo_meta"]["valor"] < r["tempo_meta"]["cenarios"]["pessimista"]
    texto = s.texto(sim)
    assert "Quando posso parar de trabalhar?" in texto and "não é promessa" in texto.lower() and "4,5% a.a." in texto
    with pytest.raises(ValueError):
        s.Entrada(idade=40, idade_meta=35).validar()


def test_imovel_empata_na_valorizacao_indicada():
    im = premissas()["simulador"]["imovel"]
    r = s.imovel_x_financeiro(800_000, 20, 4.5, im)
    empate = s.imovel_x_financeiro(800_000, 20, 4.5, {**im, "valorizacao_real_aa": r["valorizacao_de_empate_aa"]})
    assert empate["imovel"][-1] == pytest.approx(empate["financeiro"][-1], rel=2e-3)
    assert r["melhor"] in {"imóvel", "investimentos financeiros"} and "liquidez" in r["texto"]


def test_le_a_situacao_em_palavras():
    d = s.ler_frase("tenho 40 anos, tenho 500 mil investidos, invisto 5 mil por mês, quero chegar a 5 milhões e viver "
                    "com 20 mil, perfil moderado, imóvel de 800 mil")
    assert d == {"idade": 40, "aporte_mensal": 5000.0, "renda_desejada": 20000.0, "meta": 5e6, "patrimonio": 500000.0,
                 "imovel_valor": 800000.0, "perfil": "moderado"}
    d = s.ler_frase("patrimônio de 1,2 milhão, aporte de 3.500, quero parar aos 55 anos com renda de 15 mil, tenho 35 anos")
    assert d["patrimonio"] == 1.2e6 and d["aporte_mensal"] == 3500 and d["idade"] == 35 and d["idade_meta"] == 55
    assert s.ler_frase("apartamento de 600 mil em 15 anos") == {"imovel_valor": 600000.0, "horizonte_imovel_anos": 15}
    d = s.ler_frase("tenho 2 mi, aporte 10k, 50 anos, renda de 30 mil")
    assert d["idade"] == 50 and d["patrimonio"] == 2e6 and d["aporte_mensal"] == 10000 and d["renda_desejada"] == 30000


def test_simula_pela_ficha_do_cliente():
    from quiron.servicos.planejamento import ficha

    ficha.salvar({"cliente": "CLI-012", "idade": 50, "perfil": "conservador", "aporte_mensal": 4000,
                  "renda_desejada_aposentadoria": 12000, "idade_aposentadoria": 62,
                  "patrimonio": [{"nome": "Carteira", "tipo": "investimento", "valor": 900000},
                                 {"nome": "Casa", "tipo": "residencia", "valor": 1500000}]})
    e = s.de_ficha("CLI-012", meta=3_000_000)
    assert (e.patrimonio, e.idade, e.perfil, e.renda_desejada, e.idade_meta, e.meta) == (900000, 50, "conservador", 12000, 62, 3e6)
    from quiron.mcp.assessoria import servidor

    assert "Quando posso parar de trabalhar?" in servidor.simular_patrimonio(cliente="CLI-012")
    assert "Não simulei" in servidor.simular_patrimonio(idade=200)


def test_terminal_painel_sim():
    from quiron.terminal.backend import app as terminal

    c = TestClient(terminal.app)
    h = {"X-Quiron": "terminal"}
    assert c.post("/api/simulador", json={"patrimonio": 1}).status_code == 403
    r = c.post("/api/simulador", json={"patrimonio": 200000, "aporte_mensal": 3000, "idade": 30, "meta": 2000000}, headers=h).json()
    assert len(r["anos"]) == len(r["series"]["base"]) and r["respostas"] and "texto" in r
    assert c.post("/api/simulador", json={"idade": 5}, headers=h).status_code == 400
    assert c.post("/api/simulador", json={"cliente": "João"}, headers=h).status_code == 400
    js = c.get("/app.js").text
    assert "renderSim" in js and '"SIM"' in js and "graficoPatrimonio" in js


def test_telegram_simular_com_grafico_e_formatacao():
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron, para_html

    class SemMCP:
        ferramentas = []

        async def chamar(self, n, a):
            return "ok"

    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {111})
    ajuda = asyncio.run(bot.tratar(111, 111, "/simular"))[0].texto
    assert "Simulador de patrimônio" in ajuda
    saida = asyncio.run(bot.tratar(111, 111, "/simular tenho 35 anos, 300 mil investidos, invisto 4 mil por mês, quero chegar a 3 milhões"))[0]
    assert "Em quanto tempo chego a R$ 3,00 mi?" in saida.texto and Path(saida.arquivo).exists() and saida.arquivo.endswith(".png")
    inicio = asyncio.run(bot.tratar(111, 111, "/start"))[0]
    assert any(d == "qa:/simular" for linha in inicio.teclado() for _, d in linha)
    assert "simular" in {n for n, _ in bot.menu_telegram()}

    html = para_html("### Título\n- **Selic**: 13,75% <script>\n| A | B |\n|---|---|\n| x | **1** |\n`cod` [BCB](https://bcb.gov.br/?a=1&b=2)")
    assert "<b>Título</b>" in html and "• <b>Selic</b>" in html and "&lt;script&gt;" in html and "<script>" not in html
    assert "<pre>A  B\nx  1</pre>" in html and "<code>cod</code>" in html and 'href="https://bcb.gov.br/?a=1&amp;b=2"' in html
    assert para_html("CLI_012 e 5 * 3 = 15") == "CLI_012 e 5 * 3 = 15"  # nada de itálico por engano
