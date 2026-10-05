"""Qualidade da informação: histórias agrupadas, relevância, briefing montado em Python e comentário conferido."""

from datetime import date, datetime, timedelta, timezone

import pytest

from quiron.nucleo import cerebro
from quiron.runtime.roteamento import rotear
from quiron.servicos.mercado import abertos, bcb, briefing, cotacoes, tesouro
from quiron.servicos.noticias import relevancia
from quiron.servicos.noticias.coleta import Noticia, _classificar

AGORA = datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    relevancia.limpar_cache()


def _n(titulo, fonte="InfoMoney", grupo="brasil", horas=1.0, resumo=""):
    n = Noticia("", titulo, f"https://ex.com/{abs(hash(titulo + fonte))}", fonte, grupo, AGORA - timedelta(hours=horas), resumo)
    return _classificar(n)


def test_mesma_historia_de_varios_veiculos_vira_uma_so():
    lista = [
        _n("Ibovespa dispara e bate recorde, enquanto dólar cai mais de 4% após 1º turno da eleição", "Valor Econômico"),
        _n("Bolsa dispara e bate recorde com euforia após eleições; dólar despenca a R$ 5", "Folha Mercado"),
        _n("Ibovespa bate recorde e dólar despenca após primeiro turno", "g1 Economia"),
        _n("Startup alemã de robótica atinge avaliação de US$ 1 bilhão", "InfoMoney"),
        _n("Brasileirão: Flamengo vence clássico e assume a liderança", "g1 Economia"),
    ]
    hs = relevancia.agrupar(lista, AGORA)
    assert hs[0].cobertura == 3 and hs[0].fonte == "Valor Econômico"  # o veículo de referência é o principal
    assert not any("Flamengo" in h.titulo for h in hs)  # ruído (esporte) fora
    assert not any("robótica" in h.titulo for h in hs)  # sem tema de mercado no título: fora


def test_relevancia_pondera_tema_fonte_cobertura_e_hora():
    copom = _n("Copom mantém a Selic em 13,75% e sinaliza cortes", "Banco Central — Copom", "oficiais", horas=2)
    cripto = _n("Bitcoin sobe 3% no dia", "Money Times", horas=2)
    antiga = _n("Copom mantém a Selic em 13,75% e sinaliza cortes", "InfoMoney", horas=40)
    assert relevancia.nota(copom, AGORA) > relevancia.nota(cripto, AGORA)
    assert relevancia.nota(copom, AGORA) > relevancia.nota(antiga, AGORA)
    assert relevancia.nota(copom, AGORA, cobertura=4) > relevancia.nota(copom, AGORA, cobertura=1)
    so_resumo = _n("Candidatos a governador: veja a lista", resumo="Eleições")
    assert relevancia.nota(so_resumo, AGORA) == 0


def test_diversificar_nao_deixa_um_assunto_tomar_tudo():
    lista = [_n(f"Eleição: mercado reage ao resultado {i} com bolsa em alta", horas=i * 0.1) for i in range(5)]
    lista = [_n(f"{t} {i}", fonte=f"Fonte{i}", horas=0.5) for i, t in enumerate([
        "Eleição mexe com a bolsa e o Ibovespa sobe", "Eleição: Ibovespa dispara com resultado", "Eleição e bolsa: euforia no pregão",
        "Copom: ata indica pausa nos cortes da Selic", "IPCA de setembro desacelera para 0,3%"])]
    hs = relevancia.agrupar(lista, AGORA)
    escolhidas = relevancia.diversificar(hs, 3, max_por_tema=2)
    temas = [relevancia.tema_principal(h) for h in escolhidas]
    assert len(escolhidas) == 3 and max(temas.count(t) for t in temas) <= 2


def test_link_do_redirecionador_vira_endereco_real(monkeypatch):
    from quiron.servicos.noticias import coleta

    rss = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>F</title><item><title>Juros caem</title>'
           b'<link>https://redir.folha.com.br/redir/online/mercado/rss091/*https://www1.folha.uol.com.br/mercado/a.shtml</link>'
           b'<pubDate>Mon, 05 Oct 2026 12:00:00 -0300</pubDate></item></channel></rss>')
    monkeypatch.setattr(coleta, "obter", lambda *a, **k: type("R", (), {"conteudo": rss})())
    itens = coleta._itens_rss({"nome": "Folha", "url": "x"})
    assert itens[0].link == "https://www1.folha.uol.com.br/mercado/a.shtml"


# ---------------------------------------------------------------- briefing


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _fontes_falsas(monkeypatch):
    agora = datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)

    def sgs(chave, n=2):
        valores = {"selic_meta": 13.75, "cdi": 13.65, "ipca_12m": 4.22}
        return _Obj(ultimo=_Obj(valor=valores[chave], data=date(2026, 8, 1)), obtido_em=agora, desatualizado=False)

    def focus(ind, ano):
        m = {("ipca", 2026): (5.01, 4.99), ("ipca", 2027): (4.30, 4.31), ("selic", 2027): (12.0, 12.0)}[(ind, ano)]
        return _Obj(mediana=m[0], mediana_semana_anterior=m[1], data=date(2026, 10, 2))

    base = date(2026, 10, 2)
    titulos = [tesouro.Titulo("Tesouro Prefixado", date(2029, 1, 1), base, 13.83, 13.9, None, None),
               tesouro.Titulo("Tesouro Prefixado", date(2032, 1, 1), base, 14.15, 14.2, None, None),
               tesouro.Titulo("Tesouro IPCA+", date(2029, 5, 15), base, 7.39, 7.4, None, None),
               tesouro.Titulo("Tesouro IPCA+", date(2035, 5, 15), base, 7.55, 7.6, None, None),
               tesouro.Titulo("Tesouro IPCA+", date(2045, 5, 15), base, 7.03, 7.1, None, None)]
    tab = tesouro.Tabela(titulos, base, "Tesouro Transparente", agora, False)
    hist = {"prefixado": [(date(2026, 10, 1), date(2029, 1, 1), 13.86), (date(2026, 10, 1), date(2032, 1, 1), 14.12)],
            "ipca_mais": [(date(2026, 10, 1), date(2035, 5, 15), 7.66)]}

    def cot(ativo):
        dados = {"USDBRL": 4.98, "IBOV": 206912.0, "^GSPC": 7773.9, "petroleo_brent": 100.42}
        var = {"USDBRL": -4.58, "IBOV": 7.70, "^GSPC": 0.66, "petroleo_brent": -1.79}
        return cotacoes.Cotacao(ativo, ativo, dados[ativo], var[ativo], "BRL", datetime(2026, 10, 5), "Yahoo Finance", agora, "pode ter atraso")

    monkeypatch.setattr(bcb, "sgs", sgs)
    monkeypatch.setattr(bcb, "focus", focus)
    monkeypatch.setattr(tesouro, "titulos_atuais", lambda: tab)
    monkeypatch.setattr(tesouro, "historico_taxas", lambda chave: (hist.get(chave, []), "Tesouro"))
    monkeypatch.setattr(cotacoes, "cotacao", cot)
    monkeypatch.setattr(abertos, "calendario_ibge", lambda dias: [
        abertos.Divulgacao(datetime(2026, 10, 9, 9, 0), "Índice Nacional de Preços ao Consumidor Amplo (ref. 09/2026)", "IBGE"),
        abertos.Divulgacao(datetime(2026, 10, 8, 9, 0), "Pesquisa Industrial Mensal: Produção Física - Regional (ref. 08/2026)", "IBGE")])
    from quiron.servicos.noticias import consultas

    hist_noticias = relevancia.agrupar([
        _n("Ibovespa dispara e bate recorde após 1º turno da eleição", "Valor Econômico"),
        _n("Ibovespa bate recorde e dólar despenca após primeiro turno", "g1 Economia")], AGORA)
    monkeypatch.setattr(consultas, "historias", lambda horas=12, termo=None: hist_noticias)


def test_briefing_formatado_com_variacoes_agenda_e_noticias(monkeypatch):
    _fontes_falsas(monkeypatch)
    b = briefing.montar(datetime(2026, 10, 5, 7, 30, tzinfo=briefing.BRT))
    t = b.texto
    assert t.startswith("☀️ **Briefing — segunda, 05/10** · 07:30")
    assert "**O que está mexendo com o mercado**" in t and "Valor Econômico (+1)" in t
    assert "Selic 13,75% · CDI 13,65%" in t
    assert "Pré 2029 13,83% (▼3 bps)" in t and "Pré 2032 14,15% (▲3 bps)" in t and "IPCA+ 2035 7,55% (▼11 bps)" in t
    assert "IPCA 12m 4,22% (ago/26)" in t and "IPCA 2026 5,01% (▲0,02 p.p. na semana)" in t
    assert "**Mercados** (fech. 05/10)" in t and "Dólar R$ 4,98 ▼4,58%" in t and "Ibovespa 206.912 pts ▲7,70%" in t
    assert "sex 09/10 IPCA (set)" in t and "Regional" not in t  # só divulgação que mexe com mercado
    assert "```" not in t and "_Fontes:" in t


def test_briefing_sem_fontes_avisa_e_nao_inventa(monkeypatch):
    _fontes_falsas(monkeypatch)

    def fora(*a, **k):
        raise bcb.FonteIndisponivel("fora do ar")

    monkeypatch.setattr(bcb, "sgs", fora)
    t = briefing.montar(datetime(2026, 10, 5, 7, 30, tzinfo=briefing.BRT)).texto
    assert "Selic" not in t.split("**Juros**")[1].split("\n")[1]  # sem número inventado
    assert "⚠️" in t and "indisponível" in t


def test_comentario_com_numero_inventado_e_descartado(monkeypatch):
    _fontes_falsas(monkeypatch)
    resposta = ("• Aposentados: bom momento para conversar sobre travar juro real na renda fixa longa.\n"
                "• Dólar deve ir a R$ 4,20 até o fim do ano, então proteja o caixa.\n"
                "• Empresários: volatilidade alta pede revisar o caixa em dólar.")
    monkeypatch.setattr(cerebro, "perguntar", lambda *a, **k: cerebro.Resposta(resposta, "simulado", []))
    texto = briefing.completo(datetime(2026, 10, 5, 7, 30, tzinfo=briefing.BRT))
    assert "**Para os clientes**" in texto and "travar juro real" in texto
    assert "4,20" not in texto  # número que não está no briefing: linha fora
    assert texto.index("**Para os clientes**") < texto.index("_Fontes:")


def test_briefing_sem_ia_sai_igual(monkeypatch):
    _fontes_falsas(monkeypatch)

    def sem_cota(*a, **k):
        raise cerebro.CerebroIndisponivel("cota")

    monkeypatch.setattr(cerebro, "perguntar", sem_cota)
    texto = briefing.completo(datetime(2026, 10, 5, 7, 30, tzinfo=briefing.BRT))
    assert "**Juros**" in texto and "Para os clientes" not in texto


@pytest.mark.parametrize("frase", ["Faça meu briefing.", "briefing", "me manda o briefing de hoje"])
def test_frases_de_briefing_vao_direto(frase):
    assert rotear(frase) == ("briefing", "")
