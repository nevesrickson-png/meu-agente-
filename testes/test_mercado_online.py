"""Testes contra as fontes REAIS. Rode com `uv run pytest -m online` (precisa de internet).

Servem para confirmar que os formatos das fontes não mudaram. Se algum falhar, a fonte mudou o formato
ou está fora do ar: avise o Claude Code com a mensagem do erro.
"""

from datetime import date

import pytest

from quiron.servicos.mercado import abertos, bcb, cotacoes, curva, http, tesouro

pytestmark = pytest.mark.online


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    http.definir_cliente(None)


@pytest.mark.parametrize("chave", list(bcb.SERIES))
def test_series_sgs(chave):
    s = bcb.sgs(chave)
    assert s.ultimo.valor is not None and (date.today() - s.ultimo.data).days < 400


@pytest.mark.parametrize("ind", list(bcb.INDICADORES_FOCUS))
def test_focus(ind):
    e = bcb.focus(ind)
    assert e.mediana > 0 and (date.today() - e.data).days < 15


def test_tesouro():
    tab = tesouro.titulos_atuais()
    assert (date.today() - tab.data_base).days < 10 and tesouro.por_tipo(tab, "ipca_mais")


def test_ettj_anbima():
    c = curva.ettj_anbima()
    assert len(c.vertices) > 5 and curva.no_prazo(c, 2).pre > 0


def test_brapi_e_yahoo():
    assert cotacoes.brapi("PETR4").preco > 0
    for a in ("IBOV", "USDBRL", "^GSPC", "petroleo_brent", "ouro"):
        assert cotacoes.yahoo(a).preco > 0, a


def test_cvm_e_ibge():
    assert abertos.buscar_companhia("WEG")[0]
    assert isinstance(abertos.calendario_ibge(15), list)


def test_damodaran():
    assert "Brazil" in abertos.buscar_damodaran("premio_pais", "Brazil")
