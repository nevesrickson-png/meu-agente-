"""Aceite da Fase 17 com dados e IA reais (internet + chaves): `uv run pytest -m online`.

Pautas a partir de notícias/Banco Central/radar/agenda com fontes; um carrossel sobre Tesouro Selic x poupança sai como
RASCUNHO, sem alerta grave de compliance, com todos os números conferidos com as fontes, disclaimer e créditos."""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.online


def test_aceite_pautas_e_roteiro_com_disclaimer_e_creditos(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    from quiron.servicos.conteudo import gerador, insumos

    itens = insumos.coletar("Tesouro Selic ou poupança com a Selic alta")
    assert any(i.tipo == "numero" for i in itens) and any(i.tipo == "regra" for i in itens)
    pautas, origem = gerador.gerar_pautas(itens=itens, n=4)
    assert origem == "ia" and len(pautas) >= 3 and all(p.fontes for p in pautas[:3])
    peca = gerador.gerar_peca("Tesouro Selic ou poupança: qual rende mais com a Selic alta?", "carrossel", itens=itens)
    rev = peca.revisado
    destino = Path(os.environ.get("QUIRON_CAPTURAS", tmp_path))
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "conteudo-aceite.md").write_text(gerador.texto_pautas(pautas, origem) + "\n\n=====\n\n" + peca.entrega(), encoding="utf-8")
    assert not rev.graves, rev.alertas
    assert rev.numeros_sem_fonte == [], rev.numeros_sem_fonte
    assert rev.creditos and "não é recomendação" in rev.disclaimer
    assert peca.entrega().startswith("RASCUNHO") and "Fontes:" in peca.entrega()
