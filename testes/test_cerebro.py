import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.cerebro import CerebroIndisponivel, perguntar


from quiron.nucleo.config import Config, carregar_config

CFG = Config(gemini_api_key="chave-falsa", groq_api_key="chave-falsa")


def test_envia_a_pergunta_pelo_litellm():
    # mock_response faz o LiteLLM real devolver a resposta sem ir à internet
    r = perguntar("Explique duration.", sistema="Seja breve.", config=CFG, mock_response="Duration é...")
    assert r.enviado == [
        {"role": "system", "content": "Seja breve."},
        {"role": "user", "content": "Explique duration."},
    ]
    assert r.texto == "Duration é..." and r.modelo == CFG.llm_principal


def test_cai_para_a_reserva_quando_o_principal_falha(monkeypatch):
    llm = cerebro._litellm()
    original = llm.completion

    def completion(**kw):
        if kw["model"].startswith("gemini/"):
            raise RuntimeError("cota esgotada")
        return original(**kw)

    monkeypatch.setattr(llm, "completion", completion)
    r = perguntar("Explique duration.", config=CFG, mock_response="Duration é...")
    assert r.modelo == CFG.llm_reserva
    assert r.texto == "Duration é..."
    assert any("cota esgotada" in f for f in r.falhas)


def test_pula_modelo_sem_chave_e_avisa_quando_nada_responde():
    sem_chaves = Config()
    with pytest.raises(CerebroIndisponivel, match="sem chave"):
        perguntar("oi", config=sem_chaves)
    resultados = cerebro.testar_conexao(sem_chaves)
    assert [ok for _, ok, _ in resultados] == [False, False]


def test_modelos_vem_do_env(tmp_path, monkeypatch):
    for v in ("LLM_PRINCIPAL", "LLM_RESERVA", "LLM_ALTERNATIVOS", "GEMINI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    env = tmp_path / ".env"
    env.write_text("LLM_PRINCIPAL=groq/modelo-x   # comentário\nLLM_RESERVA=gemini/modelo-y\nLLM_ALTERNATIVOS=\nGEMINI_API_KEY=abc\n")
    carregar_config.cache_clear()
    try:
        cfg = carregar_config(str(env))
        assert cfg.modelos == ["groq/modelo-x", "gemini/modelo-y"]
        assert cfg.tem_chave_para("gemini/modelo-y")
    finally:
        carregar_config.cache_clear()
        for v in ("LLM_PRINCIPAL", "LLM_RESERVA", "LLM_ALTERNATIVOS", "GEMINI_API_KEY"):  # o load_dotenv gravou no ambiente
            monkeypatch.delenv(v, raising=False)


@pytest.mark.online
def test_conexao_real():
    """Rode no seu PC com `uv run pytest -m online` (usa as chaves do .env)."""
    carregar_config.cache_clear()
    resultados = cerebro.testar_conexao()
    assert any(ok for _, ok, _ in resultados), resultados


def test_conversar_com_ferramentas_via_litellm():
    """O LiteLLM real com resposta simulada contendo chamada de ferramenta."""
    import litellm

    resposta = litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "x1", "type": "function", "function": {"name": "quiron_sistema__ping", "arguments": "{}"},
         "provider_specific_fields": {"thought_signature": "abc"}}]}}])
    t = cerebro.conversar([{"role": "user", "content": "ping"}],
                          [{"type": "function", "function": {"name": "quiron_sistema__ping", "parameters": {"type": "object", "properties": {}}}}],
                          config=CFG, mock_response=resposta)
    assert t.chamadas == [{"id": "x1", "nome": "quiron_sistema__ping", "argumentos": {}}]
    assert t.mensagem["role"] == "assistant" and t.mensagem["tool_calls"][0]["id"] == "x1"
    assert "thought_signature" in str(t.mensagem)  # preservada para o Gemini 3


def test_fila_de_modelos_gratis_e_pausa_por_cota(monkeypatch):
    cfg = Config(gemini_api_key="x", groq_api_key="x", llm_alternativos=("gemini/alt-1",))
    assert cfg.modelos == [cfg.llm_principal, "gemini/alt-1", cfg.llm_reserva]
    llm = cerebro._litellm()
    original = llm.completion
    chamados = []

    def completion(**kw):
        chamados.append(kw["model"])
        if kw["model"] == cfg.llm_principal:
            raise RuntimeError('429 RESOURCE_EXHAUSTED quota "retryDelay": "3600s"')
        return original(**kw)

    monkeypatch.setattr(llm, "completion", completion)
    monkeypatch.setattr(cerebro, "_PAUSA", {})
    monkeypatch.setattr(cerebro, "_em_pausa", lambda m: cerebro._PAUSA.get(m, 0) > __import__("time").time())
    assert perguntar("oi", config=cfg, mock_response="ok").modelo == "gemini/alt-1"
    assert cerebro._PAUSA[cfg.llm_principal] > 0
    chamados.clear()
    # na segunda vez nem tenta o modelo sem cota (o teste usa mock_response, então força a checagem)
    assert cerebro._em_pausa(cfg.llm_principal)
