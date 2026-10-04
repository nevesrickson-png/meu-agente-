"""Runtime "bot próprio": laço do agente com servidores MCP reais e cérebro simulado; regras do Telegram."""

import asyncio

import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.config import Config
from quiron.runtime import agente as mod_agente
from quiron.runtime.agente import Agente, indice_skills, prompt_sistema
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.telegram_bot import BotQuiron, dividir


def cerebro_roteirizado(passos):
    """Simula o modelo: cada chamada devolve o próximo passo do roteiro e registra o que recebeu."""
    recebidos = []

    def conversar(mensagens, ferramentas=None, **kw):
        recebidos.append({"mensagens": list(mensagens), "ferramentas": [f["function"]["name"] for f in ferramentas or []]})
        passo = passos[len(recebidos) - 1]
        if isinstance(passo, str):
            return cerebro.Turno(passo, [], {"role": "assistant", "content": passo}, "simulado")
        chamadas = [{"id": f"c{i}", "nome": n, "argumentos": a} for i, (n, a) in enumerate(passo)]
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": c["id"], "type": "function",
               "function": {"name": c["nome"], "arguments": "{}"}} for c in chamadas]}
        return cerebro.Turno("", chamadas, msg, "simulado")

    return conversar, recebidos


def test_prompt_tem_persona_e_skills():
    p = prompt_sistema()
    assert "Quíron" in p and "RASCUNHO" in p and "`briefing`" in p and "horário de Brasília" in p
    assert "biblioteca-estudo" in indice_skills()


def test_agente_usa_skill_e_ferramenta_mcp_de_verdade(monkeypatch):
    conversar, recebidos = cerebro_roteirizado([
        [("ler_skill", {"nome": "briefing"})],
        [("quiron_sistema__ping", {})],
        "Quíron no ar — teste concluído.",
    ])
    monkeypatch.setattr(cerebro, "conversar", conversar)

    async def rodar():
        async with ConexaoMCP(servidores=["quiron-sistema"]) as c:
            assert not c.falhas
            return await Agente(c, Config()).responder("está no ar?", [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}])

    reg = asyncio.run(rodar())
    assert reg.resposta == "Quíron no ar — teste concluído."
    assert reg.ferramentas == ["ler_skill", "quiron_sistema__ping"]
    assert "quiron_sistema__ping" in recebidos[0]["ferramentas"] and "ler_skill" in recebidos[0]["ferramentas"]
    resultados = [m for m in recebidos[2]["mensagens"] if m.get("role") == "tool"]
    assert "Skill: briefing" in resultados[0]["content"] and resultados[1]["content"].startswith("pong — Quíron no ar")
    assert recebidos[0]["mensagens"][1]["content"] == "oi"  # histórico entra na conversa


def test_agente_para_depois_do_limite_e_trata_cerebro_fora(monkeypatch):
    conversar, _ = cerebro_roteirizado([[("ler_skill", {"nome": "x"})]] * 20)
    monkeypatch.setattr(cerebro, "conversar", conversar)

    class SemMCP:
        ferramentas = []

    reg = asyncio.run(Agente(SemMCP(), Config()).responder("loop"))
    assert "poucas etapas" in reg.resposta and len(reg.ferramentas) == mod_agente.MAX_PASSOS

    def fora(*a, **k):
        raise cerebro.CerebroIndisponivel("cota esgotada")

    monkeypatch.setattr(cerebro, "conversar", fora)
    reg = asyncio.run(Agente(SemMCP(), Config()).responder("oi"))
    assert "indisponível" in reg.resposta and "cota" in reg.erro


def test_dividir_respostas_longas():
    texto = ("parágrafo " * 50 + "\n\n") * 20
    partes = dividir(texto, 1000)
    assert all(len(p) <= 1000 for p in partes) and " ".join(partes).split() == texto.split()  # nada se perde


class AgenteFalso:
    def __init__(self):
        self.perguntas = []

    async def responder(self, pergunta, historico=None):
        self.perguntas.append((pergunta, historico))
        return mod_agente.Registro(pergunta, resposta=f"resposta para: {pergunta}")


class MemoriaFalsa:
    def __init__(self):
        self.dados = {}

    def ler(self, chat):
        return self.dados.get(chat, [])

    def guardar(self, chat, p, r):
        self.dados[chat] = self.ler(chat) + [{"role": "user", "content": p}, {"role": "assistant", "content": r}]

    def apagar(self, chat):
        self.dados.pop(chat, None)


def test_bot_so_responde_ao_rickson_e_traduz_comandos():
    ag, mem = AgenteFalso(), MemoriaFalsa()
    bot = BotQuiron(ag, mem, {111})
    assert asyncio.run(bot.tratar(999, 1, "oi")) == []  # estranho: silêncio
    assert ag.perguntas == []
    assert asyncio.run(bot.tratar(111, 1, "/briefing")) == ["resposta para: Faça meu briefing."]
    asyncio.run(bot.tratar(111, 1, "/noticia copom"))
    assert ag.perguntas[-1][0] == "O que está saindo sobre copom?" and len(ag.perguntas[-1][1]) == 2  # lembra a conversa
    assert asyncio.run(bot.tratar(111, 1, "/novo")) == ["Conversa reiniciada."] and mem.ler(1) == []
