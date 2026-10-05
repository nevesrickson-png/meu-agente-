"""Interface única: Terminal + Acervo + Configurações num só lugar, com o bot do Telegram supervisionado, Google Agenda,
troca de modo (normal/offline) pelo lançador `quiron` e proteção das rotas de sistema. Sem internet."""

import json
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

from quiron import iniciar
from quiron.configurador import app as configurador
from quiron.nucleo.config import carregar_config
from quiron.terminal.backend import app as terminal
from quiron.terminal.backend import central

H = {"X-Quiron": "terminal"}
CHAVES = {"TELEGRAM_BOT_TOKEN": "123456:abcdefghijklmnop", "TELEGRAM_ALLOWED_USER_IDS": "7592218870",
          "GEMINI_API_KEY": "AIzaSy-chave-de-teste-1234"}


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("QUIRON_SEGREDOS", str(tmp_path / "segredos"))
    for k in [*CHAVES, "TERMINAL_SENHA", "QUIRON_MODO", "QUIRON_CENTRAL", "GOOGLE_AGENDA_ID"]:
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    monkeypatch.setattr(configurador, "caminho_env", lambda: env)
    sup = central.Supervisor(espera=0.2)
    monkeypatch.setattr(central, "SUPERVISOR", sup)
    monkeypatch.setattr(sup, "outro_bot", lambda: None)
    monkeypatch.setattr(central, "SAIR", None)
    monkeypatch.setattr(central, "GOOGLE", central._Google())
    carregar_config.cache_clear()
    yield tmp_path
    sup.desligar()
    for k in CHAVES:
        os.environ.pop(k, None)
    carregar_config.cache_clear()


def _esperar(cond, segundos=8.0):
    fim = time.time() + segundos
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _bot_falso(texto="bot de teste no ar", dormir=30):
    return [sys.executable, "-c", f"import time; print({texto!r}, flush=True); time.sleep({dormir})"]


def test_paginas_integradas_com_a_mesma_barra_de_abas():
    c = TestClient(terminal.app)
    for pagina in ["/", "/acervo", "/config"]:
        html = c.get(pagina).text
        assert 'id="abas"' in html and "/nav.js" in html and "/nav.css" in html, pagina
    js = c.get("/nav.js").text
    assert all(x in js for x in ['"/acervo"', '"/config"', "/api/sistema/resumo"])
    assert "Google Agenda" in c.get("/config").text and "Versão offline" in c.get("/config").text
    r = c.get("/api/sistema/resumo").json()
    assert r == {"telegram": {"situacao": "externo", "desde": "", "reinicios": 0, "ultimo_erro": "", "pid": None},
                 "offline": False, "config_completa": False, "central": False}


def test_rotas_de_sistema_so_na_propria_tela_e_no_proprio_pc():
    c = TestClient(terminal.app)
    assert c.get("/api/sistema/estado").status_code == 403  # sem o cabeçalho da tela
    assert c.post("/api/sistema/config/salvar", json={"valores": CHAVES}).status_code == 403
    assert c.get("/api/sistema/estado", headers={**H, "host": "malicioso.com"}).status_code == 403  # DNS rebinding
    fora = TestClient(terminal.app, client=("100.101.102.103", 5000))  # outro aparelho pelo Tailscale, sem senha
    assert fora.get("/api/sistema/estado", headers={**H, "host": "pc.tail1.ts.net"}).status_code == 403
    assert c.get("/api/sistema/estado", headers=H).status_code == 200


def test_chaves_salvas_mascaradas_e_aplicadas_na_hora(ambiente):
    c = TestClient(terminal.app)
    e = c.get("/api/sistema/estado", headers=H).json()
    assert e["config"]["completo"] is False and e["local"] is True and e["telegram"]["situacao"] == "externo"
    r = c.post("/api/sistema/config/salvar", json={"valores": {**CHAVES, "GOOGLE_AGENDA_ID": "trabalho@group.calendar.google.com"}},
               headers=H).json()
    assert r["config"]["completo"] and "servidor" in r["mensagem"]  # sem modo central: avisa para reiniciar o serviço
    texto = (ambiente / ".env").read_text()
    assert "GEMINI_API_KEY=AIzaSy-chave-de-teste-1234" in texto and "GOOGLE_AGENDA_ID=trabalho@" in texto
    assert os.environ["GEMINI_API_KEY"] == "AIzaSy-chave-de-teste-1234"  # o bot (processo filho) nasce com as novas
    bruto = json.dumps(c.get("/api/sistema/estado", headers=H).json(), ensure_ascii=False)
    assert "AIzaSy-chave-de-teste-1234" not in bruto and "…1234" in bruto  # segredo nunca volta inteiro
    assert c.post("/api/sistema/config/salvar", json={"valores": {"TELEGRAM_ALLOWED_USER_IDS": "@rickson"}}, headers=H).status_code == 400
    assert c.post("/api/sistema/config/apagar", json={"chave": "GEMINI_API_KEY"}, headers=H).status_code == 400  # obrigatório


def test_supervisor_liga_registra_religa_e_desliga(monkeypatch):
    sup = central.SUPERVISOR
    with pytest.raises(ValueError, match="servidor"):
        sup.ligar()  # fora do modo central não liga nada
    sup.gerenciado = True
    with pytest.raises(ValueError, match="Falta preencher"):
        sup.ligar()
    configurador.atualizar_env(CHAVES)
    sup.comando = _bot_falso()
    sup.ligar()
    assert _esperar(lambda: sup.estado()["situacao"] == "ligado" and "bot de teste no ar" in sup.registro())
    pid = sup.estado()["pid"]
    sup.reiniciar()
    assert _esperar(lambda: sup.estado()["pid"] not in {None, pid})
    assert sup.reinicios == 0  # reinício pedido não conta como queda
    sup.desligar()
    assert sup.estado()["situacao"] == "desligado" and sup.estado()["pid"] is None

    sup.comando = [sys.executable, "-c", "import sys; print('caiu'); sys.exit(2)"]  # bot que cai: religa sozinho
    sup.ligar()
    assert _esperar(lambda: sup.reinicios >= 2)
    assert "código 2" in sup.ultimo_erro
    sup.desligar()

    monkeypatch.setattr(sup, "outro_bot", lambda: 4242)  # janela antiga ainda ligada: não sobe um segundo bot
    with pytest.raises(ValueError, match="4242"):
        sup.ligar()


def test_primeiro_uso_salvar_as_chaves_liga_o_telegram():
    sup = central.SUPERVISOR
    sup.gerenciado = True
    sup.comando = _bot_falso()
    c = TestClient(terminal.app)
    assert c.get("/api/sistema/resumo").json()["telegram"]["situacao"] == "sem_config"
    r = c.post("/api/sistema/config/salvar", json={"valores": CHAVES}, headers=H).json()
    assert "ligou no Telegram" in r["mensagem"]
    assert _esperar(lambda: sup.estado()["situacao"] == "ligado")
    r = c.post("/api/sistema/config/salvar", json={"valores": {"BRAPI_TOKEN": "tok-brapi-123456"}}, headers=H).json()
    assert "reiniciado" in r["mensagem"]
    assert c.post("/api/sistema/telegram/desligar", headers=H).json()["situacao"] == "desligado"
    assert c.post("/api/sistema/telegram/explodir", headers=H).status_code == 404


def test_google_agenda_credencial_e_autorizacao_pela_tela(ambiente):
    c = TestClient(terminal.app)
    g = c.get("/api/sistema/google", headers=H).json()
    assert g["credencial"] is False and g["autorizado"] is False
    assert c.post("/api/sistema/google/conectar", headers=H).status_code == 400  # sem credencial
    assert c.post("/api/sistema/google/credencial", content=b"{}", headers=H).status_code == 400
    assert c.post("/api/sistema/google/credencial", content=b"nao e json", headers=H).status_code == 400
    cred = {"installed": {"client_id": "123.apps.googleusercontent.com", "client_secret": "s"}}
    assert c.post("/api/sistema/google/credencial", content=json.dumps(cred).encode(), headers=H).json()["credencial"] is True
    assert (ambiente / "segredos" / "google_oauth.json").exists()

    def autorizar_falso(abrir_navegador, saida, abrir):
        abrir("https://accounts.google.com/o/oauth2/auth?x=1")
        (ambiente / "segredos" / "google_token.json").write_text("{}")
        return "✅ Google Agenda autorizado."

    import webbrowser

    abertos = []
    original = webbrowser.open
    webbrowser.open = abertos.append
    try:
        central.GOOGLE.conectar(autorizar=autorizar_falso)
        assert _esperar(lambda: not central.GOOGLE.andamento)
    finally:
        webbrowser.open = original
    g = c.get("/api/sistema/google", headers=H).json()
    assert g["autorizado"] and g["ok"] and "autorizado" in g["resultado"] and abertos
    fora = TestClient(terminal.app, client=("100.101.102.103", 5000))
    assert fora.post("/api/sistema/google/conectar", headers=H).status_code == 403
    assert c.post("/api/sistema/google/desconectar", headers=H).json()["autorizado"] is False


def test_troca_de_modo_so_pelo_lancador(monkeypatch, ambiente):
    with pytest.raises(ValueError, match="atalho"):
        central.pedir_troca_de_modo("offline")
    saidas = []
    central.SUPERVISOR.gerenciado = True
    monkeypatch.setenv("QUIRON_CENTRAL", "1")
    monkeypatch.setattr(central, "SAIR", saidas.append)
    c = TestClient(terminal.app)
    assert c.post("/api/sistema/modo", json={"modo": "lua"}, headers=H).status_code == 409
    assert c.post("/api/sistema/modo", json={"modo": "offline"}, headers=H).json()["ok"]
    assert central.ler_modo_pedido() == "offline"
    assert _esperar(lambda: saidas == [central.CODIGO_TROCA_MODO])


def test_lancador_religa_no_modo_pedido_e_depois_de_queda(ambiente):
    chamadas, pausas = [], []
    codigos = iter([central.CODIGO_TROCA_MODO, 1, 0])

    def chamar(cmd, env):
        chamadas.append((cmd, env.get("QUIRON_MODO"), env.get("QUIRON_CENTRAL")))
        if len(chamadas) == 1:
            central.arquivo_modo().parent.mkdir(parents=True, exist_ok=True)
            central.arquivo_modo().write_text("offline")
        return next(codigos)

    assert iniciar.rodar("normal", 8765, True, chamar=chamar, dormir=pausas.append) == 0
    assert [m for _, m, _ in chamadas] == [None, "offline", "offline"]  # trocou de modo e manteve após a queda
    assert all(cen == "1" for _, _, cen in chamadas) and pausas == [30]
    assert "--sem-navegador" not in chamadas[0][0] and "--sem-navegador" in chamadas[1][0]  # o navegador abre uma vez só
    assert "--central" in chamadas[0][0]


def test_inicio_automatico_fora_do_windows():
    assert central.inicio_automatico() == {"disponivel": False, "ligado": False} or os.name == "nt"
    c = TestClient(terminal.app)
    if os.name != "nt":
        assert c.post("/api/sistema/inicio_automatico", json={"ligar": True}, headers=H).status_code == 400


def test_versao_mostra_o_commit():
    v = central.versao()
    assert v["pasta"] and (v["codigo"] == "" or len(v["codigo"]) >= 7)


def test_bot_que_cai_ao_ligar_vira_erro_com_motivo_claro():
    sup = central.SUPERVISOR
    sup.gerenciado = True
    configurador.atualizar_env(CHAVES)
    sup.comando = [sys.executable, "-c", "print('telegram.error.InvalidToken: The token was rejected by the server.'); "
                   "import sys; sys.exit(1)"]
    sup.espera = 0.05
    sup.ligar()
    assert _esperar(lambda: sup.estado()["situacao"] == "erro")
    assert "recusou o token" in sup.estado()["ultimo_erro"]
    sup.desligar()
    assert central.motivo_da_queda("httpx.ConnectError: getaddrinfo failed").startswith("sem conexão")
    assert central.motivo_da_queda("Traceback...\nValueError: algo estranho\n") == "ValueError: algo estranho"


def test_lancador_porta_ocupada_e_quedas_seguidas():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert not iniciar.porta_livre(s.getsockname()[1])
    chamadas = []
    assert iniciar.rodar("normal", 8765, False, chamar=lambda cmd, env: chamadas.append(1) or 1, dormir=lambda s: None) == 1
    assert len(chamadas) == 3  # três quedas logo ao abrir: para e explica, em vez de religar para sempre
