"""Depuração 4 (08/10/2026): um teste por correção da rodada de otimização e depuração."""

import json
import os
from datetime import date, datetime
from pathlib import Path

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


# ---------------------------------------------------------------- otimizações (08/10/2026)
def test_yaml_em_cache_relido_quando_o_arquivo_muda(tmp_path):
    from quiron.nucleo import config

    arq = tmp_path / "x.yaml"
    arq.write_text("a: 1\nlista: [1, 2]\n", encoding="utf-8")
    primeiro = config.ler_yaml_arquivo(arq)
    primeiro["lista"].append(99)  # quem mexe no resultado não estraga o cache
    assert config.ler_yaml_arquivo(arq) == {"a": 1, "lista": [1, 2]}
    novo = tmp_path / "x.tmp"
    novo.write_text("a: 2\n", encoding="utf-8")
    os.replace(novo, arq)  # troca atômica (como as gravações do Quíron)
    assert config.ler_yaml_arquivo(arq) == {"a": 2}


def test_banco_padrao_em_wal_com_espera(tmp_path):
    from quiron.nucleo.banco import conectar

    con = conectar(tmp_path / "b.db")
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_uma_coleta_de_noticias_por_vez(monkeypatch):
    import threading
    import time as _t

    from quiron.servicos.noticias import coleta, consultas

    chamadas = []
    monkeypatch.setattr(coleta, "coletar", lambda: (chamadas.append(1), _t.sleep(0.3), [])[2])
    monkeypatch.setattr(consultas, "_ultima_coleta", None)
    ts = [threading.Thread(target=consultas._garantir_coleta) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(chamadas) == 1  # três painéis pedindo juntos = uma coleta


def test_noticias_antigas_saem_do_banco():
    from datetime import timedelta, timezone

    from quiron.servicos.noticias import coleta

    agora = datetime.now(timezone.utc)
    with coleta._banco() as con:
        for i, dias in enumerate((1, 200)):
            con.execute("INSERT INTO noticias(id, titulo, publicado_em) VALUES (?,?,?)",
                        (f"n{i}", f"t{i}", (agora - timedelta(days=dias)).isoformat()))
    assert coleta.limpar_antigas() == 1
    with coleta._banco() as con:
        assert [r[0] for r in con.execute("SELECT id FROM noticias")] == ["n0"]


def test_memo_do_terminal_carimba_o_inicio_da_consulta(monkeypatch):
    import asyncio
    import time as _t

    from quiron.terminal.backend import app as terminal
    from quiron.terminal.backend import dados as d

    monkeypatch.setitem(d.TOPICOS, "lento", (lambda: _t.sleep(0.3) or {"ok": 1}, 1))
    monkeypatch.setattr(terminal, "_memo", {})
    antes = _t.time()
    asyncio.run(terminal.obter_topico("lento", {}))
    carimbo = next(v for k, v in terminal._memo.items() if "lento" in k)[0]
    assert carimbo - antes < 0.1  # início, não fim (consulta lenta não faz a próxima atualização cair no memo)


def test_modelo_de_embeddings_sai_da_memoria_quando_parado(monkeypatch):
    import time as _t

    from quiron.servicos.biblioteca import embeddings as emb

    class Motor:
        def embed(self, textos, batch_size=16):
            import numpy as np

            return [np.zeros(3) for _ in textos]

    monkeypatch.setattr(emb, "OCIOSO_S", 0.2)
    fe = emb.FastEmbed()
    monkeypatch.setattr(fe, "_carregar", lambda: fe._motor or setattr(fe, "_motor", Motor()) or fe._motor)
    assert fe.vetores(["a", "b"]) == [[0.0] * 3] * 2 and fe._motor is not None
    _t.sleep(0.6)
    assert fe._motor is None  # descarregado depois de parado
    assert fe.vetor_consulta("c") == [0.0] * 3  # e volta sozinho no próximo uso


def test_mcp_sobe_os_servidores_em_paralelo_sem_uv(monkeypatch, tmp_path):
    import sys

    from quiron.runtime import ferramentas_mcp as f

    assert f._comando({"command": "python", "args": ["-c", "1"]})[1] == ["-c", "1"]
    script = Path(sys.executable).parent / "quiron-mcp-sistema"
    cmd, args = f._comando({"command": "uv", "args": ["run", "--quiet", "quiron-mcp-sistema"]})
    if script.exists() or script.with_suffix(".exe").exists():
        assert Path(cmd).name.startswith("quiron-mcp-sistema") and args == []
    monkeypatch.setenv("QUIRON_MCP_VIA_UV", "1")
    assert f._comando({"command": "uv", "args": ["run", "x"]})[1] == ["run", "x"]


def test_websocket_ignora_mensagem_que_nao_e_json(monkeypatch):
    from fastapi.testclient import TestClient

    from quiron.terminal.backend.app import app

    monkeypatch.setitem(__import__("quiron.terminal.backend.dados", fromlist=["x"]).TOPICOS, "eco", (lambda: {"ok": True}, 60))
    with TestClient(app).websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_text("isto não é json")
        ws.send_text(json.dumps({"tipo": "assinar", "paineis": [{"id": "p1", "topico": "eco", "params": {}}]}))
        msg = json.loads(ws.receive_text())
        assert msg["id"] == "p1" and msg["dados"] == {"ok": True}


def test_titulo_com_cdata_escapado_nao_some():
    from quiron.servicos.noticias.coleta import texto_limpo

    assert texto_limpo("<![CDATA[Pharmaceutical Executive Daily: FDA Approves Tecentriq]]>") == \
        "Pharmaceutical Executive Daily: FDA Approves Tecentriq"  # PharmExec: antes virava "" e o feed ficava vazio
    assert texto_limpo("<p>Selic <b>mantida</b></p>") == "Selic mantida"


def test_focus_sem_select():
    from quiron.servicos.mercado import bcb

    urls = []

    class R:
        dados = {"value": []}
    bcb_obter = bcb.obter
    try:
        bcb.obter = lambda url, **k: (urls.append(url), (_ for _ in ()).throw(RuntimeError("parar")))[1]
        with pytest.raises(RuntimeError):
            bcb.focus("ipca", 2026)
    finally:
        bcb.obter = bcb_obter
    assert "%24select" not in urls[0] and "$select" not in urls[0]  # o firewall do BC recusa (403) consulta com $select


def test_telas_nao_ficam_em_cache_depois_de_atualizar():
    from fastapi.testclient import TestClient

    from quiron.terminal.backend.app import app

    c = TestClient(app, base_url="http://127.0.0.1")
    for caminho in ("/", "/app.js", "/tema.css", "/cartas"):
        assert c.get(caminho).headers.get("cache-control") == "no-cache", caminho


def test_iof_da_calculadora_bate_com_a_tabela_oficial():
    from quiron.nucleo import regras
    from quiron.servicos.calculadoras import aliquota_iof

    tabela = regras.carregar_regras()["renda_fixa"]["iof"]["tabela_dia_1_a_30"]  # Decreto 6.306/2007, anexo
    assert [round(aliquota_iof(d) * 100) for d in range(1, 31)] == tabela


def test_lucro_presumido_com_acrescimo_da_lc_224_acima_de_5_milhoes():
    from quiron.servicos.planejamento import impostos

    ate = impostos.lucro_presumido(4_000_000)
    assert ate.irpj == pytest.approx(4_000_000 * 0.32 * 0.15)  # abaixo do limite: nada muda
    acima = impostos.lucro_presumido(6_000_000)
    base = 6_000_000 * 0.32 + 1_000_000 * 0.32 * 0.10  # só o R$ 1 mi acima do limite tem presunção de 35,2%
    assert acima.irpj == pytest.approx(base * 0.15) and acima.csll == pytest.approx(base * 0.09)
