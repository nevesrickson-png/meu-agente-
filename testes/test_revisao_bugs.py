"""Regressões da revisão de 06/10/2026 (quatro revisores por área) — tudo sem internet."""

import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest

from quiron.nucleo.config import Config


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def _bot():
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    return BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {7})


# ---------------------------------------------------------------- bot
def test_rotina_do_briefing_nao_vira_transcricao_do_pos(monkeypatch):
    from quiron.runtime.agendador import BRT
    from quiron.servicos.mercado import briefing

    monkeypatch.setattr(briefing, "completo", lambda *a, **k: "☀️ **Briefing** de teste")
    bot = _bot()
    bot.assessoria.esperando_pos[7] = "CLI-012"  # /pos aberto à noite, esperando o áudio
    agora = datetime.now(BRT)
    bot.agente.agendador.criar("Faça meu briefing.", "tarefa", "diario 07:30", None, agora=agora)
    saidas = asyncio.run(bot.agenda_vencida(agora + timedelta(days=1, hours=1)))
    assert saidas and saidas[0].texto.startswith("☀️ **Briefing**")
    assert bot.assessoria.esperando_pos.get(7) == "CLI-012"  # o pós-reunião continua esperando o áudio


def test_um_item_com_erro_nao_derruba_a_agenda(monkeypatch):
    from quiron.runtime.agendador import BRT
    from quiron.servicos.mercado import briefing

    def quebra(*a, **k):
        raise RuntimeError("fonte fora")

    monkeypatch.setattr(briefing, "completo", quebra)
    bot = _bot()
    agora = datetime.now(BRT)
    bot.agente.agendador.criar("Faça meu briefing.", "tarefa", "diario 07:30", None, agora=agora)
    bot.agente.agendador.criar("ligar para o CLI-001", "lembrete", "uma vez", agora + timedelta(minutes=1), agora=agora)
    saidas = asyncio.run(bot.agenda_vencida(agora + timedelta(days=1, hours=1)))
    textos = " | ".join(s.texto for s in saidas)
    assert "Lembrete: ligar para o CLI-001" in textos and "Não consegui fazer agora" in textos


def test_para_html_italico_com_sublinhado():
    from quiron.runtime.telegram_bot import para_html

    assert para_html("_Fontes: Yahoo · BC._ dados_do_cliente") == "<i>Fontes: Yahoo · BC.</i> dados_do_cliente"


def test_rotas_lembre_que_e_cartas():
    from quiron.runtime.roteamento import rotear

    assert rotear("lembre que hoje eu prefiro respostas curtas")[0] == "lembrar"
    assert rotear("me lembra amanhã às 10h de ligar")[0] == "tarefa"
    assert rotear("lembre que segunda às 10h tenho reunião")[0] == "tarefa"


def test_simular_entende_valor_sem_rotulo():
    from quiron.servicos.planejamento.simulador import ler_frase

    assert ler_frase("500 mil aporte 5 mil 40 anos") == {"idade": 40, "aporte_mensal": 5000.0, "patrimonio": 500000.0}
    assert ler_frase("quero juntar 2 milhões aportando 5 mil") == {"aporte_mensal": 5000.0, "meta": 2000000.0}


# ---------------------------------------------------------------- fila de análises
def test_orfa_so_volta_se_o_dono_morreu(tmp_path):
    from quiron.servicos.analise import fila as mod

    f = mod.Fila(tmp_path / "a.db", tmp_path / "rel")
    t = f.pedir("renda_fixa_comparativo", {})
    antiga = (datetime.now() - timedelta(hours=2)).isoformat()
    with f._con() as c:  # rodando há 2 h, por um processo VIVO (este): análise lenta, não órfã
        c.execute("UPDATE tarefas SET situacao='rodando', iniciada_em=?, dono=? WHERE id=?", (antiga, f.dono, t.id))
    assert f.recuperar_orfas() == 0
    with f._con() as c:  # processo morto: volta para a fila
        c.execute("UPDATE tarefas SET dono=? WHERE id=?", (f.dono.rsplit(":", 1)[0] + ":999999999", t.id))
    assert f.recuperar_orfas() == 1 and f.obter(t.id).situacao == "na fila"


# ---------------------------------------------------------------- mercado
def test_cambio_do_dia_contra_a_ptax(monkeypatch):
    from quiron.servicos.mercado import bcb, cotacoes

    monkeypatch.setattr(bcb, "sgs", lambda k, n=2: bcb.Serie(k, k, "R$", [bcb.Ponto(date(2026, 10, 2), 5.22),
                                                                        bcb.Ponto(date(2026, 10, 5), 5.00)], "BC", datetime.now(), False))
    var, nota = cotacoes._variacao_contra_ptax("USDBRL", 4.975, datetime(2026, 10, 6))
    assert round(var, 2) == -0.5 and "PTAX de 05/10" in nota  # e não os −4,7% da barra repetida do Yahoo


def test_desempenho_em_dolar_para_ouro_e_cripto(monkeypatch):
    from quiron.servicos.mercado import cotacoes, painel

    serie = [(datetime(2026, 1, 2) + timedelta(days=i), 100.0 + i) for i in range(270)]
    monkeypatch.setattr(cotacoes, "historico", lambda a, p="1y": serie)
    assert "US$" in painel.desempenho("ouro") and "R$" not in painel.desempenho("BTC-USD")
    assert "R$" in painel.desempenho("TRXF11")


def test_janela_do_bcb_nao_se_renova_sozinha(monkeypatch):
    from quiron.servicos.mercado import bcb

    chamadas = {"api": 0, "soap": 0}

    def api(codigo, n):
        chamadas["api"] += 1
        raise bcb.FonteIndisponivel("recusou")

    def soap(codigo):
        chamadas["soap"] += 1
        r = type("R", (), {"fonte": "BC", "obtido_em": datetime.now(), "desatualizado": False})()
        return [bcb.Ponto(date(2026, 10, 1), 13.75)], r

    monkeypatch.setattr(bcb, "_pontos_api", api)
    monkeypatch.setattr(bcb, "_pontos_soap", soap)
    monkeypatch.setattr(bcb, "_api_fora_ate", 0.0)
    bcb.sgs("selic_meta")
    fim = bcb._api_fora_ate
    bcb.sgs("selic_meta")  # dentro da janela: não tenta a API e não empurra a janela
    assert chamadas == {"api": 1, "soap": 2} and bcb._api_fora_ate == fim


def test_preferencias_nao_deixam_sem_fonte_ativa(monkeypatch):
    from quiron.servicos import preferencias

    monkeypatch.setattr(preferencias, "ler_yaml", lambda nome, com_ajustes=True: {"fontes": [
        {"nome": "A"}, {"nome": "B", "ativo": False}]} if nome == "fontes_noticias" else {})
    with pytest.raises(preferencias.PreferenciaInvalida):
        preferencias.salvar({"noticias": [{"nome": "A", "ativa": False}]})


# ---------------------------------------------------------------- cartas, imóveis, resumo
def test_datas_das_cartas_sem_falso_mes():
    from quiron.servicos.cartas.coleta import extrair_data

    hoje = date(2026, 10, 6)
    assert extrair_data("https://x.com/novidades/2025/03/carta.pdf", hoje) == "2025-03-01"  # "novidades" não é novembro
    assert extrair_data("setor 2025", hoje) == ""
    assert extrair_data("Março 2026", hoje) == "2026-03-01" and extrair_data("carta-out-2026", hoje) == "2026-10-01"


def test_ler_carta_nao_segue_redirecionamento_para_rede_interna(monkeypatch):
    from quiron.servicos.cartas import coleta

    monkeypatch.setattr(coleta, "link_conhecido", lambda u: True)
    monkeypatch.setattr(coleta, "permitido", lambda u, c: True)
    monkeypatch.setattr(coleta, "_endereco_publico", lambda u: "127.0.0.1" not in u)
    redirecionador = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1:8765/api/sistema"}))
    real = httpx.Client
    monkeypatch.setattr(coleta.httpx, "Client", lambda **k: real(transport=redirecionador, **{x: v for x, v in k.items() if x != "transport"}))
    assert "Só leio cartas" in coleta.ler_carta("https://gestora.com.br/carta.pdf")


def test_data_conhecida_da_carta_nao_some(dados):
    from quiron.servicos.cartas import coleta

    sit = coleta.Situacao("G", "gestora", "https://g.com", "ativa", conferido_em="2026-10-06T10:00:00+00:00")
    coleta._gravar(sit, [coleta.Carta("G", "Carta de setembro", "https://g.com/c.pdf", "2026-09-01")])
    coleta._gravar(sit, [coleta.Carta("G", "Carta de setembro", "https://g.com/c.pdf", "")])  # leitura sem data
    assert coleta.da_fonte("G")[0]["data"] == "2026-09-01"


def test_uf_do_imovel_pega_a_ultima_sigla_valida():
    from quiron.servicos.fundos.fii_imoveis import local

    assert local("Galpão CD, Rod. Anhanguera km 30, Cajamar - SP") == ("Cajamar", "SP")
    assert local("Rua A, 10 - Bloco AB, Barueri/SP") == ("Barueri", "SP")


def test_carteira_do_fii_funciona_sem_internet(monkeypatch):
    from quiron.servicos.fundos import cvm, fii_imoveis

    tentativas = []

    def sem_rede(url):
        tentativas.append(url)
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(cvm, "baixar", sem_rede)
    c = fii_imoveis.carteira("11.728.688/0001-47")
    assert c["imoveis"] == [] and tentativas
    n = len(tentativas)
    fii_imoveis.carteira("11.728.688/0001-47")  # a 2ª consulta da mesma análise não tenta baixar de novo
    assert len(tentativas) == n


def test_filtros_do_resumo_nao_casam_dentro_de_palavras():
    import re

    from quiron.servicos.mercado.resumo import FILTRO_SECAO as F

    assert not re.search(F["bolsa_eua"], "Sony company in Germany", re.I) and re.search(F["bolsa_eua"], "Bolsas de NY sobem", re.I)
    assert not re.search(F["renda_fixa"], "Saudi Aramco", re.I) and not re.search(F["moedas"], "juro real sobe", re.I)
