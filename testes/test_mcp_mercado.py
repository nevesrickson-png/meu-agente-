"""Teste funcional: sobe o `quiron-mercado` como o Claude Code faz. Sem internet, as fontes aparecem como
indisponíveis — o importante aqui é o servidor responder e nunca quebrar."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parents[1]


def test_servidor_mercado_responde(tmp_path):
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-mercado"]
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path)}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                agenda = await s.call_tool("agenda", {"dias": 3})
                return nomes, agenda

    nomes, agenda = asyncio.run(rodar())
    assert {"cotacao", "watchlist", "taxas", "curva_juros", "macro", "focus", "agenda", "briefing", "companhia", "fundo_cotas", "damodaran"} <= nomes
    assert not agenda.is_error and agenda.content[0].text.startswith("## Agenda")
