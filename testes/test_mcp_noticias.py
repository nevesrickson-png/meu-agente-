"""Teste funcional: sobe o `quiron-noticias` como o Claude Code faz (sem internet, as fontes falham sem quebrar)."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parents[1]


def test_servidor_noticias_responde(tmp_path):
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-noticias"]
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path), "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                resp = await s.call_tool("redes_sociais", {"termo": "copom", "redes": ["youtube"]})
                return nomes, resp

    nomes, resp = asyncio.run(rodar())
    assert {"noticias", "principais", "alertas", "redes_sociais", "sentimento", "status_fontes"} <= nomes
    assert not resp.is_error and "## Redes sociais: copom" in resp.content[0].text
