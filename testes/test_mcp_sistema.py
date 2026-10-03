"""Teste funcional: sobe o servidor MCP de verdade (stdio, como o Claude Code faz) e chama as ferramentas."""

import asyncio
import json
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parents[1]


def _parametros_do_mcp_json() -> StdioServerParameters:
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-sistema"]
    return StdioServerParameters(command=shutil.which(cfg["command"]) or cfg["command"], args=cfg["args"], cwd=str(RAIZ))


async def _chamar(ferramentas: dict[str, dict]) -> tuple[list[str], dict[str, str]]:
    async with stdio_client(_parametros_do_mcp_json()) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as sessao:
            await sessao.initialize()
            nomes = [t.name for t in (await sessao.list_tools()).tools]
            respostas = {}
            for nome, args in ferramentas.items():
                r = await sessao.call_tool(nome, args)
                assert not r.is_error, r
                respostas[nome] = r.content[0].text
            return nomes, respostas


def test_servidor_mcp_responde_como_no_claude_code():
    nomes, r = asyncio.run(
        _chamar({
            "ping": {},
            "status": {},
            "previa_anonimizacao": {"texto": "Cliente Odete Pires, tel (11) 98765-4321"},
        })
    )
    assert {"ping", "status", "previa_anonimizacao"} <= set(nomes)
    assert r["ping"].startswith("pong — Quíron no ar")
    assert "Status do Quíron" in r["status"] and "Regras de mercado" in r["status"]
    assert "Odete" not in r["previa_anonimizacao"] and "98765" not in r["previa_anonimizacao"]
