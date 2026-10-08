"""Depuração 4 (08/10/2026): um teste por correção da rodada de otimização e depuração."""

import json
import os
from datetime import date, datetime

import pytest

from quiron.servicos.assessoria import datas

HOJE = date(2026, 10, 8)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    return tmp_path


@pytest.mark.parametrize("frase,esperado,titulo", [
    ("dia 31 de dezembro ligar", date(2026, 12, 31), "Ligar"),
    ("15 de março de 2027 revisar carteira", date(2027, 3, 15), "Revisar carteira"),
    ("reunião em 5 de novembro às 14h", date(2026, 11, 5), "Reunião"),
    ("3 de março entregar IR", date(2027, 3, 3), "Entregar IR"),  # já passou este ano → ano que vem
])
def test_data_com_mes_por_extenso(frase, esperado, titulo):
    texto, d, _ = datas.extrair(frase, HOJE)
    assert d == esperado and texto == titulo


def test_numeros_absurdos_nao_quebram():
    assert datas.interpretar("em 999999999 dias úteis", HOJE) is None
    assert datas.relativo("daqui a 999999999 horas", datetime(2026, 10, 8, 10))[1] is None


def test_fim_do_mes_no_ultimo_fim_de_semana():
    assert datas.interpretar("fim do mês", date(2026, 10, 31)) == date(2026, 10, 31)  # sábado: não some
    assert datas.interpretar("fim do mês", HOJE) == date(2026, 10, 30)


def test_lista_lgpd_corrompida_nao_e_regravada_vazia(tmp_path):
    from quiron.servicos import lgpd

    raiz = tmp_path / "dados"
    raiz.mkdir(parents=True, exist_ok=True)
    lgpd._anotar_esquecido(raiz, "CLI-001")
    lgpd._anotar_esquecido(raiz, "CLI-002")
    assert set(json.loads((raiz / "lgpd_esquecidos.json").read_text())) == {"CLI-001", "CLI-002"}
    (raiz / "lgpd_esquecidos.json").write_text('{"CLI-001": "2026-', encoding="utf-8")
    with pytest.raises(lgpd.ListaEsquecidosIlegivel):
        lgpd._anotar_esquecido(raiz, "CLI-003")
    assert (raiz / "lgpd_esquecidos.json").read_text() == '{"CLI-001": "2026-'  # nada foi apagado


def test_ajustes_gravados_sem_tmp_fixo(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from quiron.nucleo import config

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda i: config.salvar_ajuste("teste", {f"k{i}": i}), range(16)))
    assert config.ler_ajuste("teste") == {f"k{i}": i for i in range(16)}  # nenhuma gravação simultânea se perdeu
    assert not list(config.arquivo_ajuste("teste").parent.glob("*.tmp"))


def test_litellm_usa_tabela_local(monkeypatch):
    from quiron.nucleo import cerebro

    monkeypatch.delenv("LITELLM_LOCAL_MODEL_COST_MAP", raising=False)
    cerebro._litellm()
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def test_google_agenda_reaproveita_um_cliente_http():
    from quiron.servicos.organizacao import google_agenda as ga

    assert ga._cliente_compartilhado() is ga._cliente_compartilhado()
