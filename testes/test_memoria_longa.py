"""Memória persistente em camadas: fatos (com extração automática, atualização e privacidade), episódios, eventos,
recuperação híbrida, MEMORIA.md editável, consolidação, LGPD e integração com agente e bot. Sem internet (IA simulada)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.config import Config
from quiron.runtime.agente import Agente
from quiron.runtime.memoria import Memoria
from quiron.runtime.memoria_longa import Escriba, MemoriaLonga


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.setenv("QUIRON_EMBEDDINGS", "lexico")  # significado aproximado sem download
    return tmp_path


class SemMCP:
    ferramentas = []

    async def chamar(self, nome, args):
        return "ok"


def _resposta(texto):
    return SimpleNamespace(texto=texto)


# ---------------------------------------------------------------- fatos
def test_guardar_sem_repetir_e_sem_dado_pessoal():
    m = MemoriaLonga()
    msg, f = m.adicionar("Rickson prefere respostas curtas", "preferencia", 4, "dito")
    assert msg.startswith("Guardado") and f.id == 1
    assert m.adicionar("rickson PREFERE respostas curtas!", "preferencia")[0].startswith("Já estava")
    assert len(m.fatos()) == 1
    for pessoal in ["CLI-012 tem CPF 123.456.789-00", "telefone do cliente (11) 98765-4321", "e-mail joao@empresa.com.br"]:
        assert "dado pessoal" in m.adicionar(pessoal)[0]
    assert len(m.fatos()) == 1
    assert m.adicionar("CLI-012 é conservador e tem 62 anos", "cliente")[1] is not None  # código é permitido


def test_fato_que_muda_substitui_o_antigo_e_esquecer():
    m = MemoriaLonga()
    _, antigo = m.adicionar("Rickson estuda 3 horas por semana", "estudo")
    assert m.atualizar(antigo.id, "Rickson estuda 6 horas por semana").startswith("Atualizado")
    ativos = m.fatos()
    assert [f.texto for f in ativos] == ["Rickson estuda 6 horas por semana"]
    velho = m.obter(antigo.id)
    assert not velho.ativo and velho.substituido_por == ativos[0].id  # o antigo fica arquivado, não some
    m.adicionar("Rickson torce pelo Corinthians", "perfil")
    assert m.esquecer("corinthians") == "Esquecido: 1 item(ns)."
    assert m.esquecer(f"#{ativos[0].id}") == "Esquecido: 1 item(ns)." and not m.fatos()


def test_operacoes_da_extracao_automatica():
    m = MemoriaLonga()
    _, dito = m.adicionar("Rickson quer ser estrategista de referência", "objetivo", 5, "dito")
    _, extraido = m.adicionar("Rickson usa planilha para carteiras", "trabalho")
    feitos = m.aplicar([
        {"op": "adicionar", "texto": "Rickson faz a prova do CFP em março de 2027", "categoria": "estudo", "importancia": 5},
        {"op": "atualizar", "id": extraido.id, "texto": "Rickson usa o Quíron para analisar carteiras"},
        {"op": "apagar", "id": dito.id},  # o que ele mandou guardar só sai quando ELE pedir
        {"op": "adicionar", "texto": "cliente com CPF 111.222.333-44"},  # recusado
        "lixo",
    ])
    textos = {f.texto for f in m.fatos()}
    assert "Rickson faz a prova do CFP em março de 2027" in textos
    assert "Rickson usa o Quíron para analisar carteiras" in textos and "Rickson usa planilha para carteiras" not in textos
    assert "Rickson quer ser estrategista de referência" in textos
    assert len(feitos) == 2


def test_recupera_o_que_tem_a_ver_com_o_pedido():
    m = MemoriaLonga()
    m.adicionar("Rickson faz a prova do CFP em março de 2027", "estudo", 3)
    m.adicionar("Rickson não gosta de futebol", "perfil", 2)
    m.adicionar("Rickson prefere respostas curtas para ler no celular", "preferencia", 5)
    rel = [f.texto for f in m.relevantes("quando é a minha prova do CFP?")]
    assert rel[0].startswith("Rickson faz a prova do CFP") and not any("futebol" in t for t in rel)
    ctx = m.contexto("quando é a minha prova do CFP?")
    assert "respostas curtas" in ctx.split("### Lembranças")[0]  # importância 5 = núcleo, sempre presente
    assert "prova do CFP" in ctx and "futebol" not in ctx
    assert m.obter(3).usos >= 1


# ---------------------------------------------------------------- episódios e escriba
def _msgs(textos, inicio=None):
    inicio = inicio or datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
    return [(i + 1, (inicio + timedelta(minutes=i)).isoformat(), "user" if i % 2 == 0 else "assistant", t) for i, t in enumerate(textos)]


def test_escriba_cria_episodio_e_extrai_fatos():
    m = MemoriaLonga()
    pedidos = []

    def perguntar(pedido, **k):
        pedidos.append((pedido, k))
        return _resposta(json.dumps({"titulo": "Plano de estudo do CFP", "resumo": "Combinamos estudar o módulo 3 nesta semana.",
                                     "pendencias": ["Fazer simulado mini na sexta"],
                                     "fatos": [{"op": "adicionar", "texto": "Rickson estuda à noite, depois das 21h",
                                                "categoria": "rotina", "importancia": 3}]}))

    esc = Escriba(m, perguntar=perguntar, config=Config(llm_principal="gemini/x", llm_reserva="groq/y"))
    ep = esc.fechar(7, _msgs(["vamos montar meu plano de estudo do CFP", "Claro…", "estudo à noite depois das 21h", "Anotado."]))
    assert ep.titulo == "Plano de estudo do CFP" and ep.pendencias == ["Fazer simulado mini na sexta"]
    assert [f.texto for f in m.fatos()] == ["Rickson estuda à noite, depois das 21h"]
    assert pedidos[0][1]["config"].modelos[0] == "groq/y"  # escriba começa pelo Groq (poupa o Gemini)
    assert m.ultimo_id_episodio(7) == 4
    assert m.episodios_relevantes("simulado do CFP")[0].id == ep.id
    assert "Plano de estudo do CFP" in m.buscar("plano de estudo")


def test_escriba_sem_ia_guarda_episodio_simples():
    m = MemoriaLonga()

    def sem_ia(pedido, **k):
        raise cerebro.CerebroIndisponivel("cota")

    ep = Escriba(m, perguntar=sem_ia).fechar(7, _msgs(["comparar CDB e LCI de 2 anos", "…"]))
    assert ep.titulo.startswith("comparar CDB") and "Pedidos:" in ep.resumo and not m.fatos()


def test_lembre_que_guarda_na_hora_sem_ia():
    m = MemoriaLonga()
    esc = Escriba(m)
    assert esc.lembrete_explicito("Lembre que eu atendo clientes só de manhã").startswith("Guardado")
    assert m.fatos()[0].origem == "dito" and m.fatos()[0].importancia == 4
    assert esc.lembrete_explicito("qual a Selic?") is None
    assert Escriba.tem_pista("a partir de agora quero os números em tabela") and not Escriba.tem_pista("qual a Selic hoje?")


# ---------------------------------------------------------------- MEMORIA.md editável e migração
def test_memoria_md_editavel_pelo_rickson(dados):
    m = MemoriaLonga()
    m.adicionar("Rickson prefere respostas curtas", "preferencia", 4)
    m.adicionar("Rickson torce pelo Corinthians", "perfil", 2)
    md = m.arquivo_md.read_text(encoding="utf-8")
    assert "## Preferências e jeito de trabalhar" in md and "- [#1] Rickson prefere respostas curtas" in md
    md = md.replace("respostas curtas", "respostas curtas e diretas").replace("- [#2] Rickson torce pelo Corinthians\n", "")
    md = md.replace("## Preferências e jeito de trabalhar\n", "## Preferências e jeito de trabalhar\n- Rickson gosta de gráficos simples\n")
    m.arquivo_md.write_text(md, encoding="utf-8")
    mudancas = m.importar_edicoes_md()
    textos = {f.texto: f for f in m.fatos()}
    assert "Rickson prefere respostas curtas e diretas" in textos and "Rickson gosta de gráficos simples" in textos
    assert textos["Rickson gosta de gráficos simples"].categoria == "preferencia"
    assert not any("Corinthians" in t for t in textos) and mudancas
    assert m.importar_edicoes_md() == []  # sem nova edição, nada muda


def test_migra_memoria_md_antiga(dados):
    ws = dados / "workspace"
    ws.mkdir()
    (ws / "MEMORIA.md").write_text("# Memória\n\n- prefere respostas curtas _(desde 03/10/2026)_\n- liga para clientes às sextas _(desde 04/10/2026)_\n",
                                   encoding="utf-8")
    m = MemoriaLonga()
    assert {f.texto for f in m.fatos()} == {"prefere respostas curtas", "liga para clientes às sextas"}
    assert all(f.origem == "importado" for f in m.fatos())
    assert len(MemoriaLonga().fatos()) == 2  # não migra de novo


# ---------------------------------------------------------------- consolidação e LGPD
def test_consolidar_junta_repetidos_e_arquiva_detalhes_velhos():
    m = MemoriaLonga()
    m.adicionar("Rickson gosta de café", "perfil", 1)
    velho = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(timespec="seconds")
    with m.con:
        m.con.execute("UPDATE fatos SET atualizado_em = ? WHERE id = 1", (velho,))
        m.con.execute("INSERT INTO fatos(texto, categoria, importancia, origem, criado_em, atualizado_em) VALUES "
                      "('Rickson prefere relatórios em PDF', 'preferencia', 3, 'extraido', ?, ?), "
                      "('rickson prefere relatorios em pdf', 'preferencia', 4, 'extraido', ?, ?)",
                      (velho, velho, velho, velho))
    r = m.consolidar()
    assert r == {"juntados": 1, "arquivados": 1}
    ativos = m.fatos()
    assert len(ativos) == 1 and ativos[0].importancia == 4


def test_lgpd_apaga_de_verdade_o_cliente():
    m = MemoriaLonga()
    m.adicionar("CLI-012 quer se aposentar aos 60", "cliente")
    m.adicionar("CLI-0123 é empresário", "cliente")
    m.guardar_episodio(7, "2026-10-05T13:00:00+00:00", "2026-10-05T13:10:00+00:00", "Reunião CLI-012", "Aposentadoria do CLI-012", [], 1, 2)
    m.registrar_evento("pos", "/pos CLI-012 → resumo registrado")
    from quiron.servicos import lgpd

    r = lgpd.esquecer_cliente("CLI-012")
    assert r.itens["memória persistente (fatos, conversas resumidas, eventos)"] >= 3  # + registros que citam o código
    m2 = MemoriaLonga()
    assert [f.texto for f in m2.fatos()] == ["CLI-0123 é empresário"]  # código inteiro: CLI-012 não apaga CLI-0123
    assert not m2.episodios() and not m2.eventos_recentes()
    assert m2.con.execute("SELECT COUNT(*) FROM fatos WHERE texto LIKE '%CLI-012 %'").fetchone()[0] == 0


# ---------------------------------------------------------------- integração: agente lembra entre conversas
def test_agente_lembra_entre_conversas(monkeypatch):
    sistemas = []

    def conversar(mensagens, ferramentas=None, **k):
        sistemas.append(mensagens[0]["content"])
        return cerebro.Turno("Combinado.", [], {"role": "assistant", "content": "Combinado."}, "simulado")

    def escriba(pedido, **k):
        return _resposta(json.dumps({"titulo": "Preferências de relatório", "resumo": "Ele pediu relatórios sempre em PDF.",
                                     "pendencias": [], "fatos": [{"op": "adicionar", "texto": "Rickson quer relatórios sempre em PDF",
                                                                  "categoria": "preferencia", "importancia": 4}]}))

    monkeypatch.setattr(cerebro, "conversar", conversar)
    monkeypatch.setattr(cerebro, "perguntar", escriba)
    ag = Agente(SemMCP(), Config(), em_segundo_plano=False)
    asyncio.run(ag.responder("Lembre que meu nome no escritório é Rick", chat=7))
    assert "Rick" in sistemas[-1] and any(f.texto.startswith("meu nome no escritório") for f in ag.longa.fatos())
    asyncio.run(ag.responder("a partir de agora quero relatórios sempre em PDF", chat=7))  # pista → extrai na hora
    assert any("PDF" in f.texto for f in ag.longa.fatos())
    asyncio.run(ag.responder("ok, obrigado", chat=7))

    # 2 horas depois a conversa vira episódio; em outra conversa (Terminal), ele lembra
    futuro = datetime.now(timezone.utc) + timedelta(hours=2)
    assert ag.fechar_se_ocioso(7, agora=futuro)
    assert ag.longa.episodios()[0].titulo == "Preferências de relatório"
    asyncio.run(ag.responder("monte o relatório do mês", chat=-12))
    assert "relatórios sempre em PDF" in sistemas[-1] and "Sua memória de longo prazo" in sistemas[-1]

    # /novo não perde nada: vira episódio
    asyncio.run(ag.responder("vamos falar de FII", chat=7))
    ag.novo_assunto(7)
    assert len(ag.longa.episodios()) == 2 and ag.memoria.historico(7) == []


def test_historico_tem_limite_duro_mesmo_sem_resumo(dados):
    from quiron.runtime import memoria as mod

    mem = Memoria()
    for i in range(100):
        mem.guardar(1, "user" if i % 2 == 0 else "assistant", f"msg {i}")
    assert len(mem.historico(1)) == mod.LIMITE_DURO


def test_bot_comandos_de_memoria_e_eventos(monkeypatch):
    from quiron.runtime.telegram_bot import BotQuiron

    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {111})
    t = lambda x: asyncio.run(bot.tratar(111, 111, x))[0].texto  # noqa: E731
    assert "Ainda não guardei nada" in t("/memoria")
    assert t("/lembrar prefiro reuniões às terças").startswith("Guardado")
    tela = t("/memoria")
    assert "#1 ★★★★ prefiro reuniões às terças" in tela and "/memoria esquecer" in tela
    assert t("/memoria mudar 1 prefiro reuniões às quartas").startswith("Atualizado")
    assert "quartas" in t("/memoria buscar reuniões")
    t("/tarefa amanhã às 10h ligar para o CLI-012")  # ação pelo comando direto → evento na memória
    assert any("/tarefa" in e for e in bot.agente.longa.eventos_recentes())
    t("/tarefas")  # listagem não vira evento
    assert sum("/tarefas" in e for e in bot.agente.longa.eventos_recentes()) == 0
    assert t("/memoria esquecer 2") == "Esquecido: 1 item(ns)."
    assert "Ainda não guardei" in t("/memoria")


def test_revetoriza_quando_o_modelo_muda():
    m = MemoriaLonga()
    m.adicionar("Rickson faz a prova do CFP em março", "estudo")
    with m.con:
        m.con.execute("UPDATE fatos SET modelo_vetor = 'modelo-antigo'")
    assert m.relevantes("prova do CFP")  # ainda acha por palavras
    assert m.revetorizar() == 1 and m.revetorizar() == 0


# ---------------------------------------------------------------- registro completo: tudo gravado
def test_agente_grava_pergunta_ferramentas_e_resposta(monkeypatch):
    passos = iter([
        cerebro.Turno("", [{"id": "c1", "nome": "lembrar", "argumentos": {"fato": "Rickson prefere FIIs de tijolo"}}],
                      {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
                       "function": {"name": "lembrar", "arguments": "{}"}}]}, "simulado"),
        cerebro.Turno("Guardado.", [], {"role": "assistant", "content": "Guardado."}, "simulado"),
    ])
    monkeypatch.setattr(cerebro, "conversar", lambda *a, **k: next(passos))
    ag = Agente(SemMCP(), Config(), em_segundo_plano=False)
    asyncio.run(ag.responder("guarde que prefiro FIIs de tijolo", chat=-12))
    tipos = [(r["canal"], r["tipo"]) for r in ag.longa.registros_do_dia()]
    assert ("terminal", "entrada") in tipos and ("terminal", "ferramenta") in tipos and ("terminal", "ferramenta_resultado") in tipos
    assert ("terminal", "resposta") in tipos and ("sistema", "memoria_fato") in tipos
    linha = ag.longa.linha_do_tempo()
    assert "🗣️ guarde que prefiro FIIs de tijolo" in linha and "🤖 Guardado." in linha and "🧠 guardado #1" in linha
    assert ag.longa.buscar_registros("tijolo") and all(r["tipo"] != "ferramenta_resultado" for r in ag.longa.buscar_registros("tijolo"))


def test_bot_grava_comandos_diretos_audio_arquivo_e_avisos(monkeypatch):
    from quiron.runtime import audio
    from quiron.runtime.telegram_bot import BotQuiron

    monkeypatch.setattr(audio, "transcrever", lambda conteudo, nome: "/tarefa sexta revisar carteira do CLI-020")
    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {111})
    asyncio.run(bot.tratar(111, 111, "/tarefa amanhã às 9h estudar duration"))
    asyncio.run(bot.tratar_audio(111, 111, b"OggS"))
    asyncio.run(bot.tratar_arquivo(111, 111, b"%PDF", "livro.pdf"))
    bot.registrar_proativo(111, "⏰ Lembrete: estudar duration", "agenda")
    asyncio.run(bot.tratar(999, 999, "/tarefa intruso"))  # estranho: nada gravado
    regs = bot.agente.longa.registros_do_dia()
    pares = [(r["tipo"], r["conteudo"][:22]) for r in regs]
    assert ("comando", "/tarefa amanhã às 9h e") in pares and any(t == "resposta_comando" for t, _ in pares)
    assert any(t == "audio" and c.startswith("/tarefa sexta") for t, c in pares)
    assert any(t == "arquivo" and c.startswith("livro.pdf") for t, c in pares)
    assert any(t == "proativo" for t, _ in pares) and not any("intruso" in r["conteudo"] for r in regs)


def test_conversas_antigas_entram_no_registro(dados):
    mem = Memoria()
    mem.guardar(7, "user", "qual a Selic?")
    mem.guardar(7, "assistant", "13,75% a.a.")
    m = MemoriaLonga()
    assert [r["tipo"] for r in m.registros_do_dia()] == ["entrada", "resposta"]
    assert len(MemoriaLonga().registros_do_dia()) == 2  # não migra de novo


def test_copia_restauracao_integridade_e_exportacao(dados):
    m = MemoriaLonga()
    m.adicionar("Rickson prefere relatórios em PDF", "preferencia", 4)
    pasta = m.fazer_copia()
    assert (pasta / "memoria.db").exists() and m.verificar_integridade() == "ok"
    assert m.resumo()["ultima_copia"]
    m.esquecer("#1")
    assert not m.fatos()
    dia = pasta.name
    assert "restaurada" in m.restaurar_copia(dia)
    assert [f.texto for f in MemoriaLonga().fatos()] == ["Rickson prefere relatórios em PDF"]
    with pytest.raises(FileNotFoundError):
        m.restaurar_copia("1999-01-01")
    arq = MemoriaLonga().exportar()
    conteudo = json.loads(arq.read_text(encoding="utf-8"))
    assert conteudo["fatos"] and conteudo["registro"] and "conversas_resumidas" in conteudo
    for i in range(35):  # guarda só as 30 mais recentes
        m.fazer_copia(quando=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i))
    assert len([p for p in m.pasta_copias().iterdir() if not p.name.startswith("antes-")]) == 30
    assert any(p.name.startswith("antes-de-restaurar-") for p in m.pasta_copias().iterdir())


def test_lgpd_apaga_tambem_do_registro():
    m = MemoriaLonga()
    m.registrar("telegram", 7, "entrada", "o CLI-012 quer previdência")
    m.registrar("telegram", 7, "entrada", "o CLI-0123 quer FII")
    assert m.apagar_por_cliente("CLI-012") >= 1
    textos = [r["conteudo"] for r in MemoriaLonga().registros_do_dia()]
    assert not any("CLI-012 " in t for t in textos) and any("CLI-0123" in t for t in textos)
    assert not MemoriaLonga().buscar_registros("previdência")


def test_bot_memoria_hoje_estado_exportar(monkeypatch):
    from quiron.runtime.telegram_bot import BotQuiron

    bot = BotQuiron(Agente(SemMCP(), Config(), em_segundo_plano=False), {111})
    asyncio.run(bot.tratar(111, 111, "/lembrar prefiro reuniões às terças"))
    hoje = asyncio.run(bot.tratar(111, 111, "/memoria hoje"))[0].texto
    assert hoje.startswith("📜 Registro de") and "/lembrar prefiro reuniões" in hoje
    assert "integridade: ok" in asyncio.run(bot.tratar(111, 111, "/memoria estado"))[0].texto
    assert "Cópia de segurança feita" in asyncio.run(bot.tratar(111, 111, "/memoria copia"))[0].texto
    exp = asyncio.run(bot.tratar(111, 111, "/memoria exportar"))[0]
    assert exp.arquivo and exp.arquivo.endswith(".json")
    assert "Data inválida" in asyncio.run(bot.tratar(111, 111, "/memoria 31/02"))[0].texto


def test_terminal_faz_a_copia_do_dia(dados):
    from quiron.terminal.backend import central

    from quiron.runtime.memoria_longa import _brt

    central.copia_diaria_da_memoria(vezes=1)
    hoje = datetime.now(_brt()).strftime("%Y-%m-%d")  # a pasta da cópia leva a data de Brasília (perto da meia-noite UTC difere)
    assert (dados / "backups" / "memoria" / hoje / "memoria.db").exists()
