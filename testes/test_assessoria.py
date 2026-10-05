"""Fase 13 — assessoria do dia a dia: datas ditas, compliance, pós-reunião, treino, objeções, vencimentos, dossiê, LGPD e
o fluxo no Telegram (/pos com áudio, /treino). O cérebro é simulado (sem chave, sem internet)."""

import asyncio
import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from quiron.nucleo import cerebro
from quiron.runtime.agendador import BRT, Agendador
from quiron.servicos.assessoria import compliance, datas, dossie, objecoes, pos_reuniao, treino, vencimentos

SEGUNDA = datetime(2026, 10, 5, 15, 0, tzinfo=BRT)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def _sem_cerebro(*a, **k):
    raise cerebro.CerebroIndisponivel("teste offline")


def test_datas_ditas_viram_calendario():
    h = date(2026, 10, 5)  # segunda
    casos = {"amanhã": "2026-10-06", "depois de amanhã": "2026-10-07", "sexta": "2026-10-09", "semana que vem": "2026-10-12",
             "quinta da semana que vem": "2026-10-15", "dia 20": "2026-10-20", "dia 2": "2026-11-02", "15/10": "2026-10-15",
             "daqui a 2 semanas": "2026-10-19", "em 3 dias úteis": "2026-10-08", "fim do mês": "2026-10-30",
             "mês que vem dia 10": "2026-11-10", "2026-12-01": "2026-12-01"}
    for expr, esperado in casos.items():
        assert str(datas.interpretar(expr, h)) == esperado, expr
    assert datas.interpretar("ontem", h) is None and datas.interpretar("01/01/2020", h) is None
    assert datas.interpretar(None, h) is None
    assert datas.hora("amanhã às 10h") == (10, 0) and datas.hora("14h30") == (14, 30) and datas.hora("3 da tarde") == (15, 0)
    assert datas.somar_dias_uteis(date(2026, 10, 9), 1) == date(2026, 10, 12)  # sexta + 1 útil = segunda


def test_compliance_pega_promessa_risco_e_dado_pessoal():
    alertas = compliance.conferir("Esse CDB é sem risco e rende garantido 1% ao mês. Ano passado rendeu 15%. CPF 123.456.789-09")
    regras = {a.regra for a in alertas}
    assert {"Promessa de rentabilidade", "Negar o risco", "Rentabilidade passada sem ressalva", "CPF no texto"} <= regras
    assert compliance.conferir("O fundo rendeu 12% em 2025; rentabilidade passada não é garantia de rentabilidade futura.") == []
    limpo = "Oi, tudo bem? O CDB vence dia 20. Posso te mostrar as opções de renovação com o mesmo risco na quinta?"
    assert compliance.conferir(limpo) == [] and compliance.resumo([]).startswith("✅")
    assert any(a.regra == "FGC exagerado" for a in compliance.conferir("O FGC garante qualquer valor."))


RESPOSTA_IA = {
    "resumo": ["Cliente vendeu participação na clínica.", "Quer parar aos 60 anos."],
    "decisoes": ["Enviar proposta de alocação"],
    "tarefas": [{"texto": "Enviar proposta de alocação", "responsavel": "assessor", "quando": "sexta que vem"},
                {"texto": "Enviar declaração de IR", "responsavel": "cliente", "quando": "amanhã às 10h"},
                {"texto": "Estudar portabilidade do PGBL", "responsavel": "assessor", "quando": None},
                {"texto": "Prazo que já passou", "responsavel": "assessor", "quando": "ontem"}],
    "proximo_contato": "dia 20 às 10h",
    "ficha": [{"campo": "idade", "valor": "52", "trecho": "ele tem 52 anos"},
              {"campo": "ocupacao", "valor": "médico", "trecho": "é médico"},
              {"campo": "idade_aposentadoria", "valor": "60", "trecho": "parar aos 60"},
              {"campo": "cpf", "valor": "123", "trecho": "não pode"},
              {"campo": "perfil", "valor": "agressivo", "trecho": "rótulo inválido"}],
    "pontos_de_atencao": ["Insatisfeito com o multimercado"],
    "perfil_sinais": ["Esposa tem medo de bolsa"],
}
TRANSCRICAO = ("Reunião com o CLI-012. Tem 52 anos, é médico, CPF 123.456.789-09. Falei que o CDB é sem risco nenhum. "
               "Mando a proposta até sexta que vem; ele manda o IR amanhã às 10h. Próxima reunião dia 20 às 10h.")


def test_pos_reuniao_datas_em_python_lembretes_e_ficha(monkeypatch):
    enviados = []

    def falso(pergunta, **k):
        enviados.append(pergunta)
        return SimpleNamespace(texto="```json\n" + json.dumps(RESPOSTA_IA, ensure_ascii=False) + "\n```")

    monkeypatch.setattr(cerebro, "perguntar", falso)
    r = pos_reuniao.processar("cli-012", TRANSCRICAO, agora=SEGUNDA)
    assert "123.456.789-09" not in enviados[0] and "[oculto]" in enviados[0]  # CPF nunca vai ao modelo
    assert "05/10/2026 (segunda)" in enviados[0]
    prazos = {t.texto: (t.prazo, t.hora, t.combinado, t.responsavel) for t in r.tarefas}
    assert prazos["Enviar proposta de alocação"] == ("2026-10-09", "", True, "assessor")
    assert prazos["Enviar declaração de IR"] == ("2026-10-06", "10:00", True, "cliente")
    assert prazos["Estudar portabilidade do PGBL"] == ("2026-10-07", "", False, "assessor")  # 2 dias úteis
    assert prazos["Prazo que já passou"][2] is False
    assert (r.proximo_contato, r.proximo_contato_hora) == ("2026-10-20", "10:00")
    assert r.ficha == [{"campo": "idade", "valor": 52, "trecho": "ele tem 52 anos"},
                       {"campo": "ocupacao", "valor": "profissional_liberal", "trecho": "é médico"},
                       {"campo": "idade_aposentadoria", "valor": 60, "trecho": "parar aos 60"}]
    assert any("Negar o risco" in c for c in r.compliance) and any("ocultados" in a for a in r.avisos)

    lembretes = {a.texto: a.proxima for a in Agendador().listar()}
    assert lembretes["[CLI-012] Cobrar do cliente: Enviar declaração de IR"] == datetime(2026, 10, 6, 10, 0, tzinfo=BRT)
    assert lembretes["[CLI-012] Enviar proposta de alocação"] == datetime(2026, 10, 9, 9, 0, tzinfo=BRT)
    assert datetime(2026, 10, 20, 10, 0, tzinfo=BRT) in lembretes.values()  # próximo contato
    md = r.markdown()
    assert "cobrar do cliente: Enviar declaração de IR — 06/10 10:00" in md and "(prazo sugerido)" in md

    assert pos_reuniao.listar("CLI-012")[0].id == r.id
    msg = pos_reuniao.aplicar_na_ficha("CLI-012", r.id)
    assert msg.startswith("✅ Ficha atualizada")
    from quiron.servicos.planejamento import ficha as fichas

    f = fichas.carregar("CLI-012")
    assert (f.idade, f.ocupacao, f.idade_aposentadoria) == (52, "profissional_liberal", 60)
    assert "Reunião" in f.observacoes
    assert pos_reuniao.aplicar_na_ficha("CLI-012", r.id) == "Essas sugestões já foram aplicadas."
    with pytest.raises(ValueError):
        pos_reuniao.carregar("CLI-012", "../../segredo")


def test_pos_reuniao_sem_ia_usa_regras(monkeypatch):
    monkeypatch.setattr(cerebro, "perguntar", _sem_cerebro)
    r = pos_reuniao.processar("CLI-007", "Cliente quer reduzir risco. Vou enviar a simulação de renda fixa até quinta. "
                                         "Ele ficou de mandar o extrato do banco amanhã.", agora=SEGUNDA)
    assert r.origem == "regras" and any("regras" in a for a in r.avisos)
    tarefas = {t.texto: (t.prazo, t.responsavel) for t in r.tarefas}
    assert tarefas["Enviar a simulação de renda fixa até quinta"] == ("2026-10-08", "assessor")
    assert ("2026-10-06", "cliente") in tarefas.values()
    with pytest.raises(ValueError):
        pos_reuniao.processar("CLI-007", "curto", agora=SEGUNDA)


def _treino_falso(monkeypatch, feedback):
    falas = iter(["Olha, meu tempo é curto.", "Tenho uns 800 mil espalhados.", "Isso me preocupa, tenho dois filhos.",
                  "Promessa assim não cola.", "Manda aí que eu vejo."])
    monkeypatch.setattr(cerebro, "conversar", lambda msgs, **k: SimpleNamespace(texto="Dr. Henrique: " + next(falas)))
    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(feedback)))


def test_treino_conversa_e_feedback_com_nota_em_python(monkeypatch):
    nota = lambda n: {"nota": n, "evidencia": "x", "melhoria": "y"}  # noqa: E731
    fb = {"criterios": {"rapport": nota(8), "descoberta": nota(7), "suitability": nota(6), "clareza": nota(8),
                        "objecoes": nota(5), "compliance": nota(9), "fechamento": nota(9)},
          "objetivo_oculto_descoberto": True, "objecoes": [{"objecao": "Não tenho tempo", "tratada": True}],
          "pontos_fortes": ["boa pergunta sobre a família"], "melhorar": ["não prometa retorno"],
          "reescritas": [{"disse": "vai ganhar com certeza", "melhor": "não dá para prometer retorno"}], "resumo": "Bom início."}
    _treino_falso(monkeypatch, fb)
    s, abertura = treino.iniciar("medico_ocupado primeira_reuniao dificil")
    assert (s.personagem, s.cenario, s.dificuldade) == ("medico_ocupado", "primeira_reuniao", "dificil")
    assert "🗣️ Dr. Henrique: Olha, meu tempo é curto." in abertura  # tira o "Nome:" que o modelo põe
    assert treino.responder("Obrigado pelo tempo. O que te fez topar essa conversa?").endswith("800 mil espalhados.")
    treino.responder("E pensando na sua família, como você imagina o futuro deles?")
    treino.responder("Pode ficar tranquilo que com certeza vai render 20% ao ano.")
    treino.responder("Te mando um diagnóstico até sexta e marcamos 20 minutos na semana que vem?")
    s, texto = treino.encerrar()
    met = s.feedback["metricas"]
    assert met["perguntas"] == 3 and met["perguntas_abertas"] == 2 and met["proximo_passo"] is True
    assert met["compliance_grave"] is True and any("Certeza" in c for c in met["compliance"])
    # compliance limitado a 3 por alerta grave: (8·15+7·20+6·15+8·15+5·15+3·10+9·10)/100 = 6,65 → 6,7
    assert s.feedback["criterios"]["compliance"]["nota"] == 3.0 and s.feedback["nota_final"] == 6.7
    assert "Nota geral:" in texto and "Objetivo oculto: descoberto" in texto and "Melhor:" in texto
    assert treino.ativa() is None
    assert "Média por critério" in treino.evolucao()
    with pytest.raises(treino.TreinoInvalido):
        treino.responder("oi")


def test_treino_sem_ia_no_feedback_ainda_da_os_numeros(monkeypatch):
    _treino_falso(monkeypatch, {})
    monkeypatch.setattr(cerebro, "perguntar", _sem_cerebro)
    treino.iniciar("aposentada_conservadora")
    treino.responder("Bom dia, Dona Célia! Como a senhora está?")
    treino.responder("Me conta o que a senhora espera desse dinheiro.")
    s, texto = treino.encerrar()
    assert s.feedback["origem"] == "regras" and s.feedback["nota_final"] is None
    assert "Números da conversa" in texto and "Sem IA" in texto


def test_objecoes_acha_a_mais_parecida():
    assert objecoes.buscar("ah, mas meu banco cuida disso pra mim")[0][0] == "gerente_banco"
    assert objecoes.buscar("previdência é furada")[0][0] == "previdencia_furada"
    assert objecoes.buscar("meu vizinho ganhou 20%")[0][0] == "comparacao_vizinho"
    assert objecoes.buscar("quero entender o COE") == []
    assert "Reenquadrar" in objecoes.descrever(*objecoes.buscar("bolsa é cassino")[0])


def _carteira(cliente="CLI-012"):
    from quiron.servicos.carteira import arquivo
    from quiron.servicos.carteira.modelo import Carteira, Posicao

    c = Carteira("Carteira", [Posicao("CDB Banco X", "pos_fixado", 300000, vencimento=date(2026, 11, 20), taxa="110% CDI"),
                              Posicao("Tesouro IPCA+ 2035", "inflacao", 200000, vencimento=date(2035, 5, 15)),
                              Posicao("BOVA11", "acoes", 500000, ticker="BOVA11")], "moderado", cliente)
    return arquivo.salvar(c)


def test_vencimentos_e_dossie(monkeypatch):
    _carteira()
    itens = vencimentos.proximos(90, hoje=date(2026, 10, 5))
    assert [(v.cliente, v.nome, v.valor) for v in itens] == [("CLI-012", "CDB Banco X", 300000)]
    texto = vencimentos.descrever(itens, 90)
    assert "20/11/2026" in texto and "R$ 300.000,00" in texto
    assert "Nenhum vencimento" in vencimentos.descrever([], 30)

    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(RESPOSTA_IA)))
    pos_reuniao.processar("CLI-012", TRANSCRICAO, agora=SEGUNDA)
    d = dossie.montar("cli-012", hoje=date(2026, 10, 5))
    assert d.startswith("DOSSIÊ DE REUNIÃO — CLI-012")
    assert "Ficha de planejamento: não existe" in d
    assert "Ações Brasil: 50,0%" in d and "Concentração: BOVA11 = 50,0%" in d and "Fora da faixa do perfil" in d
    assert "20/11/2026: CDB Banco X" in d and "Últimas reuniões" in d and "Enviar proposta de alocação" in d


def test_esquecer_apaga_reunioes_e_lembretes(monkeypatch, dados):
    from quiron.servicos import lgpd

    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(RESPOSTA_IA)))
    pos_reuniao.processar("CLI-012", TRANSCRICAO, agora=SEGUNDA)
    Agendador().criar("Ligar para o CLI-0120", "lembrete", "uma vez", datetime(2026, 12, 1, 9, tzinfo=BRT), agora=SEGUNDA)
    r = lgpd.esquecer_cliente("CLI-012")
    assert r.itens["anotações de reunião"] == 1 and r.itens["lembretes"] == 5
    assert not (dados / "reunioes" / "CLI-012").exists()
    assert [a.texto for a in Agendador().listar()] == ["Ligar para o CLI-0120"]  # código inteiro: outro cliente fica


def test_telegram_pos_por_audio_e_treino(monkeypatch):
    from quiron.nucleo.config import Config
    from quiron.runtime import audio
    from quiron.runtime.agente import Agente
    from quiron.runtime.telegram_bot import BotQuiron

    class SemMCP:
        ferramentas = []

        async def chamar(self, nome, args):
            return "ok"

    monkeypatch.setattr(cerebro, "perguntar", lambda p, **k: SimpleNamespace(texto=json.dumps(RESPOSTA_IA)))
    monkeypatch.setattr(audio, "transcrever", lambda c, n="voz.ogg": TRANSCRICAO)
    bot = BotQuiron(Agente(SemMCP(), Config()), {111})
    assert "/pos CLI-XXX" in asyncio.run(bot.tratar(111, 1, "/ajuda"))[0].texto
    assert "CÓDIGO" in asyncio.run(bot.tratar(111, 1, "/pos"))[0].texto
    assert "Pode mandar o áudio" in asyncio.run(bot.tratar(111, 1, "/pos CLI-012"))[0].texto
    saidas = asyncio.run(bot.tratar_audio(111, 1, b"OggS"))
    assert saidas[0].texto.startswith("🎙️") and saidas[1].texto.startswith("📝 Pós-reunião CLI-012")
    botoes = [b for linha in saidas[1].teclado() for b in linha]
    assert botoes[0][0] == "📇 Aplicar na ficha" and len(botoes[0][1]) <= 64
    assert asyncio.run(bot.clicar_assessoria(111, botoes[0][1]))[0].texto.startswith("✅ Ficha atualizada")
    n = len(Agendador().listar())
    assert "cancelados" in asyncio.run(bot.clicar_assessoria(111, botoes[1][1]))[0].texto
    assert len(Agendador().listar()) == n - 4  # o lembrete do próximo contato fica

    falas = iter(["Oi, em que posso ajudar?", "Na poupança eu nunca perdi nada."])
    monkeypatch.setattr(cerebro, "conversar", lambda msgs, **k: SimpleNamespace(texto=next(falas)))
    assert "Treino #" in asyncio.run(bot.tratar(111, 1, "/treino aposentada_conservadora"))[0].texto
    assert asyncio.run(bot.tratar(111, 1, "Bom dia! Como a senhora está?"))[0].texto == "🗣️ Dona Célia: Na poupança eu nunca perdi nada."
    monkeypatch.setattr(cerebro, "perguntar", _sem_cerebro)
    assert "Feedback do treino" in asyncio.run(bot.tratar(111, 1, "/treino fim"))[0].texto
    assert "Personagens" in asyncio.run(bot.tratar(111, 1, "/treino opcoes"))[0].texto
