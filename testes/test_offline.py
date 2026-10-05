"""Fase 16 — versão offline: cérebro só local, rede desligada (só cache), cofre criptografado de clientes reais (só
offline e só no PC), pacote de dados, verificador e telas do Terminal. Sem internet e sem Ollama (simulados)."""

import json
import tarfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from quiron.nucleo import cerebro, offline
from quiron.nucleo.config import carregar_config
from quiron.servicos.mercado import http
from quiron.servicos.offline import cofre, pacote

SENHA = "uma frase longa de teste"


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("QUIRON_BIBLIOTECA", str(tmp_path / "bib"))
    monkeypatch.setenv("QUIRON_COFRE", str(tmp_path / "cofre" / "clientes.cofre"))
    monkeypatch.delenv("QUIRON_MODO", raising=False)
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    carregar_config.cache_clear()
    yield tmp_path
    carregar_config.cache_clear()
    http.definir_cliente(None)


def _offline(monkeypatch):
    monkeypatch.setenv("QUIRON_MODO", "offline")
    carregar_config.cache_clear()


def test_cerebro_offline_so_usa_o_modelo_local(monkeypatch):
    _offline(monkeypatch)
    assert carregar_config().modelos == ["ollama_chat/qwen2.5:3b"]
    chamadas = []

    class LLM:
        @staticmethod
        def completion(**k):
            chamadas.append(k)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))])

    monkeypatch.setattr(cerebro, "_litellm", lambda: LLM)
    assert cerebro.perguntar("oi").texto == "ok"
    k = chamadas[0]
    assert k["model"] == "ollama_chat/qwen2.5:3b" and k["api_base"] == "http://127.0.0.1:11434" and k["num_ctx"] == 8192
    monkeypatch.delenv("QUIRON_MODO")
    carregar_config.cache_clear()
    assert not any(offline.e_local(m) for m in carregar_config().modelos)  # normal: nuvem


def test_rede_offline_usa_so_o_cache(monkeypatch):
    def nunca(req):
        raise AssertionError("offline não pode sair para a internet")

    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"v": 1}))))
    assert http.obter("https://api.exemplo/x", fonte="X", ttl=60).conteudo == {"v": 1}  # online: guarda no cache
    _offline(monkeypatch)
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(nunca)))
    r = http.obter("https://api.exemplo/x", fonte="X", ttl=0)
    assert r.conteudo == {"v": 1} and r.desatualizado
    with pytest.raises(http.FonteIndisponivel, match="offline"):
        http.obter("https://api.exemplo/outro", fonte="Y", ttl=60)
    from quiron.servicos.mercado import cotacoes

    with pytest.raises(http.FonteIndisponivel, match="offline"):
        cotacoes.yahoo("IBOV")


def test_cofre_criptografado_so_abre_offline(monkeypatch, ambiente):
    with pytest.raises(cofre.CofreBloqueado):
        cofre.criar(SENHA)  # versão normal: nem cria
    _offline(monkeypatch)
    with pytest.raises(ValueError):
        cofre.criar("curta")
    c = cofre.criar(SENHA)
    c.gravar("cli-012", nome="Marcos Antônio Pereira", telefone="(11) 98765-4321", cidade="Campinas")
    bruto = cofre.caminho().read_bytes()
    assert bruto.startswith(cofre.CABECALHO) and b"Marcos" not in bruto and "Pereira".encode() not in bruto
    aberto = cofre.abrir(SENHA)
    assert aberto.clientes["CLI-012"].nome == "Marcos Antônio Pereira"
    assert [x.codigo for x in aberto.buscar("marcos")] == ["CLI-012"] and aberto.buscar("98765")[0].codigo == "CLI-012"
    with pytest.raises(cofre.SenhaErrada):
        cofre.abrir("senha errada qualquer")
    aberto.trocar_senha("outra frase bem longa")
    assert cofre.abrir("outra frase bem longa").clientes
    assert aberto.remover("CLI-012") and not cofre.abrir("outra frase bem longa").clientes
    monkeypatch.setenv("LLM_LOCAL_OFFLINE", "gemini/gemini-flash-latest")  # alguém pôs nuvem no offline: não abre
    carregar_config.cache_clear()
    with pytest.raises(cofre.CofreBloqueado, match="nuvem"):
        cofre.abrir("outra frase bem longa")


def test_esquecer_lembra_do_cofre(monkeypatch):
    from quiron.servicos import lgpd

    _offline(monkeypatch)
    cofre.criar(SENHA)
    assert "quiron-offline cofre remover CLI-012" in lgpd.esquecer_cliente("CLI-012").descrever()


def test_pacote_leva_dados_mas_nunca_o_cofre(monkeypatch, ambiente):
    from quiron.nucleo.config import pasta_biblioteca, pasta_dados
    from quiron.servicos.planejamento import ficha

    (pasta_biblioteca() / "indice").mkdir(parents=True)
    (pasta_biblioteca() / "indice" / "chroma.sqlite3").write_text("indice")
    ficha.salvar({"cliente": "CLI-012", "idade": 52})
    import sqlite3

    with sqlite3.connect(pasta_dados() / "academia.db") as con:
        con.execute("CREATE TABLE t (x)")
        con.execute("INSERT INTO t VALUES (42)")
    _offline(monkeypatch)
    cofre.criar(SENHA)
    arq = pacote.gerar()
    with tarfile.open(arq) as tar:
        nomes = tar.getnames()
    assert "biblioteca/indice/chroma.sqlite3" in nomes and "dados/fichas/CLI-012.json" in nomes and "dados/academia.db" in nomes
    assert not any("cofre" in n for n in nomes)

    # importa num "outro PC": o que existia vai para a reserva
    novo = ambiente / "pc2"
    monkeypatch.setenv("QUIRON_DADOS", str(novo / "dados"))
    monkeypatch.setenv("QUIRON_BIBLIOTECA", str(novo / "bib"))
    (novo / "dados" / "fichas").mkdir(parents=True)
    (novo / "dados" / "fichas" / "antiga.json").write_text("{}")
    r = pacote.importar(arq)
    assert (novo / "bib" / "indice" / "chroma.sqlite3").read_text() == "indice"
    assert json.loads((novo / "dados" / "fichas" / "CLI-012.json").read_text())["idade"] == 52
    with sqlite3.connect(novo / "dados" / "academia.db") as con:
        assert con.execute("SELECT x FROM t").fetchone() == (42,)
    assert r["reserva"] and (novo / "dados" / r["reserva"].split("/dados/")[-1] / "dados" / "fichas" / "antiga.json").exists()

    ruim = ambiente / "ruim.tar.gz"
    with tarfile.open(ruim, "w:gz") as tar:
        f = ambiente / "x.txt"
        f.write_text("x")
        tar.add(f, arcname="../../fora.txt")
    with pytest.raises(ValueError):
        pacote.importar(ruim)


def test_verificar(monkeypatch):
    from quiron.servicos.offline import cli

    monkeypatch.setattr(cli.httpx, "get", lambda url, timeout: SimpleNamespace(json=lambda: {"models": [{"name": "qwen2.5:3b"}]}))
    itens = {n: (ok, info) for n, ok, info in cli.verificar()}
    assert itens["Ollama rodando"][0] and itens["Modelo qwen2.5:3b"][0]
    assert not itens["Índice da biblioteca"][0] and not itens["Cofre de clientes"][0]

    def fora(url, timeout):
        raise httpx.ConnectError("recusado")

    monkeypatch.setattr(cli.httpx, "get", fora)
    assert "ollama.com/download" in {n: info for n, ok, info in cli.verificar()}["Ollama rodando"]


def test_terminal_cofre_so_offline_e_no_pc(monkeypatch):
    from quiron.terminal.backend import app as terminal

    terminal._cofre.cofre = None
    c = TestClient(terminal.app)
    h = {"X-Quiron": "terminal"}
    assert c.get("/api/modo").json()["offline"] is False
    assert c.post("/api/cofre/abrir", json={"senha": SENHA, "criar": True}, headers=h).status_code == 403  # normal: nada
    assert c.get("/api/offline/pacote", headers=h).status_code == 403  # sem TERMINAL_SENHA, sem pacote

    _offline(monkeypatch)
    assert c.post("/api/cofre/abrir", json={"senha": SENHA, "criar": True}).status_code == 403  # sem o cabeçalho da tela
    assert c.post("/api/cofre/abrir", json={"senha": SENHA, "criar": True}, headers={**h, "host": "pc.tail1.ts.net"}).status_code == 403
    assert c.post("/api/cofre/abrir", json={"senha": SENHA, "criar": True}, headers=h).json() == {"ok": True, "clientes": 0}
    assert c.get("/api/modo").json() == {"offline": True, "modelo": "ollama_chat/qwen2.5:3b", "cofre_existe": True, "cofre_aberto": True}
    assert c.post("/api/cofre/cliente", json={"codigo": "CLI-012", "nome": "Marcos Antônio Pereira", "cidade": "Campinas"},
                  headers=h).status_code == 200
    from quiron.servicos.planejamento import ficha

    ficha.salvar({"cliente": "CLI-012", "idade": 52, "ocupacao": "profissional_liberal"})
    d = c.get("/api/cofre/cliente/cli-012", headers=h).json()
    assert d["cliente"]["nome"] == "Marcos Antônio Pereira" and "DOSSIÊ DE REUNIÃO — CLI-012" in d["dossie"] and "52 anos" in d["dossie"]
    assert c.get("/api/cofre/clientes?q=marcos", headers=h).json()["itens"][0]["codigo"] == "CLI-012"
    assert c.post("/api/cofre/fechar", headers=h).json() == {"ok": True}
    assert c.get("/api/cofre/clientes").status_code == 403  # sem o cabeçalho da tela
    assert c.get("/api/cofre/clientes", headers=h).status_code == 423  # fechado
    assert c.post("/api/cofre/abrir", json={"senha": "errada errada"}, headers=h).status_code == 401
    assert "vazia" in c.get("/api/biblioteca?q=duration").json()["texto"]  # biblioteca local responde (vazia aqui)
