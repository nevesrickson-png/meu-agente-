"""Preferências pela tela (ajustes por cima de config/), rotinas padrão criadas uma vez e rotinas só de leitura."""

import asyncio
from datetime import datetime, timedelta

import pytest

from quiron.nucleo.config import Config, ler_yaml, salvar_ajuste
from quiron.runtime.agendador import BRT, Agendador
from quiron.servicos import preferencias


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def test_ajuste_vale_por_cima_do_padrao_e_nao_mexe_no_config():
    original = ler_yaml("watchlist", com_ajustes=False)
    salvar_ajuste("watchlist", {"acoes": ["PETR4"]})
    w = ler_yaml("watchlist")
    assert w["acoes"] == ["PETR4"] and w["indices"] == original["indices"]  # o resto continua o padrão
    assert ler_yaml("watchlist", com_ajustes=False) == original
    salvar_ajuste("persona", {"mensagens_automaticas": {"maximo_por_dia": 5}})
    p = ler_yaml("persona")
    assert p["mensagens_automaticas"]["maximo_por_dia"] == 5 and "prioridade" in p["mensagens_automaticas"]  # mescla funda


def test_ajuste_corrompido_nao_derruba(dados):
    (dados / "ajustes").mkdir()
    (dados / "ajustes" / "watchlist.yaml").write_text("acoes: [PETR4\n", encoding="utf-8")
    assert ler_yaml("watchlist") == ler_yaml("watchlist", com_ajustes=False)


def test_salvar_preferencias_valida_e_grava():
    p = preferencias.salvar({"watchlist": {"acoes": "petr4, wege3 , PETR4", "commodities": "ouro"}, "mensagens_dia": 2})
    assert p["watchlist"]["acoes"] == ["PETR4", "WEGE3"] and p["watchlist"]["commodities"] == ["ouro"]
    assert p["mensagens_dia"] == 2 and Agendador().limite_diario() == 2
    with pytest.raises(preferencias.PreferenciaInvalida):
        preferencias.salvar({"watchlist": {"acoes": "PETR4; <script>"}})
    with pytest.raises(preferencias.PreferenciaInvalida):
        preferencias.salvar({"mensagens_dia": 50})


def test_fontes_desligadas_somem_da_coleta():
    from quiron.servicos.noticias import coleta

    todas = [f["nome"] for f in coleta.ler_fontes()]
    p = preferencias.salvar({"noticias": [{"nome": "Money Times", "ativa": False}, {"nome": "Inexistente", "ativa": False}]})
    nomes = [f["nome"] for f in coleta.ler_fontes()]
    assert "Money Times" not in nomes and len(nomes) == len(todas) - 1
    assert next(f for f in p["noticias"] if f["nome"] == "Money Times")["ativa"] is False
    with pytest.raises(preferencias.PreferenciaInvalida):  # não deixa desligar tudo
        preferencias.salvar({"noticias": [{"nome": n, "ativa": False} for n in todas]})


def test_briefing_troca_horario_e_desliga_sem_duplicar():
    ag = Agendador()
    ag.criar("Faça meu briefing.", "tarefa", "diario 07:30", None)
    preferencias.salvar({"briefing": {"ativo": True, "hora": "06:45", "dias": "dias_uteis"}})
    rotinas = [a for a in Agendador().listar() if "briefing" in a.texto.lower()]
    assert len(rotinas) == 1 and rotinas[0].recorrencia == "dias_uteis 06:45"
    assert preferencias.ler()["briefing"] == {"ativo": True, "hora": "06:45", "dias": "dias_uteis"}
    preferencias.salvar({"briefing": {"ativo": False}})
    assert preferencias.rotina_briefing() is None and preferencias.ler()["briefing"]["ativo"] is False
    with pytest.raises(preferencias.PreferenciaInvalida):
        preferencias.salvar({"briefing": {"ativo": True, "hora": "25:00"}})


class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def test_rotina_padrao_cancelada_nao_volta(monkeypatch):
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {1})
    assert "Faça meu briefing." in bot.garantir_rotinas_padrao()
    r = preferencias.rotina_briefing(bot.agente.agendador)
    bot.agente.agendador.cancelar(r.id)
    assert bot.garantir_rotinas_padrao() == []  # reiniciar o bot não recria
    assert preferencias.rotina_briefing(bot.agente.agendador) is None


def test_rotina_com_lembre_que_nao_vira_fato(monkeypatch):
    """Rotina recorrente cujo texto parece um comando de escrita ("lembre que…") vai para a IA, não para /lembrar."""
    from quiron.nucleo import cerebro
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    monkeypatch.setattr(cerebro, "conversar", lambda *a, **k: cerebro.Turno("ok", [], {"role": "assistant", "content": "ok"}, "simulado"))
    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {1})
    agora = datetime.now(BRT)
    bot.agente.agendador.criar("Lembre que hoje tem reunião com o CLI-004", "tarefa", "diario 09:00", None, agora=agora)
    asyncio.run(bot.agenda_vencida(agora + timedelta(days=1, hours=1)))
    assert bot.agente.longa.resumo()["fatos"] == 0


def test_tesouro_le_o_arquivo_uma_vez(monkeypatch):
    from quiron.servicos.mercado import tesouro

    csv_txt = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha\n"
               "Tesouro Prefixado;01/01/2029;02/10/2026;13,83;13,95;800,00;799,00;799,00\n"
               "Tesouro Prefixado;01/01/2029;01/10/2026;13,86;13,98;799,00;798,00;798,00\n")
    chamadas = []

    def obter(*a, **k):
        chamadas.append(1)
        return type("R", (), {"conteudo": csv_txt, "fonte": "Tesouro", "obtido_em": datetime(2026, 10, 2), "desatualizado": False})()

    monkeypatch.setattr(tesouro, "obter", obter)
    tesouro._MEMO.clear()
    tab = tesouro.titulos_atuais()
    hist, _ = tesouro.historico_taxas("prefixado")
    assert tab.titulos[0].taxa_compra == 13.83 and len(hist) == 2
    assert len(chamadas) == 2 and tesouro._MEMO["chave"][1] == len(csv_txt)  # baixou (cache) 2x, leu o CSV 1x


def test_so_guarda_o_que_difere_do_padrao(dados):
    base = ler_yaml("watchlist", com_ajustes=False)
    preferencias.salvar({"watchlist": {"acoes": "PETR4", "etfs": ", ".join(base["etfs"])}, "mensagens_dia": 3})
    import yaml

    ajuste = yaml.safe_load((dados / "ajustes" / "watchlist.yaml").read_text(encoding="utf-8"))
    assert ajuste == {"acoes": ["PETR4"]}  # ETFs iguais ao padrão não ficam congelados no ajuste
    assert not (dados / "ajustes" / "persona.yaml").exists()
    preferencias.salvar({"watchlist": {"acoes": ""}})
    assert not (dados / "ajustes" / "watchlist.yaml").exists()  # tudo igual ao padrão: arquivo some


def test_briefing_desligado_antes_do_bot_ligar_nao_e_recriado():
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    assert preferencias.ler()["briefing"]["ativo"] is True  # o bot ainda vai criar às 07:30
    preferencias.salvar({"briefing": {"ativo": False}})
    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {1})
    assert "Faça meu briefing." not in bot.garantir_rotinas_padrao()
    assert preferencias.rotina_briefing(bot.agente.agendador) is None
