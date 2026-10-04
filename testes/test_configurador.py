"""Tela de Configurações: .env preservado, proteção por código, salvar, testar chaves e descobrir o ID."""

import httpx
import pytest
from fastapi.testclient import TestClient

from quiron.configurador import app as cfg

MODELO = """# ===== cabeçalho =====
TELEGRAM_BOT_TOKEN=            # @BotFather
TELEGRAM_ALLOWED_USER_IDS=     # SEU id numérico
GEMINI_API_KEY=                # aistudio
LLM_PRINCIPAL=gemini/gemini-flash-latest   # confirme
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / ".env.example").write_text(MODELO, encoding="utf-8")
    caminho = tmp_path / ".env"
    monkeypatch.setattr(cfg, "caminho_env", lambda: caminho)
    return caminho


@pytest.fixture
def cliente(env):
    return TestClient(cfg.criar_app("codigo-secreto", 8766), headers={"X-Quiron-Codigo": "codigo-secreto"})


def test_atualizar_env_nasce_do_modelo_e_preserva_comentarios(env):
    cfg.atualizar_env({"GEMINI_API_KEY": "AIza-chave-123", "BRAPI_TOKEN": "tok"})
    texto = env.read_text(encoding="utf-8")
    assert "# ===== cabeçalho =====" in texto and "LLM_PRINCIPAL=gemini/gemini-flash-latest" in texto
    assert "GEMINI_API_KEY=AIza-chave-123" in texto and "# aistudio" in texto
    assert texto.rstrip().endswith("BRAPI_TOKEN=tok")
    assert cfg.ler_valores()["GEMINI_API_KEY"] == "AIza-chave-123"  # comentário não entra no valor
    cfg.atualizar_env({"GEMINI_API_KEY": "outra"})
    assert cfg.ler_valores()["GEMINI_API_KEY"] == "outra" and env.read_text(encoding="utf-8").count("GEMINI_API_KEY") == 1


def test_faltando_exige_id_numerico(env):
    cfg.atualizar_env({"TELEGRAM_BOT_TOKEN": "1:abc", "TELEGRAM_ALLOWED_USER_IDS": "@ricksonrkn", "GEMINI_API_KEY": "x"})
    assert cfg.faltando(cfg.ler_valores()) == ["TELEGRAM_ALLOWED_USER_IDS"]
    cfg.atualizar_env({"TELEGRAM_ALLOWED_USER_IDS": "7592218870"})
    assert cfg.faltando(cfg.ler_valores()) == []


def test_api_exige_codigo_e_host_local(env):
    app = cfg.criar_app("codigo-secreto", 8766)
    assert TestClient(app).get("/api/estado").status_code == 403
    assert TestClient(app, base_url="http://malicioso.com").get("/", headers={"X-Quiron-Codigo": "codigo-secreto"}).status_code == 403
    assert "Configurações" in TestClient(app).get("/").text


def test_salvar_nao_devolve_segredos_e_mantem_chave_em_branco(cliente, env):
    r = cliente.post("/api/salvar", json={"valores": {"TELEGRAM_BOT_TOKEN": "123:segredo-muito-longo",
                                                      "TELEGRAM_ALLOWED_USER_IDS": " 7592218870 ", "GEMINI_API_KEY": "AIzaXYZ12345"}})
    assert r.status_code == 200
    e = r.json()
    assert e["completo"] and "segredo-muito-longo" not in r.text
    gem = next(c for c in e["campos"] if c["chave"] == "GEMINI_API_KEY")
    assert gem["mascara"].endswith("2345") and gem["valor"] == ""
    cliente.post("/api/salvar", json={"valores": {"GEMINI_API_KEY": ""}})  # em branco = manter
    assert cfg.ler_valores()["GEMINI_API_KEY"] == "AIzaXYZ12345"
    assert cfg.ler_valores()["TELEGRAM_ALLOWED_USER_IDS"] == "7592218870"


def test_salvar_recusa_arroba_no_id(cliente):
    r = cliente.post("/api/salvar", json={"valores": {"TELEGRAM_ALLOWED_USER_IDS": "@ricksonrkn"}})
    assert r.status_code == 400 and "números" in r.json()["detail"]


def _transporte(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/getMe"):
        ok = "bom" in req.url.path
        return httpx.Response(200 if ok else 401, json={"ok": ok, "result": {"username": "QuironBot", "first_name": "Quíron"}})
    if req.url.path.endswith("/getUpdates"):
        return httpx.Response(200, json={"ok": True, "result": [
            {"message": {"from": {"id": 7592218870, "first_name": "Rick", "username": "ricksonrkn", "is_bot": False}}},
            {"message": {"from": {"id": 7592218870, "first_name": "Rick", "username": "ricksonrkn", "is_bot": False}}}]})
    if req.url.host == "api.groq.com":
        return httpx.Response(200 if req.headers["authorization"] == "Bearer gsk_bom" else 401, json={})
    return httpx.Response(404)


def test_testar_e_descobrir_id(cliente, monkeypatch):
    monkeypatch.setattr(cfg, "_cliente", lambda: httpx.Client(transport=httpx.MockTransport(_transporte)))
    assert cliente.post("/api/testar", json={"chave": "TELEGRAM_BOT_TOKEN", "valor": "1:bom"}).json()["bot"] == "QuironBot"
    assert not cliente.post("/api/testar", json={"chave": "TELEGRAM_BOT_TOKEN", "valor": "1:ruim"}).json()["ok"]
    assert cliente.post("/api/testar", json={"chave": "GROQ_API_KEY", "valor": "gsk_bom"}).json()["ok"]
    r = cliente.post("/api/descobrir_id", json={"token": "1:bom"}).json()
    assert r["ok"] and r["pessoas"] == [{"id": 7592218870, "nome": "Rick", "usuario": "ricksonrkn"}]


def test_concluir_so_para_quando_completo(cliente):
    parou = []
    app = cfg.criar_app("c", 8766, ao_concluir=lambda: parou.append(1))
    c = TestClient(app, headers={"X-Quiron-Codigo": "c"})
    assert not c.post("/api/concluir").json()["completo"]
    c.post("/api/salvar", json={"valores": {"TELEGRAM_BOT_TOKEN": "1:a", "TELEGRAM_ALLOWED_USER_IDS": "1", "GEMINI_API_KEY": "g"}})
    assert c.post("/api/concluir").json()["completo"]
