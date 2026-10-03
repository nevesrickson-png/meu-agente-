"""Teste funcional: sobe o servidor `quiron-biblioteca` como o Claude Code faz e usa as ferramentas."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from testes import livros_teste

RAIZ = Path(__file__).resolve().parents[1]


def test_ingerir_e_buscar_pelo_mcp(tmp_path):
    (tmp_path / "entrada").mkdir()
    livros_teste.pdf_texto(tmp_path / "entrada")
    cfg = json.loads((RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["quiron-biblioteca"]
    env = {**os.environ, "QUIRON_BIBLIOTECA": str(tmp_path), "QUIRON_EMBEDDINGS": "lexico"}
    params = StdioServerParameters(command=shutil.which(cfg["command"]), args=cfg["args"], cwd=str(RAIZ), env=env)

    async def rodar():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                nomes = {t.name for t in (await s.list_tools()).tools}
                ing = (await s.call_tool("ingerir", {})).content[0].text
                busca = (await s.call_tool("buscar", {"pergunta": "convexidade", "n": 1})).content[0].text
                return nomes, ing, busca

    nomes, ing, busca = asyncio.run(rodar())
    assert {"buscar", "estudar_tema", "debate_autores", "mapa_autor", "ficha", "conectar_conceitos", "pilula", "cobertura", "ingerir"} <= nomes
    assert "1 ingerido" in ing
    assert 'Fundamentos de Renda Fixa — Ana Teste, cap. "Capítulo 2 — Convexidade", p. 2' in busca
