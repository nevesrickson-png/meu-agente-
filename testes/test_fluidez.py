"""Bot mais fluido: fala normal → função direta, continuidade, seleção de ferramentas, progresso e sugestões."""

import asyncio

import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.config import Config
from quiron.runtime.agente import Agente
from quiron.runtime.roteamento import descrever_ferramenta, rotear, selecionar_ferramentas
from quiron.runtime.telegram_bot import BotQuiron, separar_sugestoes


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def _f(nome, desc=""):
    return {"type": "function", "function": {"name": nome, "description": desc, "parameters": {"type": "object", "properties": {}}}}


FERRAMENTAS = [
    _f("ler_skill", "lê uma skill"), _f("lembrar", "guarda um fato"),
    _f("quiron_mercado__taxas", "Selic, CDI, IPCA e câmbio do dia"),
    _f("quiron_mercado__cotacao", "cotação de ação ou índice"),
    _f("quiron_mercado__buscar_fundo", "procura fundos de investimento na CVM"),
    _f("quiron_organizacao__hoje", "o dia: tarefas e agenda"),
    _f("quiron_organizacao__criar_tarefa", "cria tarefa com lembrete"),
    _f("quiron_assessoria__simular_patrimonio", "simulador de patrimônio e aposentadoria"),
    _f("quiron_biblioteca__buscar", "busca trechos nos livros"),
    _f("quiron_academia__questao", "questão de prova do CFP"),
    _f("quiron_conteudo__pauta", "ideias de post"),
] + [_f(f"quiron_carreira__f{i}", "radar regulatório de normas da CVM") for i in range(40)]


@pytest.mark.parametrize("frase, esperado", [
    ("Me lembra amanhã às 10h de ligar pro CLI-012.", ("tarefa", "amanhã às 10h de ligar pro CLI-012")),
    ("terminei a 3", ("feito", "3")),
    ("terminei a tarefa 5", ("feito", "5")),
    ("adia a 3 para sexta", ("adiar", "3 sexta")),
    ("o que tenho hoje?", ("hoje", "")),
    ("Bom dia, o que tenho pra hoje", ("hoje", "")),
    ("minhas tarefas", ("tarefas", "")),
    ("anota: estudar duration", ("nota", "estudar duration")),
    ("anota reunião sexta 15h com CLI-004", ("tarefa", "reunião sexta 15h com CLI-004")),
    ("me dá uma questão de renda fixa", ("questoes", "renda fixa")),
    ("quero fazer um simulado", ("simulado", "")),
    ("o que você sabe sobre mim", ("memoria", "")),
    ("o que fizemos hoje", ("memoria", "hoje")),
    ("Lembre que prefiro respostas curtas", ("lembrar", "prefiro respostas curtas")),
    ("tem norma nova", ("radar", "novidades")),
    ("me dá ideias de post", ("pauta", "")),
])
def test_fala_normal_vira_funcao_direta(frase, esperado):
    assert rotear(frase) == esperado


@pytest.mark.parametrize("frase", [
    "qual a selic hoje?", "me lembra de comprar pão", "ok 5", "pronto", "quando posso parar de trabalhar?", "/hoje", "",
    "questões de ética são sempre difíceis de entender, por que?", "linha 1\nlinha 2", "x" * 500,
])
def test_o_resto_vai_para_a_ia(frase):
    assert rotear(frase) is None


def test_patrimonio_com_numeros_vai_para_o_simulador():
    frase = "Quando posso parar de trabalhar com 1 milhão investido e 8 mil por mês de aporte?"
    assert rotear(frase) == ("simular", frase)


def test_selecao_manda_so_as_ferramentas_do_assunto():
    sel = [f["function"]["name"] for f in selecionar_ferramentas(FERRAMENTAS, "qual a selic e o cdi hoje?", limite=8)]
    assert "ler_skill" in sel and "lembrar" in sel  # internas sempre
    assert "quiron_mercado__taxas" in sel
    assert len(sel) <= 10
    citada = selecionar_ferramentas(FERRAMENTAS, "oi", contexto="use quiron_conteudo__pauta", limite=8)
    assert "quiron_conteudo__pauta" in [f["function"]["name"] for f in citada]
    poucas = FERRAMENTAS[:6]
    assert selecionar_ferramentas(poucas, "qualquer coisa") == poucas  # poucas: manda todas
    assert descrever_ferramenta("quiron_mercado__taxas") == "dados de mercado"


def test_sugestoes_viram_botoes():
    texto, itens = separar_sugestoes("A Selic está em 15%.\n\n» Ver a curva de juros\n» **Comparar CDB e LCI**\n")
    assert texto == "A Selic está em 15%." and itens == ["Ver a curva de juros", "Comparar CDB e LCI"]
    assert separar_sugestoes("sem sugestão") == ("sem sugestão", [])


class MCPFalso:
    ferramentas = FERRAMENTAS[2:]

    async def chamar(self, nome, args):
        return "Selic 15,00% a.a."


def test_agente_seleciona_avisa_progresso_e_bot_cria_botoes(monkeypatch):
    recebidas, avisos = [], []

    def conversar(mensagens, ferramentas=None, **kw):
        recebidas.append([f["function"]["name"] for f in ferramentas])
        if len(recebidas) == 1:
            return cerebro.Turno("", [{"id": "c1", "nome": "quiron_mercado__taxas", "argumentos": {}}],
                                 {"role": "assistant", "content": "", "tool_calls": []}, "simulado")
        return cerebro.Turno("Selic em 15%.\n» Ver a curva", [], {"role": "assistant", "content": "ok"}, "simulado")

    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(MCPFalso(), Config(), em_segundo_plano=False), {111})

    async def progresso(nome):
        avisos.append(nome)

    saidas = asyncio.run(bot.tratar(111, 1, "qual a selic hoje?", progresso))
    assert avisos == ["quiron_mercado__taxas"]
    assert len(recebidas[0]) < len(FERRAMENTAS) and "quiron_mercado__taxas" in recebidas[0]
    assert saidas[-1].texto == "Selic em 15%."
    rotulo, dado = saidas[-1].linhas[0][0]
    assert rotulo == "» Ver a curva" and dado.startswith("ms:")
    # clicar na sugestão manda o texto como se ele tivesse escrito
    asyncio.run(bot.clicar_sugestao(111, 1, dado))
    assert bot.agente.memoria.historico(1)[-2]["content"] == "Ver a curva"
    assert "expirou" in asyncio.run(bot.clicar_sugestao(111, 1, "ms:zzz"))[0].texto


def test_fala_normal_executa_a_funcao_e_entra_no_contexto(monkeypatch):
    vistos = []

    def conversar(mensagens, ferramentas=None, **kw):
        vistos.append(list(mensagens))
        return cerebro.Turno("Combinado.", [], {"role": "assistant", "content": "Combinado."}, "simulado")

    monkeypatch.setattr(cerebro, "conversar", conversar)
    bot = BotQuiron(Agente(MCPFalso(), Config(), em_segundo_plano=False), {111})
    criada = asyncio.run(bot.tratar(111, 1, "me lembra amanhã às 10h de ligar pro CLI-012"))
    assert not vistos  # função direta: sem IA, instantâneo
    assert "CLI-012" in criada[0].texto
    assert "CLI-012" in asyncio.run(bot.tratar(111, 1, "minhas tarefas"))[0].texto
    asyncio.run(bot.tratar(111, 1, "e se for às 11h?"))  # a IA recebe as trocas diretas como contexto
    conteudos = " ".join(str(m.get("content")) for m in vistos[0])
    assert "me lembra amanhã às 10h de ligar pro CLI-012" in conteudos and "minhas tarefas" in conteudos


def test_continuacao_da_tarefa_recem_criada(monkeypatch):
    assert rotear("na verdade passa para as 11h", 4) == ("adiar", "4 as 11h")
    assert rotear("pronto, fiz", 4) == ("feito", "4")
    assert rotear("na verdade passa para as 11h") is None  # sem tarefa recente: vai para a IA
    monkeypatch.setattr(cerebro, "conversar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria chamar a IA")))
    bot = BotQuiron(Agente(MCPFalso(), Config(), em_segundo_plano=False), {111})
    criada = asyncio.run(bot.tratar(111, 1, "me lembra amanhã às 9h de revisar a carteira do CLI-007"))[0].texto
    assert "revisar a carteira" in criada and "De revisar" not in criada
    remarcada = asyncio.run(bot.tratar(111, 1, "na verdade passa para as 11h"))[0].texto
    assert "11:00" in remarcada and "amanhã" in remarcada
    assert asyncio.run(bot.tratar(111, 1, "pronto, fiz"))[0].texto.startswith("✅ revisar a carteira")
