"""Teste funcional: sobe o `quiron-academia` como o Claude Code faz (sem internet)."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parents[1]


def test_servidor_academia_responde(tmp_path):
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-academia"]
    env = {**os.environ, "QUIRON_DADOS": str(tmp_path), "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                edital = await s.call_tool("edital", {"busca": "come-cotas"})
                conf = await s.call_tool("configurar_estudo", {"data_prova": "15/03/2027", "horas_semana": 5})
                return nomes, edital, conf

    nomes, edital, conf = asyncio.run(rodar())
    assert {"trilha", "edital", "topico", "diagnostico_estudo", "plano_estudo", "configurar_estudo", "gerar_questoes",
            "questoes", "registrar_resposta", "materiais_gratuitos"} <= nomes
    assert not edital.is_error and "edital CFP" in edital.content[0].text
    assert "15/03/2027" in conf.content[0].text
