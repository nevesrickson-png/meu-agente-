"""Terminal: API, WebSocket, calculadoras, layouts e senha — com fontes gravadas (sem internet)."""

import time
from datetime import datetime, timezone

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quiron.servicos import calculadoras
from quiron.servicos.mercado import bcb, cotacoes, http
from quiron.servicos.noticias import coleta
from quiron.servicos.noticias import consultas as nc
from quiron.terminal.backend import app as terminal
from quiron.terminal.backend import dados
from testes import gravacoes_mercado as gm
from testes import gravacoes_noticias as gn


def _roteador(req):
    r = gm.roteador(req)
    return r if r.status_code != 503 else gn.roteador(req)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    monkeypatch.setattr(bcb, "_api_fora_ate", 0.0)
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(_roteador)))
    monkeypatch.setattr(coleta, "ler_fontes", lambda: gn.FONTES[:3])
    monkeypatch.setattr(nc, "_ultima_coleta", None)
    from testes.test_noticias import Agora  # relógio fixo: as notícias gravadas são de 03/10/2026
    monkeypatch.setattr(coleta, "datetime", Agora)
    monkeypatch.setattr(nc, "datetime", Agora)

    def yahoo_falso(simbolo, periodo="5d"):
        n = {"5d": 5, "3mo": 60, "6mo": 120}.get(periodo, 60)
        idx = pd.date_range(end=datetime(2026, 10, 2, tzinfo=timezone.utc), periods=n, freq="D")
        base = 100.0 if simbolo != "^BVSP" else 140000.0
        return pd.DataFrame({"Close": [base + i for i in range(n)]}, index=idx)

    monkeypatch.setattr(cotacoes, "_historico_yahoo", yahoo_falso)
    cotacoes._memo.clear()
    terminal._memo.clear()
    dados._fundo.clear()
    dados._ultimo_ok.clear()
    yield TestClient(terminal.app)
    http.definir_cliente(None)


def test_pagina_e_arquivos(cliente):
    assert "<title>Quíron</title>" in cliente.get("/").text
    assert cliente.get("/app.js").status_code == 200
    assert cliente.get("/vendor/lightweight-charts.standalone.production.js").status_code == 200


def test_topicos(cliente):
    c = cliente.get("/api/topico/cotacao", params={"ativo": "petr4"}).json()
    assert c["preco"] == 38.45 and c["fonte"] == "brapi (B3)" and c["obtido_em"].endswith("+00:00")
    h = cliente.get("/api/topico/historico", params={"ativo": "IBOV", "periodo": "3mo"}).json()
    assert len(h["datas"]) == 60 and h["series"]["Média 20d"][19] == pytest.approx(140009.5) and h["series"]["Média 20d"][0] is None
    comp = cliente.get("/api/topico/historico", params={"ativo": "PETR4", "periodo": "3mo", "comparar": "IBOV"}).json()
    assert comp["modo"] == "comparacao" and comp["series"]["PETR4"][0] == pytest.approx(100.0)
    j = cliente.get("/api/topico/juros").json()
    for _ in range(50):  # o Tesouro vem em segundo plano
        if not j.get("parcial"):
            break
        time.sleep(0.1)
        j = cliente.get("/api/topico/juros").json()
    assert j["series"][0]["valor"] == 15.0 and any(t["nome"] == "Tesouro IPCA+ 2029" for t in j["tesouro"]["titulos"])
    cv = cliente.get("/api/topico/curva").json()
    assert cv["fonte"] == "ANBIMA (ETTJ)" and cv["vertices"][0]["pre"] == 14.9
    m = cliente.get("/api/topico/macro").json()
    assert m["focus"]["itens"][0]["mediana"] == 4.85
    n = cliente.get("/api/topico/top").json()
    assert n["itens"] and n["itens"][0]["titulo"].startswith("Ibovespa dispara")
    a = cliente.get("/api/topico/ativo", params={"ticker": "PETR4"}).json()
    assert a["cotacao"]["preco"] == 38.45 and a["noticias"]["itens"]
    s = cliente.get("/api/topico/status").json()
    assert s["memoria_mb"] > 0 and any(f["fonte"].startswith("Banco Central") for f in s["fontes"])
    assert cliente.get("/api/topico/inexistente").status_code == 404


def test_fonte_fora_do_ar_vira_erro_no_item(cliente):
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    dados._fundo.clear()
    dados._ultimo_ok.clear()
    j = cliente.get("/api/topico/juros").json()
    for _ in range(50):
        if not j.get("parcial"):
            break
        time.sleep(0.1)
        j = cliente.get("/api/topico/juros").json()
    assert all("erro" in s for s in j["series"]) and "erro" in j["tesouro"]


def test_calculadoras_conferidas_a_mao(cliente):
    r = cliente.post("/api/calc/juros_compostos", json={"valor_inicial": "10000", "aporte_mensal": "1000", "taxa_aa": "12", "anos": "10"}).json()
    assert dict(r["linhas"])["Valor final"] == "R$ 252.988,52"  # 10000·1,12^10 + 1000·((1,12^10−1)/i)
    eq = calculadoras.equivalencia(1, "am")
    assert dict(eq.linhas)["Ao ano"] == "12,6825%"  # 1,01^12 − 1
    cdb = calculadoras.cdb_x_isento(11, 13.5, 720)  # 361–720 dias: 17,5%
    assert dict(cdb.linhas)["Alíquota de IR no prazo"] == "17,5%" and dict(cdb.linhas)["CDB líquido"] == "11,14% a.a."
    assert dict(calculadoras.taxa_real(13.75, 4.5).linhas)["Taxa real"] == "8,85% a.a."
    pc = cliente.post("/api/calc/percentual_cdi", json={"percentual": "100"}).json()
    assert dict(pc["linhas"])["Taxa equivalente"] == "14,90% a.a."  # 100% do CDI (gravado 14,90) = o próprio CDI
    assert "erro" in cliente.post("/api/calc/taxa_real", json={"nominal_aa": "abc", "inflacao_aa": "1"}).json()


def test_layouts(cliente):
    assert cliente.get("/api/layouts").json() == {}
    corpo = [{"tipo": "watchlist", "x": 1, "y": 1, "w": 4, "h": 8}]
    assert cliente.put("/api/layouts/Meu", json=corpo).status_code == 403  # outro site não grava layout
    cliente.put("/api/layouts/Meu", json=corpo, headers={"X-Quiron": "terminal"})
    assert cliente.get("/api/layouts").json()["Meu"][0]["tipo"] == "watchlist"
    assert cliente.delete("/api/layouts/Meu").status_code == 403
    cliente.delete("/api/layouts/Meu", headers={"X-Quiron": "terminal"})
    assert cliente.get("/api/layouts").json() == {}


def test_terminal_recusa_outros_sites_e_dns_rebinding(cliente):
    import pytest as _pytest
    from starlette.websockets import WebSocketDisconnect

    assert cliente.get("/api/topico/status", headers={"host": "evil.example"}).status_code == 403  # DNS rebinding
    assert cliente.get("/api/topico/noticias", params={"horas": "abc"}).status_code == 400
    assert cliente.get("/api/topico/status", params={"lixo": "1"}).status_code == 400
    with _pytest.raises(WebSocketDisconnect) as e:
        with cliente.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as w:
            w.receive_json()
    assert e.value.code == 4403
    with cliente.websocket_connect("/ws", headers={"origin": "http://testserver"}):
        pass  # a própria tela continua entrando


def test_websocket_empurra_os_paineis_assinados(cliente):
    with cliente.websocket_connect("/ws") as ws:
        ws.send_json({"tipo": "assinar", "paineis": [{"id": "p1", "topico": "cotacao", "params": {"ativo": "PETR4"}},
                                                     {"id": "p2", "topico": "curva", "params": {}}]})
        recebidos = {}
        while len(recebidos) < 2:
            m = ws.receive_json()
            recebidos[m["id"]] = m
        assert recebidos["p1"]["dados"]["preco"] == 38.45
        assert recebidos["p2"]["dados"]["vertices"]
        ws.send_json({"tipo": "atualizar", "id": "p1"})
        assert ws.receive_json()["id"] == "p1"


def test_senha_quando_configurada(cliente, monkeypatch):
    monkeypatch.setenv("TERMINAL_SENHA", "segredo")
    assert cliente.get("/", follow_redirects=False).headers["location"] == "/login"
    assert cliente.get("/api/topico/status").status_code == 401
    with pytest.raises(Exception):
        with cliente.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert cliente.post("/login", data={"senha": "errada"}, follow_redirects=False).headers["location"] == "/login?erro=1"
    r = cliente.post("/login", data={"senha": "segredo"}, follow_redirects=False)
    assert r.status_code == 303 and "quiron_sessao" in r.cookies
    assert cliente.get("/api/topico/status").status_code == 200


def test_memo_nao_segura_a_atualizacao_agendada(cliente, monkeypatch):
    import asyncio

    contagem = {"n": 0}

    def contar():
        contagem["n"] += 1
        return {"n": contagem["n"]}

    monkeypatch.setitem(dados.TOPICOS, "teste", (contar, 10))
    agora = [1000.0]
    monkeypatch.setattr(terminal.time, "time", lambda: agora[0])
    asyncio.run(terminal.obter_topico("teste", {}))
    agora[0] += 10.0  # exatamente o intervalo: precisa buscar de novo
    assert asyncio.run(terminal.obter_topico("teste", {}))["n"] == 2
    agora[0] += 1.0  # outra aba logo depois: usa o guardado
    assert asyncio.run(terminal.obter_topico("teste", {}))["n"] == 2
