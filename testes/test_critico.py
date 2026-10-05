"""Revisão crítica do bot: LGPD antes da IA, travamentos, mensagens simultâneas, permissões e compliance."""

import asyncio

import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.config import Config
from quiron.runtime import permissoes
from quiron.runtime.agente import Agente, dados_identificaveis
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.roteamento import rotear
from quiron.runtime.telegram_bot import BotQuiron, separar_sugestoes


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def _f(nome, desc=""):
    return {"type": "function", "function": {"name": nome, "description": desc, "parameters": {"type": "object", "properties": {}}}}


class MCPFalso:
    ferramentas = [_f("quiron_mercado__taxas", "Selic e CDI"), _f("quiron_mercado__fii_dados", "fundos imobiliários FII")] + \
        [_f(f"quiron_carreira__f{i}", "radar de normas da CVM") for i in range(45)]

    def __init__(self):
        self.chamadas = []

    async def chamar(self, nome, args):
        self.chamadas.append(nome)
        return "ok"


def _sem_ia(monkeypatch):
    monkeypatch.setattr(cerebro, "conversar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não podia chamar a IA")))


@pytest.mark.parametrize("texto, achado", [
    ("o CPF do cliente é 123.456.789-09", "CPF"),
    ("liga pra ele no (11) 98765-4321", "Telefone"),
    ("manda para joao.silva@gmail.com", "E-mail"),
])
def test_dado_pessoal_nunca_vai_para_a_ia(monkeypatch, texto, achado):
    _sem_ia(monkeypatch)
    ag = Agente(MCPFalso(), Config(), em_segundo_plano=False)
    reg = asyncio.run(ag.responder(texto, chat=1))
    assert achado in reg.resposta and "Não mandei" in reg.resposta
    assert ag.memoria.historico(1) == []  # nem fica no contexto
    assert texto not in ag.longa.linha_do_tempo()  # nem no registro completo


def test_cnpj_de_fundo_e_valores_nao_bloqueiam():
    assert dados_identificaveis("analisa o fundo 12.345.678/0001-90") == []
    assert dados_identificaveis("tenho 1.500.000 investidos e aporto 8 mil") == []
    assert dados_identificaveis("CLI-012 quer se aposentar aos 60") == []


def test_ok_e_pronto_soltos_nao_concluem_tarefa():
    assert rotear("ok 5") is None
    assert rotear("pronto", 4) is None
    assert rotear("pronto, fiz", 4) == ("feito", "4")


def test_acoes_que_apagam_ou_saem_do_quiron_pedem_aprovacao():
    for nome in ("quiron_organizacao__remover_tarefa", "quiron_organizacao__criar_evento", "quiron_mercado__remover_alerta",
                 "quiron_carreira__fechar_tese", "cancelar_agendamento", "esquecer", "quiron_assessoria__esquecer_cliente"):
        assert permissoes.politica(nome) == "confirmar", nome
    assert permissoes.politica("quiron_mercado__taxas") == "livre"


def test_rodape_de_uso_interno_nao_engole_as_sugestoes():
    resposta = "Recomendo comprar WEGE3 pelo preço justo.\n\n» Ver o DCF completo\n» Comparar com o setor"
    final = permissoes.aplicar_compliance("devo comprar WEGE3?", resposta)
    assert "Uso interno" in final
    texto, itens = separar_sugestoes(final)
    assert itens == ["Ver o DCF completo", "Comparar com o setor"] and "Uso interno" in texto


def test_ferramenta_travada_nao_prende_o_bot(monkeypatch):
    monkeypatch.setenv("QUIRON_TIMEOUT_FERRAMENTA", "0.2")

    class Lenta:
        async def call_tool(self, nome, args):
            await asyncio.sleep(5)

    c = ConexaoMCP()
    c._sessoes = {"quiron-mercado": Lenta()}
    resultado = asyncio.run(c.chamar("quiron_mercado__taxas", {}))
    assert resultado.startswith("ERRO") and "não respondeu" in resultado


def test_procurar_ferramentas_libera_o_que_faltou(monkeypatch):
    ofertas = []

    def conversar(mensagens, ferramentas=None, **kw):
        ofertas.append([f["function"]["name"] for f in ferramentas])
        if len(ofertas) == 1:
            return cerebro.Turno("", [{"id": "1", "nome": "procurar_ferramentas", "argumentos": {"assunto": "fundos imobiliários FII"}}],
                                 {"role": "assistant", "content": ""}, "simulado")
        return cerebro.Turno("pronto", [], {"role": "assistant", "content": "pronto"}, "simulado")

    monkeypatch.setattr(cerebro, "conversar", conversar)
    ag = Agente(MCPFalso(), Config(), em_segundo_plano=False)
    asyncio.run(ag.responder("bom dia, tudo certo?", chat=1))
    assert "procurar_ferramentas" in ofertas[0] and "quiron_mercado__fii_dados" not in ofertas[0]
    assert "quiron_mercado__fii_dados" in ofertas[1]


def test_mensagens_simultaneas_nao_se_misturam(monkeypatch):
    """Uma rotina da agenda (/tarefas) rodando enquanto a IA pensa noutra mensagem não pode bagunçar o estado."""
    async def cenario():
        liberar = asyncio.Event()

        def conversar(mensagens, ferramentas=None, **kw):
            return cerebro.Turno("resposta da IA", [], {"role": "assistant", "content": "resposta da IA"}, "simulado")

        monkeypatch.setattr(cerebro, "conversar", conversar)
        bot = BotQuiron(Agente(MCPFalso(), Config(), em_segundo_plano=False), {111})
        original = bot.agente.responder

        async def responder_lento(*a, **k):
            await liberar.wait()
            return await original(*a, **k)

        bot.agente.responder = responder_lento
        conversa = asyncio.create_task(bot.tratar(111, 1, "como está o mercado?"))
        await asyncio.sleep(0.05)
        await bot.tratar(111, 1, "/tarefas")  # direta, no meio
        liberar.set()
        await conversa
        return bot

    bot = asyncio.run(cenario())
    msgs = [m["content"] for m in bot.agente.memoria.historico(1)]
    assert msgs.count("como está o mercado?") == 1  # a da IA guardada uma vez só (pelo agente)
    assert msgs.count("/tarefas") == 1
