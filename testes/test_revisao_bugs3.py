"""Regressões da 3ª rodada de revisão (06/10/2026) — tudo sem internet."""

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from quiron.nucleo.config import Config


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.setenv("QUIRON_EMBEDDINGS", "lexico")
    return tmp_path


class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def _bot():
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    return BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {7})


# ---------------------------------------------------------------- privacidade e permissões do agente
def test_ia_na_nuvem_recebe_dado_pessoal_mascarado(monkeypatch):
    from quiron.nucleo import cerebro

    enviadas = []

    class Falso:
        @staticmethod
        def completion(**kw):
            enviadas.append(kw["messages"])
            msg = type("M", (), {"content": "ok", "tool_calls": None, "model_dump": lambda self, **k: {"content": "ok"}})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()], "usage": None})()

    monkeypatch.setattr(cerebro, "_litellm", lambda: Falso)
    cfg = Config(llm_principal="gemini/mascara-teste", gemini_api_key="x")
    historico = [{"role": "user", "content": "/tarefa ligar Maria (11) 98888-7777 e mandar para joao@gmail.com"},
                 {"role": "assistant", "content": "📌 Tarefa criada: ligar Maria (11) 98888-7777"},
                 {"role": "tool", "content": "CPF 123.456.789-00; fundo 11.728.688/0001-47"},
                 {"role": "user", "content": "qual a selic?"}]
    cerebro.conversar(historico, config=cfg)
    texto = str(enviadas[-1])
    assert "98888" not in texto and "joao@" not in texto and "123.456" not in texto
    assert "[telefone]" in texto and "11.728.688/0001-47" in texto  # CNPJ de fundo é público
    assert historico[0]["content"].endswith("joao@gmail.com")  # o histórico local continua inteiro


def test_numeros_financeiros_nao_viram_telefone():
    from quiron.nucleo.privacidade import mascarar

    t = "PL de 1500000000, 12345678901 cotas, Selic 15,00 em 06/10/2026, R$ 1.234.567,89"
    assert mascarar(t) == t


def test_detector_pega_formatos_com_espaco_e_ddi():
    from quiron.servicos.assessoria.compliance import conferir

    for t in ("(11) 98888 7777", "+5511988887777", "11 9 8888 7777", "CPF 123 456 789 00"):
        assert any(a.gravidade == "grave" for a in conferir(t)), t


def test_rotina_agendada_nao_roda_comando_que_altera_dados():
    from quiron.runtime.agendador import BRT

    bot = _bot()
    bot.agente.longa.adicionar("Estudo CFP às terças", "estudo", 3, "dito")
    resposta = bot.agente.internas.executar("agendar", {"texto": "/memoria esquecer CFP", "tipo": "tarefa", "recorrencia": "uma vez",
                                                        "quando_iso": (datetime.now(BRT) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")})
    assert resposta.startswith("Não agendei")
    agora = datetime.now(BRT)  # mesmo que entre por outro caminho (agendador direto), não roda sozinho
    bot.agente.agendador.criar("/memoria esquecer CFP", "tarefa", "uma vez", agora + timedelta(minutes=1), agora=agora)
    saidas = asyncio.run(bot.agenda_vencida(agora + timedelta(minutes=2)))
    assert "não rodei" in saidas[0].texto and bot.agente.longa.fatos()


def test_ferramenta_interna_com_argumento_torto_nao_derruba():
    bot = _bot()
    r = asyncio.run(bot.agente.executar_ferramenta("lembrar", {"fato": "Prefiro gráficos", "importancia": "alta"}))
    assert not r.startswith("ERRO") and [f for f in bot.agente.longa.fatos() if "gráficos" in f.texto]
    assert "Não encontrei" in asyncio.run(bot.agente.executar_ferramenta("cancelar_agendamento", {"id": "#5"}))


def test_rascunho_e_rodape_de_uso_interno():
    from quiron.runtime.permissoes import aplicar_compliance

    assert aplicar_compliance("escreve uma mensagem para meu cliente sobre o CDB", "Olá").startswith("📝 RASCUNHO")
    assert aplicar_compliance("mensagem para os clientes", "Olá").startswith("📝 RASCUNHO")
    assert "Uso interno" in aplicar_compliance("vale comprar petr4?", "Recomendo compra de Petrobras.")
    assert "Uso interno" not in aplicar_compliance("vale a pena comprar CDB?", "Recomendo avaliar o prazo.")


def test_frases_que_nao_sao_adiar_nem_nota():
    from quiron.runtime.roteamento import rotear

    for t in ("passa 100 mil para o CDB", "joga 30 mil pro Tesouro IPCA", "muda 2 clientes para o perfil arrojado", "nota 10 para a resposta"):
        assert rotear(t) is None, t
    assert rotear("troca para o cenário pessimista", 5) is None
    assert rotear("passa para amanhã às 11h", 5)[0] == "adiar" and rotear("adia 3 para sexta")[0] == "adiar"
    assert rotear("lembre que toda segunda eu prefiro o briefing mais curto")[0] == "lembrar"


# ---------------------------------------------------------------- valuation, risco e relatórios
def test_arrendamento_dentro_dos_emprestimos_nao_conta_duas_vezes():
    from quiron.servicos.valuation import cvm_cias

    def linha(dem, conta, nome, valor):
        return {"_dem": dem, "CD_CONTA": conta, "DS_CONTA": nome, "VL_CONTA": valor, "ESCALA_MOEDA": "UNIDADE"}

    v = cvm_cias._extrair([linha("BPP", "2.01.04", "Empréstimos e Financiamentos", 300.0),
                           linha("BPP", "2.01.04.03", "Financiamento por Arrendamento", 100.0),
                           linha("BPP", "2.02.01", "Empréstimos e Financiamentos", 700.0),
                           linha("BPP", "2.02.01.03", "Financiamento por Arrendamento", 400.0),
                           linha("BPA", "1.01.01", "Caixa e Equivalentes de Caixa", 100.0)])
    assert v["divida_liquida"] == pytest.approx(900.0)  # antes: 1.400 (arrendamento somado de novo)


def test_pior_queda_conta_desde_o_capital_inicial():
    from quiron.servicos.carteira import risco

    idx = pd.period_range("2024-01", periods=6, freq="M")
    m = risco.metricas(pd.Series([-0.10, 0.02, 0.02, 0.01, 0.0, 0.01], index=idx))
    assert m.max_drawdown == pytest.approx(-0.10)


def test_conferencia_de_numeros_sem_sinal_e_com_milhao():
    from quiron.servicos.analise.redacao import conferir

    assert conferir("O fundo caiu 12,3% e tem R$ 1,2 milhão; inventado 47,9%", [-12.3, 1234567.0]) == [47.9]


# ---------------------------------------------------------------- mercado e notícias
def test_sentimento_no_nao_e_negacao():
    from quiron.servicos.noticias.sentimento import tom

    assert tom("Bolsas no mundo caem").nota < 0 and tom("Lucro no trimestre cresce 20%").nota > 0


def test_painel_lento_mostra_o_dado_anterior_enquanto_renova():
    import threading
    import time

    from quiron.terminal.backend import dados as d

    d._fundo.clear()
    d._ultimo_ok.clear()
    assert d._em_segundo_plano("x", lambda: {"v": 1}) in (None, {"v": 1})
    time.sleep(0.2)
    assert d._em_segundo_plano("x", lambda: {"v": 1}) == {"v": 1}
    trava = threading.Event()
    d._fundo["x"] = (d._fundo["x"][0], 0.0)  # venceu: a próxima chamada renova em segundo plano
    assert d._em_segundo_plano("x", lambda: (trava.wait(2), {"v": 2})[1], validade=1) == {"v": 1}
    trava.set()


def test_bps_do_tesouro_so_compra_contra_compra(monkeypatch):
    from quiron.servicos.mercado import bcb, briefing, tesouro

    base = date(2026, 10, 6)
    titulos = [tesouro.Titulo("Tesouro Prefixado", date(2029, 1, 1), base, 0.0, 13.62, None, None),
               tesouro.Titulo("Tesouro IPCA+", date(2029, 5, 15), base, None, 7.50, None, None)]
    tab = type("T", (), {"data_base": base, "titulos": titulos, "desatualizado": False})()
    monkeypatch.setattr(tesouro, "titulos_atuais", lambda: tab)
    monkeypatch.setattr(bcb, "sgs", lambda *a, **k: (_ for _ in ()).throw(bcb.FonteIndisponivel("fora")))
    monkeypatch.setattr(briefing, "_taxas_anteriores", lambda b, av: {("Tesouro IPCA+", date(2029, 5, 15)): 7.38,
                                                                     ("Tesouro Prefixado", date(2029, 1, 1)): 13.50})
    texto = " ".join(briefing._juros([], []))
    assert "13,62%" in texto and "bps" not in texto  # sem taxa de compra hoje: mostra a de venda, sem "variação"


# ---------------------------------------------------------------- correções pedidas em 07/10/2026
def test_live_agendada_nao_conta_como_ao_vivo():
    import httpx

    from quiron.servicos import tv

    base = ('"videoPrimaryInfoRenderer":{"title":{"runs":[{"text":"Live programada"}]},"viewCount":{},"isLive":true}'
            '"currentVideoEndpoint":{"watchEndpoint":{"videoId":"bwycWD_w6Xw"}}')
    agendada = base + '"playabilityStatus":{"status":"LIVE_STREAM_OFFLINE"},"isUpcoming":true,"scheduledStartTime":"1676408400"'
    for html, esperado in ((agendada, False), (base, True)):
        tv._VIVO.clear()
        cli = httpx.Client(transport=httpx.MockTransport(lambda r, h=html: httpx.Response(200, text=h)))
        assert tv.ao_vivo("UCayJQj7hiNhfFk-MJ8Z9H0w", cli)["ao_vivo"] is esperado


def test_fii_pedido_como_fundo_vai_para_o_comparativo_de_fii(monkeypatch):
    from quiron.servicos.analise.tipos import fundos

    chamado = {}
    monkeypatch.setattr(fundos, "fii_comparativo", lambda params, modo="entregar", **k: chamado.setdefault("p", params))
    monkeypatch.setattr(fundos, "preparar", lambda anos: (_ for _ in ()).throw(AssertionError("não devia baixar o cadastro")))
    fundos.comparativo({"fundos": ["RBRR11", "MCCI11"]}, redigir=False)
    assert chamado["p"] == {"fiis": ["RBRR11", "MCCI11"]}
    assert fundos._so_fiis({"cnpjs": "RBRR11 e MCCI11"}) == ["RBRR11", "MCCI11"]
    assert not fundos._so_fiis({"cnpjs": ["Verde FIC FIM", "RBRR11"]})


def test_motivo_da_falha_explica_em_portugues():
    from quiron.servicos.analise.fila import motivo_amigavel

    assert motivo_amigavel("FundoNaoEncontrado: não achei o fundo “XYZ” no cadastro da CVM").startswith("não achei o fundo")
    assert "OperationalError" in motivo_amigavel("OperationalError: database is locked")


def test_pedido_de_fundo_com_campo_diferente_e_validado_na_hora(dados):
    from quiron.servicos.analise import fila as mod

    f = mod.Fila(dados / "a.db", dados / "rel")
    t = f.pedir("fundo_analise", {"fundo": "MCCI11"})  # campo "fundo" e FII pedido como fundo comum
    assert (t.tipo, t.parametros) == ("fii_comparativo", {"fiis": ["MCCI11"]})
    t = f.pedir("fundos_comparativo", {"ativos": ["RBRR11", "MCCI11"], "anos": 3})
    assert t.tipo == "fii_comparativo" and t.parametros["fiis"] == ["RBRR11", "MCCI11"]
    with pytest.raises(ValueError):
        f.pedir("fii_comparativo", {"anos": 3})


def test_so_um_codigo_vai_direto_aos_dados_oficiais():
    from quiron.runtime.roteamento import rotear

    assert rotear("XPAG11") == ("ativo", "XPAG11") and rotear("o que é o MCCI11?") == ("ativo", "MCCI11")
    assert rotear("PETR4 caiu hoje?") is None
