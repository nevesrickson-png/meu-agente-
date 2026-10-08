"""Fase 14 — organização: tarefas por frase (com lembrete e botões), notas, metas, /hoje, revisão semanal, Google
Agenda (HTTP simulado) e LGPD. Sem internet."""

import asyncio
import json
import time
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from quiron.runtime.agendador import BRT, Agendador
from quiron.servicos.assessoria.datas import extrair
from quiron.servicos.organizacao import google_agenda as ga
from quiron.servicos.organizacao import hoje, metas, notas, tarefas

SEGUNDA = datetime(2026, 10, 5, 15, 0, tzinfo=BRT)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("QUIRON_SEGREDOS", str(tmp_path / "segredos"))
    return tmp_path


def test_frase_vira_texto_data_e_hora():
    h = date(2026, 10, 5)
    casos = {
        "amanhã às 10h ligar para o CLI-012": ("Ligar para o CLI-012", date(2026, 10, 6), (10, 0)),
        "me lembra de mandar a proposta pro CLI-003 sexta": ("Mandar a proposta pro CLI-003", date(2026, 10, 9), None),
        "Revisar carteira do CLI-020 dia 20 às 15h30": ("Revisar carteira do CLI-020", date(2026, 10, 20), (15, 30)),
        "preciso pagar o DAS até dia 20": ("Pagar o DAS", date(2026, 10, 20), None),
        "ligar pro contador às 3 da tarde": ("Ligar pro contador", None, (15, 0)),
        "reunião com CLI-009 quinta da semana que vem 14h": ("Reunião com CLI-009", date(2026, 10, 15), (14, 0)),
        "anota aí que preciso comprar toner": ("Comprar toner", None, None),
        "estudar 2h por dia de CFP": ("Estudar 2h por dia de CFP", None, None),  # duração, não horário
        "sexta passada enviar relatório": ("Sexta passada enviar relatório", None, None),
    }
    for frase, esperado in casos.items():
        assert extrair(frase, h) == esperado, frase


def test_tarefa_com_lembrete_adiar_concluir():
    t = tarefas.criar("amanhã às 10h ligar para o CLI-012", SEGUNDA)
    assert (t.texto, t.prazo, t.hora, t.cliente) == ("Ligar para o CLI-012", "2026-10-06", "10:00", "CLI-012")
    ag = {a.id: a for a in Agendador().listar()}[t.lembrete]
    assert ag.proxima == datetime(2026, 10, 6, 10, 0, tzinfo=BRT) and ag.texto == f"[T{t.id}] Ligar para o CLI-012"
    assert "lembrete 06/10 às 10:00" in tarefas.confirmar(t)
    assert tarefas.por_lembrete(t.lembrete).id == t.id

    so_data = tarefas.criar("pagar DAS dia 20", SEGUNDA)
    assert {a.id: a for a in Agendador().listar()}[so_data.lembrete].proxima == datetime(2026, 10, 20, 8, 0, tzinfo=BRT)
    sem_data = tarefas.criar("estudar CFP", SEGUNDA)
    assert sem_data.lembrete is None and "sem data" in tarefas.confirmar(sem_data)
    passou = tarefas.criar("hoje revisar e-mails", SEGUNDA)  # hoje sem hora depois das 8h: sem lembrete
    assert passou.prazo == "2026-10-05" and passou.lembrete is None
    so_hora = tarefas.criar("às 9h reunião interna", SEGUNDA)  # 9h já passou: vai para amanhã
    assert so_hora.prazo == "2026-10-06"

    adiada = tarefas.adiar(t.id, "1h", SEGUNDA)
    assert (adiada.prazo, adiada.hora) == ("2026-10-05", "16:00") and adiada.lembrete != t.lembrete
    assert t.lembrete not in {a.id for a in Agendador().listar()}  # o lembrete antigo foi cancelado
    adiada = tarefas.adiar(t.id, "sexta às 9h", SEGUNDA)
    assert (adiada.prazo, adiada.hora) == ("2026-10-09", "09:00")
    feita = tarefas.concluir(t.id, SEGUNDA)
    assert feita.concluida_em and adiada.lembrete not in {a.id for a in Agendador().listar()}
    lista = tarefas.descrever_lista(tarefas.listar(hoje=date(2026, 10, 7)), date(2026, 10, 7))
    assert "🔴 Atrasadas" in lista and "Revisar e-mails" in lista and "Ligar para o CLI-012" not in lista
    with pytest.raises(tarefas.TarefaInvalida):
        tarefas.criar("amanhã", SEGUNDA)
    with pytest.raises(tarefas.TarefaInvalida):
        tarefas.adiar(sem_data.id, "quando der", SEGUNDA)
    assert tarefas.remover(sem_data.id) and not tarefas.remover(sem_data.id)


def test_notas_e_metas():
    n1 = notas.criar("Ideia de pauta: duration explicada com gangorra #conteudo").id
    time.sleep(0.02)
    n2 = notas.criar("CLI-012 gosta de explicações com números #cliente").id
    assert [n.id for n in notas.buscar("gangorra")] == [n1]
    assert [n.id for n in notas.buscar("explicacoes")] == [n2]  # sem acento acha com acento
    assert [n.id for n in notas.buscar("#cliente")] == [n2] and notas.buscar("")[0].id == n2
    assert notas.remover(n1) and notas.buscar("gangorra") == []

    h = date(2026, 10, 7)  # quarta
    assert metas.interpretar("captar 2 milhões até dezembro", h)[1:] == (2_000_000, "R$", "total", "2026-12-31")
    assert metas.interpretar("estudar 5 horas por semana", h)[1:] == (5, "horas", "semanal", "")
    assert metas.interpretar("fazer 20 reuniões por mês", h)[1:] == (20, "reuniões", "mensal", "")
    assert metas.interpretar("R$ 50 mil de aporte até março", h)[1:] == (50_000, "R$", "total", "2027-03-31")
    with pytest.raises(metas.MetaInvalida):
        metas.criar("ser mais organizado", h)
    m = metas.criar("estudar 5 horas por semana", h)
    metas.registrar(m.id, 2, quando=datetime(2026, 10, 6, 20))  # terça desta semana
    metas.registrar(m.id, 9, quando=datetime(2026, 9, 29, 20))  # semana passada: não conta
    p = metas.progresso(m, h)
    assert p["feito"] == 2 and p["pct"] == 40 and p["esperado_pct"] == pytest.approx(2 / 6 * 100)
    assert "2 horas de 5 horas nesta semana (40%) · no ritmo ✅" in metas.descrever(m, h)
    assert metas.encerrar(m.id) and metas.listar() == []


def test_hoje_e_revisao_semanal(dados):
    agora = datetime(2026, 10, 5, 7, 0, tzinfo=BRT)
    tarefas.criar("hoje às 11h ligar para o CLI-012", agora)
    tarefas.criar("estudar CFP", agora)
    t3 = tarefas.criar("amanhã enviar relatório", agora)
    metas.criar("estudar 5 horas por semana", agora.date())
    texto = hoje.montar_hoje(agora)
    assert texto.startswith("☀️ **Hoje — segunda, 05/10/2026")
    assert "Ligar para o CLI-012 — hoje 11:00" in texto and "1 sem data" in texto and "🎯" in texto
    assert "Google Agenda" not in texto  # sem credencial: não polui o dia

    tarefas.concluir(t3.id, datetime(2026, 10, 6, 9, tzinfo=BRT))
    tarefas.criar("dia 13 às 10h reunião de equipe", agora)
    rev = hoje.montar_revisao(datetime(2026, 10, 11, 18, 0, tzinfo=BRT))
    assert "Revisão da semana — 05/10 a 11/10" in rev
    assert "✅ 1 tarefa(s) concluída(s) · 4 criada(s) · 1 atrasada(s)" in rev and "· Enviar relatório" in rev
    assert "Próxima semana (12/10–18/10)" in rev and "Reunião de equipe — 13/10 10:00" in rev
    assert "Qual é a UMA prioridade" in rev


# ---------------------------------------------------------------- Google Agenda (HTTP simulado)
def _credencial(dados, token=True, expira=0):
    pasta = dados / "segredos"
    pasta.mkdir(exist_ok=True)
    (pasta / "google_oauth.json").write_text(json.dumps({"installed": {"client_id": "id.apps", "client_secret": "seg"}}))
    if token:
        (pasta / "google_token.json").write_text(json.dumps({"refresh_token": "rt", "access_token": "velho", "expira_em": expira}))


def test_google_sem_configuracao_explica_o_que_falta(dados):
    assert not ga.configurado() and "docs/09-GOOGLE-AGENDA.md" in ga.como_configurar()
    with pytest.raises(ga.AgendaIndisponivel):
        ga.eventos_do_dia(date(2026, 10, 5))
    _credencial(dados, token=False)
    assert "autorizar" in ga.como_configurar()


def test_google_link_pkce_e_troca_do_codigo(dados):
    _credencial(dados, token=False)
    verificador, desafio = ga._pkce()
    q = parse_qs(urlparse(ga.link_autorizacao(5555, "est", desafio)).query)
    assert q["redirect_uri"] == ["http://127.0.0.1:5555/"] and q["code_challenge_method"] == ["S256"]
    assert q["scope"] == [ga.ESCOPO] and q["access_type"] == ["offline"] and q["state"] == ["est"]

    def google(req):
        corpo = parse_qs(req.content.decode())
        assert corpo["code"] == ["abc"] and corpo["code_verifier"] == [verificador] and corpo["grant_type"] == ["authorization_code"]
        return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

    ga.trocar_codigo("abc", 5555, verificador, httpx.Client(transport=httpx.MockTransport(google)))
    tok = json.loads(ga.arquivo_token().read_text())
    assert tok["refresh_token"] == "rt" and tok["expira_em"] > time.time() and ga.configurado()


def test_google_renova_token_lista_e_cria_eventos(dados):
    _credencial(dados)
    chamadas = []

    def google(req):
        chamadas.append((req.method, req.url.path))
        if req.url.path == "/token":
            assert parse_qs(req.content.decode())["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"access_token": "novo", "expires_in": 3600})
        assert req.headers["Authorization"] == "Bearer novo"
        if req.method == "GET":
            assert req.url.params["singleEvents"] == "true"
            return httpx.Response(200, json={"items": [
                {"id": "1", "summary": "Reunião CLI-012", "start": {"dateTime": "2026-10-05T14:00:00-03:00"},
                 "end": {"dateTime": "2026-10-05T15:00:00-03:00"}},
                {"id": "2", "summary": "Feriado", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"}},
                {"id": "3", "status": "cancelled", "start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"}}]})
        corpo = json.loads(req.content)
        return httpx.Response(200, json={"id": "9", "summary": corpo["summary"], "start": {"dateTime": corpo["start"]["dateTime"]},
                                         "end": {"dateTime": corpo["end"]["dateTime"]}})

    cli = httpx.Client(transport=httpx.MockTransport(google))
    itens = ga.eventos_do_dia(date(2026, 10, 5), cli)
    assert [e.descrever() for e in itens] == ["📅 14:00–15:00 Reunião CLI-012", "📅 (dia todo) Feriado"]
    assert json.loads(ga.arquivo_token().read_text())["access_token"] == "novo"  # renovado e guardado
    e = ga.evento_de_texto("quinta às 15h reunião com CLI-012 por 1h30", SEGUNDA, cli)
    assert e.titulo == "Reunião com CLI-012" and e.inicio == datetime(2026, 10, 8, 15, 0, tzinfo=BRT)
    assert e.fim - e.inicio == timedelta(hours=1, minutes=30)
    with pytest.raises(ga.AgendaIndisponivel):
        ga.evento_de_texto("reunião com CLI-012 quinta", SEGUNDA, cli)  # sem horário
    assert sum(1 for c in chamadas if c[1] == "/token") == 1  # token renovado só uma vez


def test_google_revogado_pede_nova_autorizacao(dados):
    _credencial(dados)
    cli = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(ga.AgendaIndisponivel, match="Autorize de novo"):
        ga.eventos_do_dia(date(2026, 10, 5), cli)


# ---------------------------------------------------------------- Telegram (aceite) e LGPD
class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def test_aceite_tarefa_por_texto_e_lembrete_chega_com_botoes(monkeypatch):
    """Aceite da Fase 14: "amanhã às 10h ligar para o CLI-012" vira tarefa e o lembrete chega (com Feito/+1h/Amanhã)."""
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    monkeypatch.setattr(tarefas, "_agora", lambda: SEGUNDA)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    assert "/tarefa amanhã às 10h" in asyncio.run(bot.tratar(111, 1, "/ajuda"))[0].texto
    criada = asyncio.run(bot.tratar(111, 1, "/tarefa amanhã às 10h ligar para o CLI-012"))[0]
    assert criada.texto == "📌 Tarefa criada: ☐ #1 Ligar para o CLI-012 — amanhã 10:00 · lembrete 06/10 às 10:00"
    assert asyncio.run(bot.agenda_vencida(datetime(2026, 10, 6, 9, 59, tzinfo=BRT))) == []
    chegou = asyncio.run(bot.agenda_vencida(datetime(2026, 10, 6, 10, 0, 30, tzinfo=BRT)))
    assert [s.texto for s in chegou] == ["⏰ Lembrete: Ligar para o CLI-012 (10:00)"]
    botoes = [b for linha in chegou[0].teclado() for b in linha]
    assert [r for r, _ in botoes] == ["✅ Feito", "⏰ +1h", "📅 Amanhã"] and all(len(d) <= 64 for _, d in botoes)
    monkeypatch.setattr(tarefas, "_agora", lambda: datetime(2026, 10, 6, 10, 1, tzinfo=BRT))
    editar, _ = asyncio.run(bot.clicar_organizacao(111, botoes[1][1]))
    assert editar == "⏰ Adiada: ☐ #1 Ligar para o CLI-012 — hoje 11:01 · lembrete 06/10 às 11:01"
    editar, _ = asyncio.run(bot.clicar_organizacao(111, botoes[0][1]))
    assert editar == "✅ Feito: Ligar para o CLI-012"
    assert asyncio.run(bot.agenda_vencida(datetime(2026, 10, 6, 11, 5, tzinfo=BRT))) == []  # feita: lembrete cancelado

    assert "Nenhuma tarefa pendente" in asyncio.run(bot.tratar(111, 1, "/tarefas"))[0].texto
    assert "Meta criada" in asyncio.run(bot.tratar(111, 1, "/meta estudar 5 horas por semana"))[0].texto
    assert "1 horas de 5 horas" in asyncio.run(bot.tratar(111, 1, "/meta 1 +1"))[0].texto
    assert "Anotado" in asyncio.run(bot.tratar(111, 1, "/nota pauta duration #conteudo"))[0].texto
    assert "Hoje —" in asyncio.run(bot.tratar(111, 1, "/hoje"))[0].texto
    assert "Google" in asyncio.run(bot.tratar(111, 1, "/evento quinta às 15h reunião"))[0].texto  # sem credencial: explica


def test_rotina_de_comando_roda_direto(monkeypatch):
    from quiron.nucleo.config import Config
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    bot.agente.agendador.criar("/revisao", "tarefa", "semanal domingo 18:00", None, agora=SEGUNDA)
    saidas = asyncio.run(bot.agenda_vencida(datetime(2026, 10, 11, 18, 0, 30, tzinfo=BRT)))
    assert saidas[0].texto.startswith("🗓️ **Revisão da semana")


def test_esquecer_apaga_tarefas_e_notas_do_cliente():
    from quiron.servicos import lgpd

    tarefas.criar("amanhã às 10h ligar para o CLI-012", SEGUNDA)
    tarefas.criar("ligar para o CLI-0120", SEGUNDA)
    notas.criar("CLI-012 prefere WhatsApp")
    r = lgpd.esquecer_cliente("CLI-012")
    assert r.itens["tarefas/notas/metas"] == 1 and r.itens["lembretes"] == 1  # a nota agora mora no Cérebro
    assert r.itens["linhas no Cérebro (notas do Obsidian)"] == 1
    assert [t.texto for t in tarefas.listar()] == ["Ligar para o CLI-0120"] and notas.buscar("WhatsApp") == []


def test_terminal_tarefa_rapida(monkeypatch):
    from fastapi.testclient import TestClient

    from quiron.terminal.backend import app as terminal
    from quiron.terminal.backend import dados as dados_terminal

    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    c = TestClient(terminal.app)
    h = {"X-Quiron": "terminal"}
    assert c.post("/api/organizacao/tarefa", json={"texto": "amanhã às 10h ligar para o CLI-012"}).status_code == 403
    r = c.post("/api/organizacao/tarefa", json={"texto": "amanhã às 10h ligar para o CLI-012"}, headers=h).json()
    assert "Ligar para o CLI-012" in r["descricao"]
    assert dados_terminal.tarefas()["tarefas"][0]["texto"] == "Ligar para o CLI-012"
    assert dados_terminal.tarefas()["itens"] == []  # o lembrete da tarefa não aparece duplicado nas rotinas
    assert c.post(f"/api/organizacao/tarefa/{r['id']}/feito", headers=h).json()["descricao"] == "✅ Ligar para o CLI-012"
    assert c.post("/api/organizacao/tarefa", json={"texto": "x"}, headers=h).status_code == 400
