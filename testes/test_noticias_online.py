"""Fontes REAIS de notícias. `uv run pytest -m online`."""

import pytest

from quiron.servicos.mercado import http
from quiron.servicos.noticias import coleta

pytestmark = pytest.mark.online


@pytest.fixture(autouse=True)
def isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    http.definir_cliente(None)


@pytest.mark.parametrize("fonte", coleta.ler_fontes(), ids=lambda f: f["nome"])
def test_feed_ativo(fonte):
    r = coleta.coletar([fonte])[0]
    assert r.ok and r.itens > 0, r.detalhe
