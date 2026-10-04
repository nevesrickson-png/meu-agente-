"""Academia (Fase 6): edital mapeado, gerador com conferência, banco com revisão espaçada, diagnóstico, plano e bot."""

import asyncio
import json
from datetime import date, timedelta

import pytest

from quiron.servicos.academia import consultas, diagnostico, edital, estudo, gerador
from quiron.servicos.academia.banco import Banco, proxima_revisao

PROGRAMA = """Índice
Módulo 1 - Planejamento Financeiro 5
Módulo 9 - Psicologia 45
1
Módulo 1 - Planejamento Financeiro:
Princípios
Peso: 13%
Texto de introdução.
1.1\t Planejamento Financeiro: a profissão
1.1.1 \tIntrodução ao planejamento
1.1.2 Funções do planejador financeiro ao realizar o
planejamento integrado
5
Módulo 2 - Gestão Financeira
Peso: 14%
2.1
Princípios de gestão financeira
2.1.1 Fundamentos:
•
Tratamento do risco
•
Gestão de risco
2.1.2 Balanço patrimonial
"""


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.setattr(gerador, "_trechos_biblioteca", lambda *a, **k: [])  # sem biblioteca nos testes
    monkeypatch.setattr(estudo, "gerar_lote", lambda *a, **k: [])  # nunca chama o modelo de verdade
    return Banco(tmp_path / "academia.db")


def _q(banco, modulo, topico="", correta=0, n=1):
    topico = topico or f"{modulo}.1.1"
    return [banco.adicionar_questao("CFP", modulo, topico, f"Enunciado {modulo}-{topico}-{i}-{correta}",
                                    ["a", "b", "c", "d"], correta, "porque sim") for i in range(n)]


def test_extrai_programa_com_formatos_variados():
    r = edital.extrair_programa(PROGRAMA)
    assert [m["numero"] for m in r["modulos"]] == ["1", "2"] or [m["numero"] for m in r["modulos"]] == [1, 2]
    m1, m2 = r["modulos"]
    assert m1["titulo"] == "Planejamento Financeiro: Princípios" and m1["peso"] == 13
    assert [t["codigo"] for t in m1["topicos"]] == ["1.1", "1.1.1", "1.1.2"]
    assert m1["topicos"][2]["titulo"].endswith("planejamento integrado")
    assert m2["topicos"][0] == {"codigo": "2.1", "titulo": "Princípios de gestão financeira"}  # código sozinho na linha
    assert m2["topicos"][1]["itens"] == ["Tratamento do risco", "Gestão de risco"]


def test_edital_cfp_oficial_mapeado():
    mods = edital.modulos("CFP")
    assert [m["peso"] for m in mods] == [13, 14, 17, 12, 12, 12, 12, 7]
    assert sum(m["questoes_estimadas"] for m in mods) == 140
    assert len(edital.topicos("CFP")) > 900
    assert edital.topico("6.2.1")["modulo"] == 6
    assert any(t["codigo"].startswith("3.") for t in edital.buscar("alocação de ativos"))


def test_calculo_seguro_e_numeros_brasileiros():
    assert gerador.calcular("100000*0.15") == 15000
    assert gerador.calcular("round(1000*(1+0.1)**2, 2)") == 1210.0
    with pytest.raises(ValueError):
        gerador.calcular("__import__('os').system('x')")
    assert gerador.numeros("R$ 1.234,56 e 12,5% e 17.5") == [1234.56, 12.5, 17.5]
    assert gerador.confere_conta("R$ 15.000,00", "100000*0.15")
    assert gerador.confere_conta("17,5%", "0.175")
    assert not gerador.confere_conta("R$ 12.000,00", "100000*0.15")


def _json_questoes(*itens):
    return json.dumps({"questoes": list(itens)})


def test_gerador_valida_conta_e_passa_pelo_revisor(banco):
    boa = {"enunciado": "Ganho de 100 mil com alíquota de 15%: imposto?", "alternativas": ["R$ 12.000,00", "R$ 15.000,00",
           "R$ 18.000,00", "R$ 20.000,00"], "correta": "B", "explicacao": "15% de 100 mil.", "verificacao": "100000*0.15",
           "subtopico": "6.2.1.4"}
    conta_errada = {**boa, "enunciado": "Outra", "correta": "A"}
    recusada_revisor = {**boa, "enunciado": "Terceira", "verificacao": ""}
    revisao = json.dumps({"revisoes": [{"n": 1, "resposta_propria": "B", "problemas": ""},
                                       {"n": 2, "resposta_propria": "B", "problemas": "a explicação contradiz o enunciado"}]})
    r = gerador.gerar_questoes("6.2.1", 3, banco=banco, mock_response=_json_questoes(boa, conta_errada, recusada_revisor),
                               mock_revisao=revisao)
    assert len(r["gravadas"]) == 1 and len(r["recusadas"]) == 2
    assert any("conta não confere" in m for m in r["recusadas"]) and any("contradiz" in m for m in r["recusadas"])
    q = banco.questao(r["gravadas"][0])
    assert q.topico == "6.2.1.4" and q.letra_correta == "B" and "Conta conferida" in q.explicacao and q.revisor


def test_revisao_espacada_e_ordem_das_questoes(banco):
    assert proxima_revisao(1, 3, 10, 2.5, date(2026, 10, 1))[3] == "2026-10-02"  # errou: volta amanhã
    rep, inter, fac, _ = proxima_revisao(4, 0, 0, 2.5)
    assert (rep, inter) == (1, 1.0)
    rep, inter, fac, _ = proxima_revisao(4, rep, inter, fac)
    assert inter == 3.0
    a, b = _q(banco, 3, n=2)
    assert banco.responder(a, 1) is False  # errou → revisão amanhã
    amanha = date.today() + timedelta(days=1)
    assert banco.escolher_questoes("CFP", 1, modulo=3, hoje=amanha)[0].id == a
    banco.anular(a)
    assert [q.id for q in banco.escolher_questoes("CFP", 5, modulo=3)] == [b]


def test_diagnostico_e_plano(banco):
    for _ in range(10):
        (qid,) = _q(banco, 3, "3.5.1", correta=0)
        banco.responder(qid, 1)  # erra tudo do módulo 3
        (qid,) = _q(banco, 8, "8.1.1", correta=0)
        banco.responder(qid, 0)  # acerta tudo do módulo 8
    mods = diagnostico.diagnosticar(banco)
    m3, m8 = mods[2], mods[7]
    assert m3.respostas == 10 and m3.situacao == "abaixo do mínimo" and m8.situacao == "acima da meta"
    assert m3.prioridade > m8.prioridade
    blocos = diagnostico.plano_semana(mods, horas=5)
    assert sum(b.minutos for b in blocos) == 300
    minutos = {k: sum(b.minutos for b in blocos if b.modulo == k) for k in range(1, 9)}
    assert minutos[3] == max(minutos.values()) and minutos[8] <= minutos[3]
    texto = diagnostico.texto_diagnostico(mods)
    assert "Domínio estimado" in texto and "3.5" in texto
    assert "Plano de estudo" in diagnostico.texto_plano(mods, blocos, 5)


def test_distribuicao_do_simulado():
    assert estudo.distribuicao(16) == {i: 2 for i in range(1, 9)}
    d = estudo.distribuicao(140)
    assert sum(d.values()) == 140 and d[3] == max(d.values()) and d[8] == min(d.values())
    assert sum(estudo.distribuicao(40).values()) == 40


def test_filtro_le_modulo_topico_e_tema():
    assert estudo.Filtro.ler("3").modulo == 3 and estudo.Filtro.ler("m 6").modulo == 6
    assert estudo.Filtro.ler("6.2.1").topico == "6.2.1"
    assert estudo.Filtro.ler("PGBL e VGBL").topico == "6.5.2"
    assert estudo.Filtro.do_codigo(estudo.Filtro.ler("6.2.1").codigo()).topico == "6.2.1"


def test_bot_questao_simulado_e_flashcards(banco):
    from quiron.runtime.academia_bot import AcademiaBot

    for mod in range(1, 9):
        _q(banco, mod, n=2, correta=0)
    bot = AcademiaBot(banco)
    telas = asyncio.run(bot.comando("questoes", "3"))
    botao = telas[0].linhas[0][0][1]  # resposta "A"
    assert botao.startswith("ac:r:") and "⚠" in telas[0].linhas[1][0][0]
    c = asyncio.run(bot.clique(botao))
    assert "✅ Certo" in c.editar and c.novas[0].linhas[0][0][1] == "ac:prox:CFP|m3"

    telas = asyncio.run(bot.comando("simulado", "mini"))
    assert "Simulado #" in telas[0].texto
    tela = telas[1]
    for i in range(16):
        dado = tela.linhas[0][1][1] if i % 2 else tela.linhas[0][0][1]  # alterna A (certa) e B (errada)
        c = asyncio.run(bot.clique(dado))
        assert "Você marcou" in c.editar
        tela = c.novas[0]
    textos = [t.texto for t in c.novas]
    assert "🏁 Simulado" in textos[0] and "Diagnóstico" in textos[1] and "Plano de estudo" in textos[2]

    cid = banco.adicionar_card("CFP", 6, "6.2.1", "Alíquota do IR em renda fixa acima de 720 dias?", "15%")
    telas = asyncio.run(bot.comando("flashcards", ""))
    assert "Mostrar resposta" in telas[0].linhas[0][0][0]
    c = asyncio.run(bot.clique(f"ac:fv:{cid}"))
    assert "15%" in c.novas[0].texto
    c = asyncio.run(bot.clique(f"ac:fn:{cid}:4"))
    assert "Próxima revisão" in c.editar
    assert "Academia" in asyncio.run(bot.comando("academia", ""))[0].texto


def test_consultas_configurar_e_edital(banco):
    assert "15/03/2027" in consultas.configurar("15/03/2027", 6, ["segunda", "quarta"], banco=banco)
    assert banco.pref("data_prova:CFP") == "2027-03-15" and banco.pref("horas_semana") == 6
    assert "faltam" in consultas.plano(banco=banco)
    assert "140 questões" in consultas.mapa_edital()
    assert "M3" in consultas.mapa_edital() and "3.5" in consultas.mapa_edital(modulo=3)
    assert "Data inválida" in consultas.configurar("31/02/2027", banco=banco)


def test_lote_noturno_respeita_janela_e_meta(banco, monkeypatch):
    chamadas = []
    monkeypatch.setattr(estudo, "gerar_lote", lambda b, m, n, t=None, area="CFP": chamadas.append(m) or [1])
    cfg = {"ligada": True, "inicio": "01:00", "fim": "06:00", "meta_por_modulo": 2}
    assert estudo.lote_noturno(banco, "12:00", cfg) == [] and not chamadas
    assert estudo.lote_noturno(banco, "02:00", cfg) == [1] and chamadas == [3]  # módulo de maior peso primeiro
    for mod in range(1, 9):
        _q(banco, mod, n=2)
    assert estudo.lote_noturno(banco, "02:00", cfg) == []  # todos na meta


def test_plano_no_domingo_ja_e_da_semana_seguinte_e_resumo_sem_cortar_palavra():
    assert diagnostico.inicio_semana(date(2026, 10, 4)) == date(2026, 10, 5)  # domingo → segunda seguinte
    assert diagnostico.inicio_semana(date(2026, 10, 7)) == date(2026, 10, 5)  # quarta → segunda da semana
    r = diagnostico.resumir("Primeira frase curta aqui. " + "palavra " * 60, 60)
    assert r == "Primeira frase curta aqui."
    assert diagnostico.resumir("x " * 100, 21).endswith("…")


def test_banco_inicial_importa_uma_vez(banco):
    from quiron.servicos.academia.cli import semear

    n = semear(banco)
    assert n >= 40 and all(v >= 2 for v in banco.contar_questoes().values())
    assert semear(banco) == 0


def test_areas_campos_e_certificacoes(banco):
    from quiron.servicos import areas

    todas = {a.id: a for a in areas.listar()}
    assert {"ECONOMIA", "RISCO", "COMERCIAL", "RENDA_FIXA", "CFP", "CNPI", "CFA_I", "CEA"} <= set(todas)
    assert sum(1 for a in todas.values() if a.tipo == "campo") == 20
    assert "ECONOMIA" in todas["CFP"].relacionadas  # caminho inverso campo → certificação
    a, resto = areas.reconhecer("renda fixa duration")
    assert a.id == "RENDA_FIXA" and resto == "duration"
    assert areas.reconhecer("cfa i ética")[0].id == "CFA_I"
    nova = areas.criar("Agronegócio", "crédito rural e CPR")
    assert nova.id == "AGRONEGOCIO" and nova.personalizada and nova.pasta == "agronegocio"
    with pytest.raises(ValueError):
        areas.criar("Agronegócio")
    # sem programa próprio: ganha um provisório e a Academia funciona igual
    assert edital.modulos("AGRONEGOCIO")[0]["topicos"][0]["codigo"] == "1.1"
    assert not edital.tem_programa("AGRONEGOCIO") and edital.tem_programa("ECONOMIA")


def test_programas_dos_campos_e_filtro_por_area():
    for ident in ("ECONOMIA", "RISCO", "COMERCIAL", "RENDA_FIXA", "SUCESSAO"):
        mods = edital.modulos(ident)
        assert len(mods) >= 3 and all(m["topicos"] for m in mods)
    f = estudo.Filtro.ler("economia 3")
    assert (f.area, f.modulo) == ("ECONOMIA", 3)
    f = estudo.Filtro.ler("renda fixa duration")
    assert f.area == "RENDA_FIXA" and edital.topico(f.topico, "RENDA_FIXA")["titulo"].startswith("Duration")
    assert estudo.Filtro.ler("2", "RISCO").area == "RISCO"
    assert estudo.Filtro.do_codigo(estudo.Filtro.ler("comercial 2.3").codigo()).topico == "2.3"
    assert sum(estudo.distribuicao(estudo.tamanho("mini", "COMERCIAL"), "COMERCIAL").values()) == 8
    assert "elaborador de questões de Comercial" in gerador.sistema("COMERCIAL")
    assert gerador.usa_regras("TRIBUTACAO", 1) and not gerador.usa_regras("COMERCIAL", 1)


def test_bot_em_outra_area(banco):
    from quiron.runtime.academia_bot import AcademiaBot

    for mod in range(1, 7):
        _q_area = [banco.adicionar_questao("ECONOMIA", mod, f"{mod}.1", f"Econ {mod}-{i}", ["a", "b", "c", "d"], 0, "x")
                   for i in range(2)]
    bot = AcademiaBot(banco)
    assert "Área ativa: Economia" in asyncio.run(bot.comando("area", "economia"))[0].texto
    assert bot.area == "ECONOMIA"
    telas = asyncio.run(bot.comando("questoes", ""))
    assert "📝 ECONOMIA" in telas[0].texto and "ECONOMIA|" in telas[0].linhas[0][0][1]
    telas = asyncio.run(bot.comando("simulado", ""))
    assert "Economia — 12 questões" in telas[0].texto
    assert "Diagnóstico · Economia" in asyncio.run(bot.comando("diagnostico", ""))[0].texto
    assert "Plano de estudo · Economia" in asyncio.run(bot.comando("plano", "4"))[0].texto
    assert "Campos (20)" in asyncio.run(bot.comando("academia", ""))[0].texto
    assert "Não achei a área" in asyncio.run(bot.comando("area", "astrologia"))[0].texto
