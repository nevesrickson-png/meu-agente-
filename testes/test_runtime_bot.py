"""Agente do Quíron (runtime próprio): workspace, memória, agendador, permissões/compliance, laço, batimento e Telegram.
O "cérebro" é simulado (sem chave); os servidores MCP são reais."""

import asyncio
from datetime import datetime, timedelta

import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.config import Config
from quiron.runtime import agente as mod_agente
from quiron.runtime import batimento, permissoes
from quiron.runtime.agendador import BRT, Agendador, RecorrenciaInvalida, proxima_execucao
from quiron.runtime.agente import Agente, indice_skills, prompt_sistema
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.memoria import Memoria
from quiron.runtime.telegram_bot import BotQuiron, dividir
from quiron.runtime.workspace import Workspace, carregar_comandos

SEXTA = datetime(2026, 10, 2, 9, 0, tzinfo=BRT)  # sexta-feira


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def cerebro_roteirizado(passos):
    """Simula o modelo: cada chamada devolve o próximo passo e registra o que recebeu."""
    recebidos = []

    def conversar(mensagens, ferramentas=None, **kw):
        recebidos.append({"mensagens": list(mensagens), "ferramentas": [f["function"]["name"] for f in ferramentas or []]})
        passo = passos[min(len(recebidos), len(passos)) - 1]
        if isinstance(passo, str):
            return cerebro.Turno(passo, [], {"role": "assistant", "content": passo}, "simulado")
        chamadas = [{"id": f"c{i}", "nome": n, "argumentos": a} for i, (n, a) in enumerate(passo)]
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": c["id"], "type": "function",
               "function": {"name": c["nome"], "arguments": "{}"}} for c in chamadas]}
        return cerebro.Turno("", chamadas, msg, "simulado")

    return conversar, recebidos


class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


# ---------------------------------------------------------------- workspace e comandos

def test_workspace_memoria_e_diario():
    ws = Workspace.padrao()
    assert "Quem é o Rickson" in ws.ler("USUARIO.md") and "Persona — Quíron" in ws.ler("SOUL.md")
    assert ws.lembrar("prefere respostas curtas").startswith("Guardado")
    assert ws.lembrar("Prefere respostas curtas").startswith("Já estava")
    ws.lembrar("estuda CFP às terças")
    assert len(ws.fatos()) == 2
    assert "Esquecido: 1" in ws.esquecer("CFP") and len(ws.fatos()) == 1
    ws.anotar_diario("teste", SEXTA)
    assert "09:00 teste" in ws.diario(SEXTA)
    (ws.raiz / "USUARIO.md").write_text("editado à mão")
    Workspace.padrao()  # garantir() nunca sobrescreve
    assert ws.ler("USUARIO.md") == "editado à mão"


def test_comandos_em_markdown():
    cmds = carregar_comandos()
    assert {"briefing", "noticia", "estudar", "pilula", "debate"} <= set(cmds)
    assert cmds["noticia"].montar("copom") == "O que está saindo sobre copom?"
    assert cmds["briefing"].descricao


# ---------------------------------------------------------------- memória

def test_memoria_busca_compacta_e_reinicia():
    m = Memoria()
    for i in range(12):
        m.guardar(1, "user", f"pergunta {i} sobre a previdência do CLI-012" if i == 3 else f"pergunta {i}")
        m.guardar(1, "assistant", f"resposta {i}")
    achados = m.buscar("previdencia")  # sem acento também acha
    assert achados and "CLI-012" in achados[0].texto
    resumos = []
    assert m.compactar(1, manter=4, limite=10, resumir=lambda ant, t: resumos.append(t) or "RESUMO X")
    hist = m.historico(1)
    assert "RESUMO X" in hist[0]["content"] and len(hist) == 2 + 4 and "pergunta 0" in resumos[0]
    assert not m.compactar(1, manter=4, limite=10, resumir=lambda a, t: "outro")
    m.reiniciar(1)
    assert m.historico(1) == [] and m.buscar("previdencia")  # contexto zerado, histórico pesquisável


# ---------------------------------------------------------------- agendador

def test_recorrencias():
    assert proxima_execucao("dias_uteis 07:30", SEXTA) == datetime(2026, 10, 5, 7, 30, tzinfo=BRT)  # sexta 9h → segunda
    assert proxima_execucao("diario 18:00", SEXTA) == datetime(2026, 10, 2, 18, 0, tzinfo=BRT)
    assert proxima_execucao("semanal sexta 18:00", SEXTA) == datetime(2026, 10, 2, 18, 0, tzinfo=BRT)
    assert proxima_execucao("semanal segunda 08:00", SEXTA) == datetime(2026, 10, 5, 8, 0, tzinfo=BRT)
    assert proxima_execucao("mensal 1 09:00", SEXTA) == datetime(2026, 11, 1, 9, 0, tzinfo=BRT)
    assert proxima_execucao("uma vez", SEXTA) is None
    with pytest.raises(RecorrenciaInvalida):
        proxima_execucao("toda hora", SEXTA)


def test_agendar_vencer_e_limite_diario():
    ag = Agendador()
    with pytest.raises(ValueError, match="já passou"):
        ag.criar("x", "lembrete", "uma vez", SEXTA - timedelta(hours=1), agora=SEXTA)
    um = ag.criar("ligar para o CLI-012", "lembrete", "uma vez", SEXTA + timedelta(hours=1), agora=SEXTA)
    rec = ag.criar("Faça meu briefing.", "tarefa", "dias_uteis 07:30", None, agora=SEXTA)
    assert [a.id for a in ag.listar()] == [um.id, rec.id]
    assert ag.vencidos(SEXTA) == []
    vencidos = ag.vencidos(SEXTA + timedelta(days=3))  # segunda 9h: os dois venceram
    assert {a.id for a in vencidos} == {um.id, rec.id}
    assert [a.id for a in ag.listar()] == [rec.id] and ag.listar()[0].proxima == datetime(2026, 10, 6, 7, 30, tzinfo=BRT)
    assert ag.cancelar(rec.id) and not ag.listar()
    for _ in range(3):
        ag.registrar_envio("t", SEXTA)
    assert not ag.pode_enviar(SEXTA) and ag.pode_enviar(SEXTA + timedelta(days=1))


# ---------------------------------------------------------------- permissões e compliance

def test_politica_e_aprovacoes():
    assert permissoes.politica("esquecer") == "confirmar"
    assert permissoes.politica("quiron_mercado__briefing") == "livre"
    ap = permissoes.Aprovacoes()
    p = ap.criar("esquecer", {"trecho": "x"}, "Apagar x")
    assert [q.id for q in ap.pendentes()] == [p.id]
    assert ap.decidir(p.id, True).argumentos == {"trecho": "x"}
    assert ap.decidir(p.id, False) is None  # não decide duas vezes


def test_compliance_rascunho_e_rodape():
    r = permissoes.aplicar_compliance("Escreva uma mensagem para o CLI-007 sobre o Copom", "Olá! O Copom cortou a Selic.")
    assert r.startswith(permissoes.MARCA_RASCUNHO)
    assert permissoes.aplicar_compliance("Escreva uma mensagem para o cliente", "RASCUNHO — Olá").count("RASCUNHO") == 1
    r = permissoes.aplicar_compliance("Vale comprar PETR4?", "A tese depende do petróleo.")
    assert r.endswith(permissoes.RODAPE)
    assert permissoes.aplicar_compliance("Como está a Selic?", "Selic em 13,75%.") == "Selic em 13,75%."


# ---------------------------------------------------------------- laço do agente

def test_prompt_tem_persona_usuario_memoria_e_skills():
    ws = Workspace.padrao()
    ws.lembrar("prefere renda fixa para aposentados")
    p = prompt_sistema(workspace=ws)
    assert "Quíron" in p and "Quem é o Rickson" in p and "prefere renda fixa" in p and "`briefing`" in p
    assert "biblioteca-estudo" in indice_skills()


def test_agente_usa_skill_mcp_real_memoria_e_agenda(monkeypatch):
    amanha = (datetime.now(BRT) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    conversar, recebidos = cerebro_roteirizado([
        [("ler_skill", {"nome": "briefing"}), ("quiron_sistema__ping", {})],
        [("lembrar", {"fato": "liga para clientes às sextas"}),
         ("agendar", {"texto": "ligar para o CLI-012", "tipo": "lembrete", "recorrencia": "uma vez", "quando_iso": amanha.strftime("%Y-%m-%dT%H:%M")})],
        "Pronto: guardei e agendei.",
    ])
    monkeypatch.setattr(cerebro, "conversar", conversar)

    async def rodar():
        async with ConexaoMCP(servidores=["quiron-sistema"]) as c:
            ag = Agente(c, Config())
            return ag, await ag.responder("me lembre amanhã às 10h de ligar para o CLI-012", chat=7)

    ag, reg = asyncio.run(rodar())
    assert reg.resposta == "Pronto: guardei e agendei."
    assert reg.ferramentas == ["ler_skill", "quiron_sistema__ping", "lembrar", "agendar"]
    resultados = [m["content"] for m in recebidos[2]["mensagens"] if m.get("role") == "tool"]
    assert "Skill: briefing" in resultados[0] and resultados[1].startswith("pong") and resultados[3].startswith("Agendado: #1")
    assert ag.workspace.fatos()[0].startswith("liga para clientes às sextas")
    assert ag.agendador.listar()[0].texto == "ligar para o CLI-012"
    assert [m["role"] for m in ag.memoria.historico(7)] == ["user", "assistant"]  # conversa guardada


def test_acao_sensivel_vira_pendencia_e_so_executa_aprovada(monkeypatch):
    conversar, _ = cerebro_roteirizado([[("esquecer", {"trecho": "sextas"})], "Pedi sua aprovação."])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    ag = Agente(SemMCP(), Config())
    ag.workspace.lembrar("liga às sextas")
    reg = asyncio.run(ag.responder("esqueça que ligo às sextas"))
    assert len(reg.pendencias) == 1 and ag.workspace.fatos()  # ainda não apagou
    assert "Esquecido" in asyncio.run(ag.executar_aprovada(reg.pendencias[0])) and not ag.workspace.fatos()


def test_limite_de_passos_cerebro_fora_e_compactacao(monkeypatch):
    conversar, _ = cerebro_roteirizado([[("listar_agenda", {})]])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    reg = asyncio.run(Agente(SemMCP(), Config()).responder("loop"))
    assert "poucas etapas" in reg.resposta and len(reg.ferramentas) == mod_agente.MAX_PASSOS

    def fora(*a, **k):
        raise cerebro.CerebroIndisponivel("cota esgotada")

    monkeypatch.setattr(cerebro, "conversar", fora)
    reg = asyncio.run(Agente(SemMCP(), Config()).responder("oi", chat=1))
    assert "indisponível" in reg.resposta and "cota" in reg.erro

    conversar, _ = cerebro_roteirizado(["ok"])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    monkeypatch.setattr(cerebro, "perguntar", lambda *a, **k: cerebro.Resposta("RESUMO", "simulado", []))
    ag = Agente(SemMCP(), Config())
    for i in range(18):
        asyncio.run(ag.responder(f"pergunta {i}", chat=2))
    assert "RESUMO" in ag.memoria.historico(2)[0]["content"]


# ---------------------------------------------------------------- batimento

def test_batimento(monkeypatch):
    ag = Agente(SemMCP(), Config())
    meio_dia = datetime(2026, 10, 2, 12, 0, tzinfo=BRT)
    conversar, _ = cerebro_roteirizado(["NADA"])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    assert asyncio.run(batimento.bater(ag, meio_dia)) is None and ag.agendador.envios_hoje(meio_dia) == 0
    conversar, recebidos = cerebro_roteirizado(["Dólar subiu 2,3% hoje (📊 Yahoo, 12:00)."])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    assert asyncio.run(batimento.bater(ag, meio_dia)).startswith("Dólar subiu")
    assert ag.agendador.envios_hoje(meio_dia) == 1 and "batimento" in ag.workspace.diario(meio_dia)
    assert asyncio.run(batimento.bater(ag, datetime(2026, 10, 2, 23, 30, tzinfo=BRT))) is None  # fora do horário
    ag.agendador.registrar_envio("x", meio_dia)
    ag.agendador.registrar_envio("y", meio_dia)
    assert asyncio.run(batimento.bater(ag, meio_dia)) is None  # limite de 3/dia


# ---------------------------------------------------------------- Telegram

def test_dividir_respostas_longas():
    texto = ("parágrafo " * 50 + "\n\n") * 20
    partes = dividir(texto, 1000)
    assert all(len(p) <= 1000 for p in partes) and " ".join(partes).split() == texto.split()


def test_bot_telegram(monkeypatch):
    conversar, _ = cerebro_roteirizado(["resposta do Quíron"])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    assert asyncio.run(bot.tratar(999, 1, "oi")) == []  # estranho: silêncio
    ajuda = asyncio.run(bot.tratar(111, 1, "/ajuda"))[0].texto
    assert "/briefing" in ajuda and "/agenda" in ajuda
    assert asyncio.run(bot.tratar(111, 1, "/noticia copom"))[0].texto == "resposta do Quíron"
    assert bot.agente.memoria.historico(1)[0]["content"] == "O que está saindo sobre copom?"
    assert "Nada agendado" in asyncio.run(bot.tratar(111, 1, "/agenda"))[0].texto

    conversar, _ = cerebro_roteirizado([[("esquecer", {"trecho": "x"})], "Pedi aprovação."])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot.agente.workspace.lembrar("fato x")
    saidas = asyncio.run(bot.tratar(111, 1, "esqueça x"))
    botoes = saidas[-1].botoes
    assert botoes[0][1].startswith("aprovar:")
    assert asyncio.run(bot.decidir(999, botoes[0][1])) == ""  # estranho não aprova
    assert asyncio.run(bot.decidir(111, botoes[0][1])).startswith("✅ Aprovado")
    assert "já foi decidido" in asyncio.run(bot.decidir(111, botoes[0][1]))

    agora = datetime.now(BRT)
    bot.agente.agendador.criar("ligar para o CLI-012", "lembrete", "uma vez", agora + timedelta(minutes=1), agora=agora)
    assert [s.texto for s in asyncio.run(bot.agenda_vencida(agora + timedelta(minutes=2)))] == ["⏰ Lembrete: ligar para o CLI-012"]


# ---------------------------------------------------------------- velocidade, áudio e rotinas

def test_comando_pre_carrega_a_skill(monkeypatch):
    conversar, recebidos = cerebro_roteirizado(["☀️ Briefing"])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    assert carregar_comandos()["briefing"].skill == "briefing"
    asyncio.run(bot.tratar(111, 1, "/briefing"))
    assert "Skill já carregada para este pedido: briefing" in recebidos[0]["mensagens"][0]["content"]
    assert bot.skills_para("Faça meu briefing.") == ["briefing"] and bot.skills_para("outra coisa") == []


def test_audio_transcreve_pelo_groq(monkeypatch):
    import httpx

    from quiron.runtime import audio

    def groq(req):
        assert req.headers["Authorization"] == "Bearer gk" and b"whisper-large-v3-turbo" in req.content
        return httpx.Response(200, json={"text": " Faça meu briefing. "})

    monkeypatch.setenv("GROQ_API_KEY", "gk")
    assert audio.transcrever(b"OggS...", cliente=httpx.Client(transport=httpx.MockTransport(groq))) == "Faça meu briefing."
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(audio.AudioIndisponivel, match="GROQ_API_KEY"):
        audio.transcrever(b"x")


def test_bot_responde_audio(monkeypatch):
    from quiron.runtime import audio

    monkeypatch.setattr(audio, "transcrever", lambda c, n="voz.ogg": "como está a Selic?")
    conversar, _ = cerebro_roteirizado(["Selic em 13,75%."])
    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    saidas = asyncio.run(bot.tratar_audio(111, 1, b"OggS"))
    assert [s.texto for s in saidas] == ["🎙️ “como está a Selic?”", "Selic em 13,75%."]
    assert asyncio.run(bot.tratar_audio(999, 1, b"OggS")) == []


def test_rotina_padrao_do_briefing_criada_uma_vez():
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    assert bot.garantir_rotinas_padrao() == ["Faça meu briefing.", "/revisao"]
    assert bot.garantir_rotinas_padrao() == []  # não duplica
    a = next(x for x in bot.agente.agendador.listar() if x.texto == "Faça meu briefing.")
    assert (a.tipo, a.recorrencia, a.proxima.strftime("%H:%M")) == ("tarefa", "diario 07:30", "07:30")


def test_ids_permitidos_ignora_usuario_com_arroba(monkeypatch, caplog):
    from quiron.runtime import telegram_bot

    monkeypatch.setattr(telegram_bot, "carregar_config", lambda: None)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "@ricksonrkn, 7592218870")
    with caplog.at_level("WARNING"):
        assert telegram_bot.ids_permitidos() == {7592218870}
    assert "@ricksonrkn" in caplog.text and "userinfobot" in caplog.text
