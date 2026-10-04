"""Conexão com os servidores MCP do Quíron (os mesmos do `.mcp.json`), para o runtime "bot próprio".

Sobe cada servidor por stdio, lista as ferramentas e as expõe no formato de "function calling" do modelo.
Nome de cada ferramenta para o modelo: `<servidor>__<ferramenta>` (ex.: `quiron-mercado__briefing`).
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from quiron.nucleo.config import RAIZ

SEPARADOR = "__"


def ler_mcp_json(caminho: Path | None = None) -> dict[str, dict]:
    return json.loads((caminho or RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


@dataclass
class ConexaoMCP:
    servidores: list[str] | None = None  # None = todos do .mcp.json
    _pilha: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)
    _sessoes: dict[str, ClientSession] = field(default_factory=dict, init=False)
    ferramentas: list[dict[str, Any]] = field(default_factory=list, init=False)
    falhas: dict[str, str] = field(default_factory=dict, init=False)

    async def __aenter__(self) -> "ConexaoMCP":
        cfg = ler_mcp_json()
        for nome, s in cfg.items():
            if self.servidores and nome not in self.servidores:
                continue
            params = StdioServerParameters(command=shutil.which(s["command"]) or s["command"], args=s.get("args", []),
                                           cwd=str(RAIZ), env={**os.environ, **s.get("env", {})})
            try:
                leitura, escrita = await self._pilha.enter_async_context(stdio_client(params))
                sessao = await self._pilha.enter_async_context(ClientSession(leitura, escrita))
                await sessao.initialize()
                self._sessoes[nome] = sessao
                for t in (await sessao.list_tools()).tools:
                    self.ferramentas.append({
                        "type": "function",
                        "function": {
                            "name": f"{nome}{SEPARADOR}{t.name}".replace("-", "_"),
                            "description": (t.description or "")[:1000],
                            "parameters": t.input_schema or {"type": "object", "properties": {}},
                        },
                    })
            except Exception as e:  # noqa: BLE001 — um servidor com problema não impede os outros
                self.falhas[nome] = f"{type(e).__name__}: {e}"
        return self

    async def __aexit__(self, *exc) -> None:
        await self._pilha.aclose()

    def _localizar(self, nome_funcao: str) -> tuple[ClientSession, str]:
        servidor, _, ferramenta = nome_funcao.partition(SEPARADOR)
        for nome, sessao in self._sessoes.items():
            if nome.replace("-", "_") == servidor:
                return sessao, ferramenta
        raise KeyError(f"servidor desconhecido: {servidor}")

    async def chamar(self, nome_funcao: str, argumentos: dict[str, Any]) -> str:
        try:
            sessao, ferramenta = self._localizar(nome_funcao)
            r = await sessao.call_tool(ferramenta, argumentos)
        except Exception as e:  # noqa: BLE001 — o modelo recebe o erro e decide o que fazer
            return f"ERRO ao chamar {nome_funcao}: {type(e).__name__}: {str(e)[:300]}"
        texto = "\n".join(getattr(c, "text", "") for c in r.content)
        return ("ERRO: " if r.is_error else "") + texto
