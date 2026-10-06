"""Regressões da 2ª rodada de revisão (06/10/2026) — tudo sem internet."""

from datetime import date, datetime
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.setenv("QUIRON_EMBEDDINGS", "lexico")
    return tmp_path


# ---------------------------------------------------------------- memória
def test_restaurar_copia_nao_apaga_os_fatos(dados):
    from quiron.runtime.memoria_longa import MemoriaLonga

    m = MemoriaLonga()
    m.adicionar("Prefiro relatórios curtos", "preferencia", 4, "dito")
    m.adicionar("Estudo CFP às terças", "estudo", 3, "dito")
    m.fazer_copia(quando=datetime(2026, 10, 5, 3))
    m.esquecer("#2")
    m.atualizar(1, "Prefiro relatórios com no máximo uma página")
    m.restaurar_copia("2026-10-05")
    m.contexto("relatórios")  # lê o MEMORIA.md: não pode tratá-lo como edição e desativar o que voltou
    assert sorted(f.texto for f in m.fatos()) == ["Estudo CFP às terças", "Prefiro relatórios curtos"]


def test_consolidar_mantem_a_protecao_do_que_foi_dito(dados):
    from quiron.runtime.memoria_longa import MemoriaLonga

    m = MemoriaLonga()
    m.adicionar("Gosto de café sem açúcar", "preferencia", 3, "dito")
    with m.con:  # cópia quase igual vinda da extração, mais importante (fica ela)
        m.con.execute("INSERT INTO fatos(texto, categoria, importancia, origem, criado_em, atualizado_em) "
                      "VALUES ('Gosto de café sem açúcar.', 'preferencia', 4, 'extraido', '2026-10-06', '2026-10-06')")
    m.consolidar()
    (f,) = m.fatos()
    assert f.origem == "dito"
    m.aplicar([{"op": "apagar", "id": f.id}])
    assert m.fatos()


# ---------------------------------------------------------------- datas, tarefas e agenda
def test_horario_com_periodo_e_artigo_as():
    from quiron.servicos.assessoria.datas import extrair, relativo
    from quiron.runtime.agendador import BRT

    h = date(2026, 10, 6)
    assert extrair("amanhã às 3h da tarde ligar CLI-012", h) == ("Ligar CLI-012", date(2026, 10, 7), (15, 0))
    assert extrair("8h da noite jantar", h)[2] == (20, 0)
    assert extrair("comprar as 3 apostilas do CFP", h) == ("Comprar as 3 apostilas do CFP", None, None)
    assert extrair("revisar os 2 fundos e as 4 ações", h)[2] is None
    assert extrair("reunião as 3 da tarde com CLI-1", h)[2] == (15, 0) and extrair("às 10 ligar", h)[2] == (10, 0)
    assert relativo("reunião em 15h com CLI-012", datetime(2026, 10, 6, 9, tzinfo=BRT))[1] is None
    assert relativo("ligar em 2h", datetime(2026, 10, 6, 9, tzinfo=BRT))[1] == datetime(2026, 10, 6, 11, tzinfo=BRT)


def test_evento_de_x_as_y_e_inicio_e_fim(monkeypatch):
    from quiron.runtime.agendador import BRT
    from quiron.servicos.organizacao import google_agenda as g

    criados = []
    monkeypatch.setattr(g, "criar_evento", lambda t, i, f, cliente_http=None: criados.append((t, i, f)))
    g.evento_de_texto("amanhã reunião de 10h às 11h com CLI-012", datetime(2026, 10, 6, 9, tzinfo=BRT))
    titulo, ini, fim = criados[-1]
    assert (titulo, ini.hour, fim.hour, ini.day) == ("Reunião com CLI-012", 10, 11, 7)


def test_adiar_tarefa_atrasada_so_com_horario_vai_para_frente():
    from quiron.runtime.agendador import BRT
    from quiron.servicos.organizacao import tarefas

    t = tarefas.criar("ligar para o CLI-012 em 06/10 às 10h", agora=datetime(2026, 10, 5, 9, tzinfo=BRT))
    t = tarefas.adiar(t.id, "11h", agora=datetime(2026, 10, 8, 9, tzinfo=BRT))
    assert (t.prazo, t.hora) == ("2026-10-08", "11:00") and t.lembrete
    t = tarefas.adiar(t.id, "8h", agora=datetime(2026, 10, 8, 9, tzinfo=BRT))
    assert t.prazo == "2026-10-09"


# ---------------------------------------------------------------- compliance e conteúdo
@pytest.mark.parametrize("frase", ["Não há risco nenhum nesse CDB.", "Esse fundo não tem risco.", "Sem riscos.",
                                   "Risco praticamente zero.", "Investimento 100% seguro",
                                   "Rentabilidade assegurada de 1% ao mês.", "Retorno certo de 12% ao ano."])
def test_compliance_pega_negacao_de_risco_e_promessa(frase):
    from quiron.servicos.assessoria.compliance import conferir

    assert any(a.gravidade == "grave" for a in conferir(frase))


def test_ressalva_de_rentabilidade_precisa_estar_perto():
    from quiron.servicos.assessoria.compliance import conferir

    longe = "Rendeu 30% no ano. O FGC cobre bem. Outra coisa. O FGC não garante tudo."
    assert "Rentabilidade passada sem ressalva" in [a.regra for a in conferir(longe)]
    assert not conferir("Rendeu 30% no ano; rentabilidade passada não é garantia de rentabilidade futura.")
    assert not conferir("O CDB não é sem risco.") and not conferir("Não há risco de crédito relevante, mas há de mercado.")


def test_numeros_do_conteudo_nao_validam_por_data_ou_sinal():
    from quiron.servicos.conteudo.insumos import Insumo
    from quiron.servicos.conteudo.revisao import conferir_numeros

    ins = [Insumo(1, "sgs", "Selic meta: 15,00% a.a. (ref. 06/10/2026)", "BC"),
           Insumo(2, "sgs", "Dólar PTAX: R$ 5,2210 (ref. 05/10/2026)", "BC")]
    texto = "Selic em 15% (15,00%), dólar a R$ 5,221. Inventados: 10%, 6%, 2026%, -15%, 10.5%."
    assert conferir_numeros(texto, ins) == ["10%", "6%", "2026%", "-15%", "10.5%"]


def test_disclaimer_de_acoes_com_bdr_minusculas_e_caixa_alta():
    from quiron.servicos.conteudo import revisao

    for texto in ("AAPL34 subiu", "comprei petr4", "PETROBRAS anuncia", "Vale lucra mais"):
        assert revisao.RE_TICKER.search(texto) or revisao._cita_empresa(texto), texto
    assert not revisao._cita_empresa("vale a pena investir no Tesouro")


# ---------------------------------------------------------------- números financeiros
def test_reducao_do_ir_2026_sobre_o_bruto():
    from quiron.servicos.planejamento import impostos

    def ir(bruto):
        return round(impostos.ir_na_fonte(bruto, impostos.inss_empregado(bruto)), 2)

    assert ir(5000) == 0.0
    assert ir(7000) == 752.53  # antes: 647,39 (redução calculada sobre a base já deduzida)
    assert 190 < ir(5500) < 200  # desconto simplificado (R$ 607,20) > INSS


def test_calculadora_entende_ponto_de_milhar():
    from quiron.servicos import calculadoras as c

    assert c._num("300.000") == 300000 and c._num("1.000.000") == 1e6 and c._num("10.5") == 10.5
    assert c._fluxos("-1.000; 300; 400; 500")[0] == -1000
    r = c.executar("financiamento", {"valor": "300.000", "taxa_am": "1", "meses": "360"})
    assert "R$ 3.08" in " ".join(str(v) for _, v in r.linhas)  # ≈ R$ 3.086, não R$ 3,09


def test_rebalanceamento_units_e_cripto_isentos():
    from quiron.servicos.carteira.modelo import Carteira, Posicao
    from quiron.servicos.carteira.rebalanceamento import planejar

    c = Carteira("t", [Posicao("TAEE11", "acoes", 30000, "TAEE11", custo=20000),
                       Posicao("BTC", "cripto", 30000, "BTC", custo=15000), Posicao("CDB", "pos_fixado", 40000)])
    p = planejar(c, {"acoes": 0.15, "cripto": 0.15, "pos_fixado": 0.70})
    assert p.ir_total == 0.0 and {o.alvo for o in p.ordens if o.acao == "vender"} == {"TAEE11", "BTC"}


# ---------------------------------------------------------------- alertas, acervo, pacote offline
def test_alerta_criado_durante_a_avaliacao_nao_some():
    from quiron.servicos import alertas

    alertas.criar("preco_acima", "PETR4", 10)

    def cotacao_lenta(ativo):
        alertas.criar("noticia", "Copom")  # outro processo cria um alerta enquanto a avaliação consulta a rede
        return type("C", (), {"preco": 50.0, "variacao_pct": 1.0})()

    disparados = alertas.avaliar(cotacao=cotacao_lenta, buscar_noticias=lambda t: [])
    assert [a.alvo for a in disparados] == ["PETR4"]
    assert sorted(a.alvo for a in alertas.listar()) == ["Copom", "PETR4"]


def test_alertas_json_estragado_nao_derruba(dados):
    from quiron.servicos import alertas

    (dados / "alertas.json").write_text("[{\"id\": 1, \"tipo\"", encoding="utf-8")
    assert alertas.listar() == [] and alertas.criar("noticia", "Selic").id == 1


def test_dois_envios_com_o_mesmo_nome_nao_se_misturam(dados, monkeypatch):
    from quiron.servicos import acervo as mod

    monkeypatch.setenv("QUIRON_BIBLIOTECA", str(dados / "bib"))
    a = mod.Acervo(dados / "acervo.db")
    monkeypatch.setattr(a, "acordar", lambda: None)

    async def partes(conteudo):
        yield conteudo

    import asyncio

    async def dois():
        return await asyncio.gather(a.salvar_em_partes("cfp", "livro.pdf", partes(b"%PDF-A" * 10)),
                                    a.salvar_em_partes("cfp", "livro.pdf", partes(b"%PDF-B" * 10)))

    ids = asyncio.run(dois())
    caminhos = sorted(Path(a.obter(i).caminho).name for i in ids)
    assert caminhos == ["livro (2).pdf", "livro.pdf"]
    assert {Path(a.obter(i).caminho).read_bytes()[:6] for i in ids} == {b"%PDF-A", b"%PDF-B"}


def test_pacote_offline_recusa_caminhos_para_fora(dados):
    from quiron.servicos.offline.pacote import _seguro

    for ruim in ("dados//tmp/x", "dados/C:/Users/x/Startup/a.bat", "dados/../x", "/etc/passwd", "dados\\..\\x", "outra/x"):
        assert not _seguro(ruim), ruim
    assert _seguro("dados/fichas/CLI-001.json") and _seguro("biblioteca/indice")


# ---------------------------------------------------------------- Terminal, simulador, rotas, LGPD, .env
def test_websocket_so_aceita_a_propria_origem():
    from quiron.terminal.backend.app import _origem_permitida as ok

    assert not ok("https://atacante.tail1234.ts.net", "127.0.0.1:8765")
    assert not ok("http://localhost:3000", "127.0.0.1:8765")
    assert ok("http://localhost:8765", "127.0.0.1:8765") and ok("https://pc.tail.ts.net", "pc.tail.ts.net")
    assert ok("http://[::1]:8765", "[::1]:8765")


def test_simulador_nao_inventa_patrimonio():
    from quiron.servicos.planejamento.simulador import ler_frase

    assert "patrimonio" not in ler_frase("tenho 35 anos, ganho 20 mil e guardo 4 mil")
    assert "patrimonio" not in ler_frase("quero me aposentar com 10 mil por mês")
    assert "patrimonio" not in ler_frase("quero 1 milhão em 20 anos")
    assert ler_frase("aporte 2 mil, 300 mil investidos")["patrimonio"] == 300000
    assert ler_frase("/simular 500 mil, aporte 5 mil")["patrimonio"] == 500000


def test_lembra_que_amanha_e_lembrete():
    from quiron.runtime.roteamento import rotear

    assert rotear("lembra que amanhã tenho dentista")[0] == "tarefa"
    assert rotear("lembre que hoje eu prefiro respostas curtas")[0] == "lembrar"


def test_cotacao_diaria_mostra_a_data_certa():
    from datetime import timezone

    from quiron.servicos.mercado import cotacoes, painel

    c = cotacoes.Cotacao("USDBRL", "Dólar", 5.0, 0.1, "BRL", datetime(2026, 10, 6, tzinfo=timezone.utc), "Yahoo", datetime.now())
    assert "dado de 06/10" in painel.texto_cotacao(c) and "05/10" not in painel.texto_cotacao(c)


def test_cota_diaria_do_gemini_pausa_ate_o_dia_seguinte():
    import time

    from quiron.nucleo import cerebro

    cerebro._pausar_se_cota("gemini/teste", Exception('429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier '
                                                       'retryDelay: "17s"'))
    assert cerebro._PAUSA["gemini/teste"] - time.time() > 600


def test_esquecer_limpa_copias_da_memoria_e_vale_apos_restaurar(dados):
    from quiron.runtime.memoria_longa import MemoriaLonga
    from quiron.servicos import lgpd

    m = MemoriaLonga()
    m.adicionar("CLI-012 quer previdência para a filha", "clientes", 4, "dito")
    m.fazer_copia(quando=datetime(2026, 10, 5, 3))
    lgpd.esquecer_cliente("CLI-012")
    m.restaurar_copia("2026-10-05")
    assert not [f for f in m.fatos() if "CLI-012" in f.texto]
    copia = MemoriaLonga(m.pasta_copias() / "2026-10-05" / "memoria.db", arquivo_md=dados / "x.md")
    assert not [f for f in copia.fatos() if "CLI-012" in f.texto]


def test_env_com_bom_e_senha_com_cerquilha(tmp_path):
    from quiron.configurador.app import atualizar_env, ler_valores

    env = tmp_path / ".env"
    env.write_bytes("\ufeffTERMINAL_SENHA=velha\n".encode())
    atualizar_env({"TERMINAL_SENHA": "ab #1 ${HOME}"}, env)
    assert env.read_text(encoding="utf-8").count("TERMINAL_SENHA") == 1
    assert ler_valores(env)["TERMINAL_SENHA"] == "ab #1 ${HOME}"


def test_tese_em_29_de_fevereiro():
    from quiron.servicos.carreira.diario import _horizonte

    assert _horizonte("em 1 ano", date(2028, 2, 29)) == date(2029, 2, 28)
