"""Fase 12 — Terminal v2: ações protegidas, análise pela tela (→ RPT), carteira, alertas, tarefas e chat (sem internet)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from quiron.servicos import alertas
from quiron.servicos.analise import fila as mod_fila
from quiron.servicos.analise.fila import TIPOS, tipo
from quiron.terminal.backend import app as terminal
from testes.test_analise import _relatorio

H = {"X-Quiron": "terminal"}


@pytest.fixture
def c(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    monkeypatch.setattr(mod_fila, "_FILA", None)
    monkeypatch.setattr(mod_fila.Fila, "iniciar_processador", lambda self: None)  # o teste processa na mão
    return TestClient(terminal.app)


def test_acoes_exigem_cabecalho_da_tela_e_host_local(c):
    for metodo, url in [("post", "/api/analisar"), ("post", "/api/alertas"), ("post", "/api/tarefas"), ("post", "/api/chat"),
                        ("post", "/api/carteira/ler"), ("delete", "/api/alertas/1"), ("delete", "/api/tarefas/1")]:
        r = getattr(c, metodo)(url, **({"json": {}} if metodo == "post" else {}))
        assert r.status_code == 403, url
    r = c.post("/api/alertas", json={"tipo": "noticia", "alvo": "Copom"}, headers={**H, "host": "malicioso.com"})
    assert r.status_code == 403  # DNS rebinding: sem senha, só o PC ou o Tailscale
    assert c.post("/api/alertas", json={"tipo": "noticia", "alvo": "Copom"}, headers={**H, "host": "pc.tail1234.ts.net"}).status_code == 200


def test_analise_pedida_na_tela_aparece_em_rpt(c, monkeypatch):
    @tipo("teste_terminal", "teste")
    def _ok(params, modo):
        r = _relatorio()
        r.titulo = f"Valuation de teste — {params['empresa']}"
        return r

    monkeypatch.setattr(mod_fila, "carregar_tipos", lambda: TIPOS)
    try:
        assert c.post("/api/analisar", json={"tipo": "nao_existe"}, headers=H).status_code == 400
        r = c.post("/api/analisar", json={"tipo": "teste_terminal", "parametros": {"empresa": "WEGE3"}}, headers=H).json()
        assert r["situacao"] == "na fila" and r["na_frente"] == 0
        assert c.get("/api/relatorios").json()["itens"][0]["situacao"] == "na fila"
        mod_fila.fila().processar_uma()
        item = c.get("/api/relatorios").json()["itens"][0]
        assert item["id"] == r["id"] and item["situacao"] == "pronta" and item["pdf"] and "WEGE3" in item["titulo"]
        assert mod_fila.fila().obter(r["id"]).origem == "terminal"
        pdf = c.get(f"/relatorios/{r['id']}/relatorio.pdf")
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    finally:
        TIPOS.pop("teste_terminal")


def test_carteira_colada_vira_enquadramento(c, monkeypatch):
    from quiron.servicos.carteira import leitura

    def sem_cerebro(*a, **k):
        raise leitura.cerebro.CerebroIndisponivel("teste offline")

    monkeypatch.setattr(leitura.cerebro, "perguntar", sem_cerebro)  # leitura por regras: determinística
    texto = "Tesouro IPCA+ 2035 R$ 120.000\nCDB Banco X 110% CDI 80 mil\nBOVA11 R$ 45.000\nIVVB11 R$ 30.000"
    r = c.post("/api/carteira/ler", json={"texto": texto, "perfil": "moderado", "cliente": "João"}, headers=H).json()
    assert r["id"].startswith("CART-") and r["total"] == pytest.approx(275000)
    assert len(r["posicoes"]) == 4
    ipca = next(x for x in r["enquadramento"] if x["classe"].startswith("Inflação"))
    assert ipca["atual"] == pytest.approx(43.64, abs=0.01) and ipca["situacao"].startswith("acima")
    from quiron.servicos.carteira import arquivo

    assert arquivo.carregar(r["id"]).cliente == ""  # nome nunca é guardado: só CLI-XXX
    assert c.post("/api/carteira/ler", json={"texto": "x"}, headers=H).status_code == 400


def test_alertas_disparam_uma_vez_por_condicao(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    with pytest.raises(alertas.AlertaInvalido):
        alertas.criar("preco_acima", "PETR4")  # sem valor
    alertas.criar("preco_abaixo", "petr4", 30)
    alertas.criar("variacao", "IBOV", 2)
    alertas.criar("noticia", "Copom")
    precos = {"PETR4": SimpleNamespace(preco=31.0, variacao_pct=0.5), "IBOV": SimpleNamespace(preco=1, variacao_pct=-2.4)}
    noticias = [{"titulo": "Copom mantém a Selic", "link": "https://x/1"}]
    cot, news = (lambda t: precos[t]), (lambda termo: list(noticias))
    disparados = alertas.avaliar(cot, news)
    assert [a.tipo for a in disparados] == ["variacao", "noticia"]
    assert alertas.avaliar(cot, news) == []  # mesma condição e mesma notícia: não repete
    precos["PETR4"] = SimpleNamespace(preco=29.5, variacao_pct=-4.8)
    noticias.append({"titulo": "Ata do Copom", "link": "https://x/2"})
    assert [a.tipo for a in alertas.avaliar(cot, news)] == ["preco_abaixo", "noticia"]
    assert "PETR4" in alertas.mensagem(alertas.listar()[0]) and "29,50" in alertas.listar()[0].detalhe

    def quebrada(t):
        raise TimeoutError

    assert alertas.avaliar(quebrada, news) == []  # fonte fora do ar não derruba nada
    assert alertas.remover(1) and not alertas.remover(1) and len(alertas.listar()) == 2


def test_alertas_e_tarefas_pela_api(c):
    r = c.post("/api/alertas", json={"tipo": "preco_acima", "alvo": "wege3", "valor": "60,5"}, headers=H).json()
    assert "WEGE3" in r["descricao"] and "60.5" in r["descricao"]
    assert c.post("/api/alertas", json={"tipo": "xyz", "alvo": "a"}, headers=H).status_code == 400
    assert c.delete(f"/api/alertas/{r['id']}", headers=H).json() == {"ok": True}

    amanha = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
    t = c.post("/api/tarefas", json={"texto": "Ligar para CLI-004", "tipo": "lembrete", "quando": amanha.strftime("%Y-%m-%dT%H:%M")},
               headers=H).json()
    assert "CLI-004" in t["descricao"]
    s = c.post("/api/tarefas", json={"texto": "Revisar carteiras", "tipo": "tarefa", "recorrencia": "semanal segunda 08:00"},
               headers=H).json()
    assert "semanal" in s["descricao"]
    assert c.post("/api/tarefas", json={"texto": "x", "recorrencia": "de vez em quando"}, headers=H).status_code == 400
    assert c.post("/api/tarefas", json={"texto": "x"}, headers=H).status_code == 400  # "uma vez" sem data
    assert c.delete(f"/api/tarefas/{t['id']}", headers=H).json() == {"ok": True}

    from quiron.terminal.backend import dados

    assert [i["texto"] for i in dados.tarefas()["itens"]] == ["Revisar carteiras"]
    assert dados.alertas_lista()["itens"] == [] and "noticia" in dados.alertas_lista()["tipos"]
    assert dados.plano() == {"lista": []}


def test_chat_usa_o_agente_com_conversa_propria(c, monkeypatch):
    chamadas = []

    class AgenteFalso:
        memoria = SimpleNamespace(reiniciar=lambda chat: chamadas.append(("novo", chat)))

        async def responder(self, texto, chat):
            chamadas.append((texto, chat))
            return SimpleNamespace(resposta="Selic em 15%.", pendencias=[SimpleNamespace(id=7, resumo="enviar e-mail")],
                                   ferramentas=["quiron-mercado__painel"], segundos=1.24)

    async def obter():
        return AgenteFalso()

    monkeypatch.setattr(terminal._chat, "obter", obter)
    r = c.post("/api/chat", json={"texto": "Como está a Selic?"}, headers=H).json()
    assert r == {"resposta": "Selic em 15%.", "pendencias": [{"id": 7, "resumo": "enviar e-mail"}],
                 "ferramentas": ["quiron-mercado__painel"], "segundos": 1.2}
    assert c.post("/api/chat", json={"texto": "/novo"}, headers=H).json()["resposta"] == "Conversa reiniciada."
    assert chamadas == [("Como está a Selic?", terminal.CHAT_TERMINAL), ("novo", terminal.CHAT_TERMINAL)]
    assert c.post("/api/chat", json={"texto": "  "}, headers=H).status_code == 400


def test_frontend_v2_sem_aviso_de_fase_futura(c):
    js = c.get("/app.js").text
    assert "chega no Terminal v2" not in js
    for comando in ["WEGE3 DCF", "FUND <nome>", "PORT", "PLAN [CLI-XXX]", "ACAD", "TASK", "ALRT", "CHAT [pergunta]"]:
        assert comando in js
    assert '"X-Quiron": "terminal"' in js
    assert c.get("/manifest.webmanifest").status_code == 200 and "theme-color" in c.get("/").text
