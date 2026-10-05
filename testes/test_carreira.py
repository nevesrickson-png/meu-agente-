"""Fase 15 — carreira: radar regulatório (fontes oficiais simuladas), diário de teses (revisão, calibração), plano de
carreira, portfólio de análises (sem cliente), simulação de entrevista e o fluxo no Telegram. Sem internet."""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from quiron.nucleo import cerebro
from quiron.runtime.agendador import BRT, Agendador
from quiron.servicos.carreira import diario, entrevista, plano, portfolio, radar
from quiron.servicos.mercado import http

ABRIL = datetime(2026, 4, 6, 10, 0, tzinfo=BRT)
OUTUBRO = datetime(2026, 10, 6, 10, 0, tzinfo=BRT)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    yield tmp_path
    http.definir_cliente(None)


def _sem_cerebro(*a, **k):
    raise cerebro.CerebroIndisponivel("offline")


# ---------------------------------------------------------------- radar
def _rss(titulos):
    agora = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    itens = "".join(f"<item><title>{t}</title><link>https://www.gov.br/x/{i}</link><description>{d}</description>"
                    f"<pubDate>{agora}</pubDate></item>" for i, (t, d) in enumerate(titulos))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{itens}</channel></rss>'


def _fontes_oficiais(req: httpx.Request) -> httpx.Response:
    hoje = datetime.now(timezone.utc).isoformat()
    if "cvm" in req.url.host or "/cvm/" in req.url.path:
        return httpx.Response(200, text=_rss([("CVM edita resolução que altera regras para assessores de investimento", "Resolução CVM 178"),
                                              ("CVM promove evento de educação financeira", "semana ENEF")]))
    if "receitafederal" in req.url.path:
        return httpx.Response(200, text=_rss([("Receita publica Instrução Normativa sobre tributação de fundos", "come-cotas"),
                                              ("Receita alerta para golpe do falso servidor", "")]))
    if "bcb.gov.br" in req.url.host:
        return httpx.Response(200, json={"Rows": [
            {"title": "Resolução CMN N° 5.343", "TipodoNormativoOWSCHCS": "Resolução CMN", "NumeroOWSNMBR": "5343.0", "data": hoje,
             "AssuntoNormativoOWSMTXT": "<div>Altera regras de fundos de investimento em direitos creditórios</div>"},
            {"title": "Comunicado N° 46.061", "TipodoNormativoOWSCHCS": "Comunicado", "NumeroOWSNMBR": "46061.0", "data": hoje,
             "AssuntoNormativoOWSMTXT": "operações compromissadas"},
            {"title": "Resolução BCB N° 591", "TipodoNormativoOWSCHCS": "Resolução BCB", "NumeroOWSNMBR": "591.0", "data": hoje,
             "AssuntoNormativoOWSMTXT": "prevenção da utilização do sistema financeiro para a prática dos crimes de lavagem"}]})
    if "camara" in req.url.host:
        return httpx.Response(200, json={"dados": [
            {"id": 1, "siglaTipo": "PLP", "numero": 255, "ano": 2026, "dataApresentacao": "2026-10-01T10:00",
             "ementa": "Incentivo à poupança previdenciária complementar e ao investimento de longo prazo"},
            {"id": 2, "siglaTipo": "REQ", "numero": 9, "ano": 2026, "dataApresentacao": "2026-10-01T10:00", "ementa": "Requerimento"}]})
    return httpx.Response(404)


def test_radar_classifica_por_tema_sem_falso_positivo():
    t = radar.config()["temas"]
    i = radar.classificar(radar.Item("BCB", "Resolução BCB 591", "x", datetime.now(timezone.utc),
                                     "prática dos crimes de lavagem"), t)
    assert i.temas == ["PLD e controles"] and i.relevancia == 2  # "crimes" não casa com CRI
    i = radar.classificar(radar.Item("CVM", "CVM altera Resolução CVM 175 de fundos", "x", datetime.now(timezone.utc)), t)
    assert i.relevancia == 3 and "Fundos (CVM 175)" in i.temas
    assert radar.classificar(radar.Item("X", "Evento de educação", "x", datetime.now(timezone.utc)), t).relevancia == 0


def test_radar_coleta_fontes_oficiais_filtra_e_mostra_novidades():
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(_fontes_oficiais)))
    r = radar.atualizar()
    assert r["erros"] == {}
    assert r["por_fonte"]["CVM — notícias"] == (1, 1)  # o evento de educação ficou de fora pelo filtro de norma
    assert r["por_fonte"]["Receita Federal — notícias"][0] == 1
    assert r["por_fonte"]["Banco Central — normativos"][0] == 2  # comunicado de rotina fica de fora
    assert r["por_fonte"]["Câmara dos Deputados — projetos de lei"][0] == 1  # só PL/PLP/PEC/MPV, sem repetir
    texto = radar.relatorio(14, atualizar_antes=False)
    assert "🔴" in texto and "assessores de investimento" in texto and "Resolução CMN N° 5.343" in texto
    assert "PLP 255/2026" in texto and "https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=1" in texto
    assert texto.index("assessores") < texto.index("Resolução BCB N° 591")  # mais relevante primeiro
    assert radar.atualizar()["novos"] == 0  # não repete link
    assert "Nenhuma novidade" in radar.relatorio(14, so_novos=True, atualizar_antes=False)  # já vistos
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503))))
    falha = radar.atualizar([{"id": "z", "nome": "Fonte Z", "tipo": "rss", "url": "https://z.gov.br/rss"}])
    assert "Fonte Z" in falha["erros"]


# ---------------------------------------------------------------- diário de teses
TESE = ("WEG vai superar o Ibovespa em 6 meses porque a demanda de transmissão segue forte e a margem EBITDA fica acima "
        "de 22%. Confiança 70%. Se a margem cair abaixo de 20%, a tese morre.")
JSON_TESE = {"titulo": "WEG supera o Ibovespa em 6 meses", "tese": "WEG supera o Ibovespa", "ativo": "WEGE3", "direcao": "alta",
             "premissas": ["demanda de transmissão forte", "margem EBITDA > 22%"], "invalidacao": ["margem < 20%"],
             "horizonte": "em 6 meses", "confianca": 70}


def test_diario_registra_revisa_e_calibra(monkeypatch):
    precos = {"WEGE3": 50.0, "IBOV": 150000.0}
    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(JSON_TESE)))
    t = diario.registrar(TESE, ABRIL, cotacao=lambda a: precos[a])
    assert (t.ativo, t.benchmark, t.preco_inicial, t.bench_inicial, t.confianca) == ("WEGE3", "IBOV", 50.0, 150000.0, 70)
    assert t.revisar_em == "2026-10-06"  # "em 6 meses" calculado em Python
    lembrete = {a.id: a for a in Agendador().listar()}[t.lembrete]
    assert lembrete.proxima == datetime(2026, 10, 6, 9, 0, tzinfo=BRT) and "/diario revisar 1" in lembrete.texto

    precos.update(WEGE3=51.45, IBOV=192115.0)
    m = diario.medir(t, lambda a: precos[a], OUTUBRO)
    assert m["retorno"] == pytest.approx(2.9) and m["retorno_bench"] == pytest.approx(28.0767, abs=1e-3)
    assert m["excesso"] == pytest.approx(2.9 - 28.0767, abs=1e-3) and m["a_favor"] is False and m["vencida"]
    rev = diario.revisao_de_teses(7, lambda a: precos[a], OUTUBRO)
    assert "WEGE3: +2,9% · IBOV: +28,1% · excesso -25,2%" in rev and "contra a tese ❌" in rev
    assert "margem EBITDA > 22%" in rev and "Uso interno" in rev

    fechada = diario.resolver(t.id, "errou", "subestimei o ciclo de alta da bolsa", OUTUBRO)
    assert fechada.situacao == "errou" and fechada.resultado == 0.0
    assert t.lembrete not in {a.id for a in Agendador().listar()}
    t2 = diario.registrar(TESE, ABRIL, cotacao=lambda a: precos[a])
    diario.resolver(t2.id, "acertou")
    e = diario.estatisticas()
    assert e["fechadas"] == 2 and e["acerto"] == 50 and e["brier"] == pytest.approx(((0.7 - 0) ** 2 + (0.7 - 1) ** 2) / 2)
    assert "60–79%: 2 tese(s), acertou 50% vs. confiança média 70% — confiante demais" in diario.texto_estatisticas()
    with pytest.raises(diario.TeseInvalida):
        diario.resolver(t2.id, "talvez")


def test_diario_sem_ia_regras_e_adiar(monkeypatch):
    monkeypatch.setattr(cerebro, "perguntar", _sem_cerebro)
    t = diario.registrar("Acho que PETR4 vai cair até dezembro com o petróleo mais fraco, 60% de confiança.", OUTUBRO,
                         cotacao=lambda a: {"PETR4": 30.0, "IBOV": 190000.0}[a])
    assert (t.ativo, t.direcao, t.confianca, t.revisar_em) == ("PETR4", "baixa", 60.0, "2026-12-31")
    sem_prazo = diario.registrar("Selic deve terminar 2027 abaixo de 12% por conta da desinflação de serviços.", OUTUBRO,
                                 cotacao=lambda a: 1.0)
    assert sem_prazo.ativo == "" and sem_prazo.revisar_em == (OUTUBRO.date() + timedelta(days=90)).isoformat()
    adiada = diario.adiar(t.id, "3 meses", OUTUBRO)
    assert adiada.revisar_em == "2027-01-06"
    with pytest.raises(diario.TeseInvalida):
        diario.registrar("curto", OUTUBRO)


# ---------------------------------------------------------------- plano, portfólio, entrevista
def test_plano_de_carreira(monkeypatch):
    assert plano.semanas_necessarias("CFP", 5) == 50 and plano.semanas_necessarias("CFP", 5, 0.6) == 35
    with pytest.raises(ValueError):
        plano.registrar_prova("XYZ", None)
    assert "prova em 20/03/2027" in plano.registrar_prova("cfp", date(2027, 3, 20))
    from quiron.servicos.academia.banco import Banco

    assert Banco().pref("data_prova:CFP") == "2027-03-20"  # a Academia usa a mesma data
    plano.avaliar("Valuation", 5)
    plano.avaliar("valuation", 7)
    plano.avaliar("comunicação escrita", 8)
    texto = plano.montar(date(2026, 10, 6))
    assert "Analista/estrategista de referência" in texto and "▶️ CFP (Planejar)" in texto and "prova 20/03/2027" in texto
    assert "valuation: 7/10 (+2" in texto and "Próximos 90 dias" in texto and "/diario" in texto
    plano.registrar_prova("CFP", None, "aprovado")
    assert "✅ CFP" in plano.montar(date(2026, 10, 6)) and "▶️ CNPI" in plano.montar(date(2026, 10, 6))


def test_portfolio_so_aceita_analise_sem_cliente(monkeypatch):
    from quiron.servicos.analise import fila as mod_fila
    from quiron.servicos.analise.fila import TIPOS, tipo
    from testes.test_analise import _relatorio

    @tipo("teste_port", "teste")
    def _rel(params, modo):
        r = _relatorio()
        r.titulo = params["titulo"]
        return r

    monkeypatch.setattr(mod_fila, "carregar_tipos", lambda: TIPOS)
    monkeypatch.setattr(mod_fila, "_FILA", None)
    try:
        f = mod_fila.fila()
        a = f.pedir("teste_port", {"titulo": "Debêntures incentivadas vs. CDB"})
        b = f.pedir("teste_port", {"titulo": "Carteira do CLI-012"})
        f.processar_uma(), f.processar_uma()
        assert [t.id for t in portfolio.candidatos()] == [a.id]
        with pytest.raises(ValueError, match="cliente"):
            portfolio.adicionar(b.id)
        assert "entrou no portfólio" in portfolio.adicionar(a.id, "mostra o cálculo de IR e sensibilidade")
        assert "Debêntures incentivadas" in portfolio.listar_texto()
        pdf = portfolio.gerar_pdf()
        import pymupdf

        texto = "".join(p.get_text() for p in pymupdf.open(pdf))
        assert "Portfólio de análises" in texto and "Debêntures incentivadas" in texto and "CLI-012" not in texto
        assert "Track record" in texto
    finally:
        TIPOS.pop("teste_port")


def test_entrevista_pergunta_e_avalia(monkeypatch):
    perguntas = iter(["Entrevistador: Bom dia. Como você calcularia o WACC de uma empresa brasileira?",
                      "E se o beta da empresa não for confiável?", "Obrigado, terminamos. Digite /entrevista fim."])
    monkeypatch.setattr(cerebro, "conversar", lambda msgs, **k: SimpleNamespace(texto=next(perguntas)))
    nota = lambda n: {"nota": n, "melhoria": "x"}  # noqa: E731
    fb = {"criterios": {"tecnico": nota(8), "estrutura": nota(6), "comunicacao": nota(7), "julgamento": nota(5), "fit": nota(9)},
          "veredito": "talvez — sólido no técnico", "melhorar": ["estruture: conclusão → argumentos → riscos"],
          "resposta_modelo": {"pergunta": "WACC", "resposta": "Primeiro, custo do capital próprio pelo CAPM…"}}
    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(fb)))
    s, abertura = entrevista.iniciar("analista_research")
    assert s.cargo == "analista_research" and abertura.endswith("🎤 Bom dia. Como você calcularia o WACC de uma empresa brasileira?")
    entrevista.responder("Primeiro, custo do capital próprio: Treasury de 4,2% + beta × prêmio + risco-país de 2,5%, convertido "
                         "para reais. Em resumo, ponderado pela estrutura de capital.")
    entrevista.responder("Uso o beta do setor do Damodaran realavancado; o risco é a premissa de estrutura de capital.")
    s, texto = entrevista.encerrar()
    met = s.feedback["metricas"]
    assert met["respostas"] == 2 and met["com_numeros_pct"] == 50 and met["estruturadas"] == 1 and met["fala_de_risco"] == 2
    assert s.feedback["nota_final"] == pytest.approx((8 * 30 + 6 * 20 + 7 * 20 + 5 * 15 + 9 * 15) / 100, abs=0.05)
    assert "Veredito: talvez" in texto and "Resposta-modelo" in texto and entrevista.ativa() is None


# ---------------------------------------------------------------- Telegram
class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def test_telegram_carreira(monkeypatch):
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(JSON_TESE)))
    monkeypatch.setattr(diario, "_cotacao_real", lambda a: {"WEGE3": 50.0, "IBOV": 150000.0}[a])
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(_fontes_oficiais)))
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    t = lambda x: asyncio.run(bot.tratar(111, 1, x))[0].texto  # noqa: E731
    assert "/diario <tese>" in t("/ajuda")
    assert t("/diario " + TESE).startswith("📓 Tese registrada:\n📓 #1 WEG supera o Ibovespa em 6 meses · WEGE3 ▲")
    assert "#1" in t("/diario lista") and "nenhuma fechada" in t("/diario placar")
    assert "Fechada" in t("/diario 1 errou aprendi a respeitar o beta")
    assert "Radar regulatório" in t("/radar 7") and "PLP 255/2026" in t("/radar 30")
    assert "Plano de carreira" in t("/carreira") and "agendada" in t("/carreira prova CNPI 2027-11-10")

    falas = iter(["Fale sobre você.", "Por que research?"])
    monkeypatch.setattr(cerebro, "conversar", lambda msgs, **k: SimpleNamespace(texto=next(falas)))
    assert "Entrevista #1" in t("/entrevista estrategista")
    assert t("Sou assessor há 5 anos e estudo para o CFP.") == "🎤 Por que research?"  # a entrevista captura a mensagem
    monkeypatch.setattr(cerebro, "perguntar", _sem_cerebro)
    assert "Feedback da entrevista" in t("/entrevista fim")
