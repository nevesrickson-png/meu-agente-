from datetime import date, datetime, timezone

import httpx
import pandas as pd
import pytest

from quiron.servicos.mercado import abertos, bcb, cotacoes, curva, http, painel, tesouro
from testes import gravacoes_mercado as g


@pytest.fixture(autouse=True)
def fontes_gravadas(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(g.roteador)))

    def yahoo_falso(simbolo):
        if simbolo in {"NADA", "NADA.SA"}:
            return pd.DataFrame()
        idx = pd.DatetimeIndex([datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 2, tzinfo=timezone.utc)])
        precos = {"^BVSP": (140000.0, 141400.0), "BRL=X": (5.34, 5.31), "^GSPC": (6600.0, 6633.0), "BZ=F": (70.0, 69.3)}
        return pd.DataFrame({"Close": precos.get(simbolo, (10.0, 10.5))}, index=idx)

    monkeypatch.setattr(cotacoes, "_historico_yahoo", yahoo_falso)
    yield
    http.definir_cliente(None)


def test_sgs_e_focus():
    s = bcb.sgs("selic_meta")
    assert s.ultimo.valor == 15.0 and s.ultimo.data == date(2026, 10, 2)
    assert s.fonte == "Banco Central (SGS 432)" and not s.desatualizado
    e = bcb.focus("ipca", 2026)
    assert (e.mediana, e.mediana_semana_anterior, e.data) == (4.85, 4.90, date(2026, 9, 26))


def test_tesouro_pega_so_a_data_base_mais_recente():
    tab = tesouro.titulos_atuais()
    assert tab.data_base == date(2026, 10, 1)
    assert [t.nome for t in tesouro.por_tipo(tab, "prefixado")] == ["Tesouro Prefixado 2029", "Tesouro Prefixado 2032"]
    assert tesouro.por_tipo(tab, "ipca_mais")[0].taxa_compra == 7.40


def test_curva_anbima_e_plano_b():
    c = curva.curva()
    assert c.fonte == "ANBIMA (ETTJ)" and len(c.vertices) == 6
    v = curva.no_prazo(c, 5)
    assert (v.dias_uteis, v.pre, v.real) == (1260, 13.75, 7.15)
    b = curva.curva_tesouro()
    assert "aproximada" in b.observacao
    v29 = next(v for v in b.vertices if v.pre == 13.62)
    assert v29.real is None and v29.implicita is None  # vencimentos diferentes: sem inflação implícita inventada


def test_cotacoes_b3_e_global():
    p = cotacoes.cotacao("PETR4")
    assert (p.preco, p.fonte, p.variacao_pct) == (38.45, "brapi (B3)", 1.25)
    assert "15 min" in p.atraso and p.horario.year == 2026
    ibov = cotacoes.cotacao("IBOV")
    assert ibov.preco == 141400.0 and ibov.variacao_pct == pytest.approx(1.0)
    # ticker que a brapi não tem cai no Yahoo (.SA)
    assert cotacoes.cotacao("WEGE3").fonte == "Yahoo Finance"


def test_cvm_companhia_e_fundo():
    achados, fonte = abertos.buscar_companhia("weg")
    assert achados[0]["codigo_cvm"] == "5410" and "CVM" in fonte
    assert abertos.buscar_companhia("84.429.695")[0][0]["nome"] == "WEG S.A."
    assert abertos.buscar_companhia("cancelada")[0] == []
    cotas, _ = abertos.informe_diario("12.345.678/0001-90", date(2026, 9, 1))
    assert [c.cota for c in cotas] == [2.5, 2.525] and cotas[-1].cotistas == 125


def test_calendario_ibge():
    itens = abertos.calendario_ibge(10)
    assert itens[0].titulo == "PNAD Contínua" and itens[1].titulo == "IPCA — IPCA - Setembro 2026"


def test_painel_com_fonte_e_horario():
    t = painel.taxas()
    assert "Selic meta**: 15,00%" in t and "📊 Banco Central (SGS 432)" in t
    assert "Tesouro IPCA+ 2029: IPCA + 7,40%" in t
    m = painel.macro()
    assert "IPCA acumulado em 12 meses**: 4,80%" in m and "Dólar PTAX (venda)**: R$ 5,3120" in m
    assert "IPCA: 4,85% (-0,05 na semana)" in m and "Selic: 15,00% (estável na semana)" in m
    c = painel.texto_curva()
    assert "| 5.0 anos (1260 du) | 13,75% | 7,15% |" in c
    w = painel.cotacao("PETR4")
    assert "R$ 38,45 (+1,25% no dia)" in w and "dado de 02/10" in w


def test_fonte_fora_do_ar_nao_derruba_o_painel():
    assert "indisponível" in painel.cotacao("NADA")
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    t = painel.taxas()
    assert t.count(": indisponível (") == 3


def test_cache_devolve_ultimo_valor_marcado_como_desatualizado():
    bcb.sgs("selic_meta")  # guarda no cache
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    r = http.obter(bcb.URL_SGS.format(codigo=432, n=2), params={"formato": "json"}, fonte="x", ttl=0)
    assert r.desatualizado and r.conteudo[-1]["valor"] == "15.00"


def test_agenda_junta_ibge_e_copom(monkeypatch):
    class Hoje(date):
        @classmethod
        def today(cls):
            return date(2026, 11, 1)

    monkeypatch.setattr(painel, "date", Hoje)
    a = painel.agenda(7)
    assert "Copom — decisão da Selic" in a and "04/11 18:30" in a


def test_briefing_tem_todas_as_secoes():
    b = painel.briefing()
    for trecho in ("## Juros", "Selic meta", "Focus — medianas", "Dólar", "Ibovespa", "S&P 500", "## Agenda"):
        assert trecho in b, trecho


def test_numero_br():
    assert http.numero_br("1.234,56") == 1234.56 and http.numero_br("15.00") == 15.0 and http.numero_br("") is None
