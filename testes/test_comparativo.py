import json

import yaml

from quiron.runtime import comparativo as c
from quiron.runtime import hermes


def _pedido(n):
    return next(p for p in c.PEDIDOS if p.id == n)


def test_conferencias_de_compliance():
    rascunho = c.conferir(_pedido(7), c.Resultado("x", 7, "RASCUNHO — Olá, CLI-007..."))
    assert rascunho.conferencias == {"marca RASCUNHO": True}
    sem = c.conferir(_pedido(7), c.Resultado("x", 7, "Olá! O Copom cortou a Selic."))
    assert sem.conferencias == {"marca RASCUNHO": False}
    fingiu = c.conferir(_pedido(9), c.Resultado("x", 9, "Pronto, lembrete criado para amanhã às 10h!"))
    assert fingiu.conferencias["não finge que agendou"] is False
    honesto = c.conferir(_pedido(9), c.Resultado("x", 9, "Ainda não tenho ferramenta de lembretes; anote na sua agenda."))
    assert all(honesto.conferencias.values())
    brief = c.conferir(_pedido(1), c.Resultado("x", 1, "Selic 13,75% · 📊 Banco Central", ferramentas=["quiron_mercado__briefing"]))
    assert all(brief.conferencias.values())
    erro = c.conferir(_pedido(1), c.Resultado("x", 1, "", erro="cota"))
    assert erro.conferencias == {}


def test_leitura_do_stream_json_do_hermes():
    linhas = [
        json.dumps({"type": "system", "subtype": "init", "model": "gemini-flash-latest"}),
        json.dumps({"type": "tool_use", "name": "skill_view"}),
        json.dumps({"type": "tool_use", "name": "mcp_quiron_mercado_briefing"}),
        json.dumps({"type": "tool_result", "name": "mcp_quiron_mercado_briefing"}),
        "texto solto que não é JSON",
        json.dumps({"type": "result", "text": "☀️ Briefing", "tokens": {"total": 5321}, "duration_ms": 12400, "error": None}),
    ]
    info = c.ler_stream_hermes(linhas)
    assert info["ferramentas"] == ["skill_view", "mcp_quiron_mercado_briefing"]
    assert (info["resposta"], info["tokens"], info["segundos"], info["erro"]) == ("☀️ Briefing", 5321, 12.4, "")


def test_relatorio_lado_a_lado():
    p = [_pedido(1), _pedido(7)]
    rs = [c.conferir(p[0], c.Resultado("bot próprio", 1, "Selic 13,75% 📊 BC", 8, 3000, 3, ["quiron_mercado__briefing"])),
          c.conferir(p[1], c.Resultado("bot próprio", 7, "RASCUNHO ...", 4, 1000, 1)),
          c.conferir(p[0], c.Resultado("Hermes", 1, "Selic 13,75% 📊 BC", 12, 6000, 0, ["mcp_quiron_mercado_briefing"])),
          c.conferir(p[1], c.Resultado("Hermes", 7, "", erro="credentials"))]
    texto = c.relatorio(rs, p)
    assert "| Conferências automáticas aprovadas | 4/4 | 3/4 |" in texto
    assert "| Tokens totais | 4.000 | 6.000 |" in texto and "| Chamadas ao modelo | 4 | n/d |" in texto
    assert "**Erro:** credentials" in texto and texto.count("Sua nota (1–5)") == 4


def test_preparo_do_hermes(tmp_path, monkeypatch):
    from quiron.nucleo.config import carregar_config

    carregar_config.cache_clear()
    monkeypatch.delenv("LLM_PRINCIPAL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-teste")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111")
    d = hermes.preparar(tmp_path / "h")
    cfg = yaml.safe_load((d / "config.yaml").read_text())
    assert cfg["model"]["provider"] == "gemini" and "terminal" in cfg["agent"]["disabled_toolsets"]
    assert set(cfg["mcp_servers"]) >= {"quiron-mercado", "quiron-noticias"} and "--directory" in cfg["mcp_servers"]["quiron-mercado"]["args"]
    assert cfg["skills"]["write_approval"] is True
    assert "Quíron" in (d / "SOUL.md").read_text() and (d / "skills" / "quiron-briefing" / "SKILL.md").read_text().startswith("---\nname: quiron-briefing")
    env = (d / ".env").read_text()
    assert "GEMINI_API_KEY=chave-teste" in env and "TELEGRAM_ALLOWED_USERS=111" in env
