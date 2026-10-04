"""Teste funcional: sobe o `quiron-analise` como o Claude Code faz (sem internet)."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parents[1]


def test_servidor_analise_responde(tmp_path):
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-analise"]
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path), "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                tipos = await s.call_tool("tipos_de_analise", {})
                conta = await s.call_tool("calcular", {"nome": "financiamento",
                                                       "parametros": {"valor": 300000, "taxa_am": 1, "meses": 360}})
                return nomes, tipos, conta

    nomes, tipos, conta = asyncio.run(rodar())
    assert {"tipos_de_analise", "analisar", "situacao_analise", "relatorios", "ler_relatorio", "calcular",
            "calculadoras_disponiveis"} <= nomes
    assert "renda_fixa_comparativo" in tipos.content[0].text
    assert "R$ 3.085,84" in conta.content[0].text and "Memória de cálculo" in conta.content[0].text
