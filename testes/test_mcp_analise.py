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
                cart = await s.call_tool("ler_carteira", {"texto": "CDB 110% CDI R$ 50 mil\nLCA 94% CDI R$ 30 mil",
                                                          "perfil": "conservador", "cliente": "CLI-001"})
                return nomes, tipos, conta, cart

    nomes, tipos, conta, cart = asyncio.run(rodar())
    assert {"tipos_de_analise", "analisar", "situacao_analise", "relatorios", "ler_relatorio", "calcular",
            "calculadoras_disponiveis", "ler_carteira"} <= nomes
    assert "renda_fixa_comparativo" in tipos.content[0].text and "carteira_diagnostico" in tipos.content[0].text
    texto = cart.content[0].text  # sem internet: leitura por regras, carteira guardada com id
    assert "CLI-001 · perfil conservador · R$ 80.000,00 em 2 posições" in texto and "carteira_id" in texto
    assert len(list((tmp_path / "carteiras").glob("CART-*.json"))) == 1
    assert "R$ 3.085,84" in conta.content[0].text and "Memória de cálculo" in conta.content[0].text
