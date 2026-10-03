import pytest

from quiron.nucleo import cerebro
from quiron.nucleo.cerebro import CerebroIndisponivel, perguntar


from quiron.nucleo.config import Config, carregar_config

CFG = Config(gemini_api_key="chave-falsa", groq_api_key="chave-falsa")


def test_anonimiza_antes_de_enviar_e_restaura_na_resposta():
    # mock_response faz o LiteLLM real devolver a resposta sem ir à internet
    r = perguntar(
        "A cliente Odete Pires (CPF 529.982.247-25, odete@exemplo.com) quer previdência.",
        config=CFG,
        nomes_protegidos=[],
        mock_response="Para [NOME_1], sugiro PGBL. Confirme o e-mail [EMAIL_1].",
    )
    enviado = r.enviado[-1]["content"]
    assert "Odete" not in enviado and "529.982" not in enviado and "odete@" not in enviado
    assert "[NOME_1]" in enviado and "[CPF_1]" in enviado and "[EMAIL_1]" in enviado
    assert r.texto == "Para Odete Pires, sugiro PGBL. Confirme o e-mail odete@exemplo.com."
    assert r.modelo == CFG.llm_principal


def test_cai_para_a_reserva_quando_o_principal_falha(monkeypatch):
    llm = cerebro._litellm()
    original = llm.completion

    def completion(**kw):
        if kw["model"].startswith("gemini/"):
            raise RuntimeError("cota esgotada")
        return original(**kw)

    monkeypatch.setattr(llm, "completion", completion)
    r = perguntar("Explique duration.", config=CFG, nomes_protegidos=[], mock_response="Duration é...")
    assert r.modelo == CFG.llm_reserva
    assert r.texto == "Duration é..."
    assert any("cota esgotada" in f for f in r.falhas)


def test_pula_modelo_sem_chave_e_avisa_quando_nada_responde():
    sem_chaves = Config()
    with pytest.raises(CerebroIndisponivel, match="sem chave"):
        perguntar("oi", config=sem_chaves, nomes_protegidos=[])
    resultados = cerebro.testar_conexao(sem_chaves)
    assert [ok for _, ok, _ in resultados] == [False, False]


def test_modelos_vem_do_env(tmp_path, monkeypatch):
    for v in ("LLM_PRINCIPAL", "LLM_RESERVA", "GEMINI_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    env = tmp_path / ".env"
    env.write_text("LLM_PRINCIPAL=groq/modelo-x   # comentário\nLLM_RESERVA=gemini/modelo-y\nGEMINI_API_KEY=abc\n")
    carregar_config.cache_clear()
    try:
        cfg = carregar_config(str(env))
        assert cfg.modelos == ["groq/modelo-x", "gemini/modelo-y"]
        assert cfg.tem_chave_para("gemini/modelo-y")
    finally:
        carregar_config.cache_clear()


@pytest.mark.online
def test_conexao_real():
    """Rode no seu PC com `uv run pytest -m online` (usa as chaves do .env)."""
    carregar_config.cache_clear()
    resultados = cerebro.testar_conexao()
    assert any(ok for _, ok, _ in resultados), resultados
