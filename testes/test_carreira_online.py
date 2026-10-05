"""Aceite da Fase 15 com fontes reais (internet + chaves): `uv run pytest -m online`.

1) O radar aponta norma recente de fonte oficial (CVM, Receita, Banco Central ou Câmara).
2) O diário gera a revisão de teses: uma tese registrada "há 6 meses" (preço histórico real do Yahoo) é revisada com os
   preços de hoje — retorno, Ibovespa, excesso e premissas."""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quiron.runtime.agendador import BRT

pytestmark = pytest.mark.online


@pytest.fixture
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


def _salvar(nome, texto, dados):
    destino = Path(os.environ.get("QUIRON_CAPTURAS", dados))
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nome).write_text(texto, encoding="utf-8")


def test_aceite_radar_aponta_norma_recente(dados):
    from quiron.servicos.carreira import radar

    r = radar.atualizar()
    assert r["novos"] > 0, r
    recentes = radar.listar(dias=45, minimo=2)
    assert recentes, "nenhum item relevante nos últimos 45 dias"
    assert any(re.search(r"(Resolução|Instrução Normativa|Circular|PLP?|resolução|norma)", i.titulo) for i in recentes)
    assert all(i.link.startswith("https://") for i in recentes)
    texto = radar.relatorio(45, atualizar_antes=False)
    _salvar("radar-aceite.md", texto, dados)
    assert "🔴" in texto or "🟡" in texto


def test_aceite_diario_gera_revisao_de_teses(dados):
    from quiron.servicos.carreira import diario
    from quiron.servicos.carreira.banco import conectar
    from quiron.servicos.mercado import cotacoes

    seis_meses = datetime.now(BRT) - timedelta(days=183)
    t = diario.registrar("WEGE3 vai superar o Ibovespa em 6 meses: demanda de transmissão de energia forte e margem EBITDA "
                         "acima de 22%. Confiança 65%. Se a margem cair abaixo de 20%, a tese morre.")
    assert t.ativo == "WEGE3" and t.benchmark == "IBOV" and t.preco_inicial and t.confianca == 65
    # simula que a tese foi registrada há 6 meses, com os fechamentos REAIS daquele dia
    def fechamento(ativo):
        serie = cotacoes.historico(ativo, "1y")
        return min(serie, key=lambda p: abs(p[0].replace(tzinfo=timezone.utc) - seis_meses.astimezone(timezone.utc)))[1]

    with conectar() as con:
        con.execute("UPDATE teses SET criada_em = ?, preco_inicial = ?, bench_inicial = ?, revisar_em = ? WHERE id = ?",
                    (seis_meses.isoformat(), fechamento("WEGE3"), fechamento("IBOV"), datetime.now(BRT).date().isoformat(), t.id))
    rev = diario.revisao_de_teses()
    _salvar("diario-aceite.md", rev, dados)
    assert f"#{t.id}" in rev and "chegou a data de revisão" in rev
    assert "WEGE3:" in rev and "IBOV:" in rev and "excesso" in rev and ("a favor" in rev or "contra a tese" in rev)
    assert "Premissas — ainda valem?" in rev
