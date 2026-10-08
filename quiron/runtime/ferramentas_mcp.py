"""Conexão com os servidores MCP do Quíron (os mesmos do `.mcp.json`), para o runtime "bot próprio".

Sobe cada servidor por stdio, lista as ferramentas e as expõe no formato de "function calling" do modelo.
Nome de cada ferramenta para o modelo: `<servidor>__<ferramenta>` (ex.: `quiron-mercado__briefing`).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from quiron.nucleo.config import RAIZ

SEPARADOR = "__"
INICIO_MAX_S = float(os.environ.get("QUIRON_MCP_INICIO_S", "90"))  # tempo máximo para um servidor MCP subir


def ler_mcp_json(caminho: Path | None = None) -> dict[str, dict]:
    return json.loads((caminho or RAIZ / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def _enxuto(esquema: dict[str, Any] | None) -> dict[str, Any]:
    """Offline: modelo pequeno se perde em parâmetros opcionais (ex.: põe um filtro de bloco à toa) — só os obrigatórios."""
    esquema = esquema or {}
    obrig = list(esquema.get("required") or [])
    props = {k: v for k, v in (esquema.get("properties") or {}).items() if k in obrig}
    return {"type": "object", "properties": props, "required": obrig}


def _comando(s: dict[str, Any]) -> tuple[str, list[str]]:
    """Comando do servidor. `uv run <script>` vira o script direto da mesma .venv: o lançador (`uv run quiron`) já
    sincronizou o ambiente, e cada `uv run` deixava um processo `uv` parado na memória (~10 MB × 10) e somava 0,1–0,6 s
    por servidor. Sem o script (ou com QUIRON_MCP_VIA_UV=1), continua pelo uv."""
    cmd, args = s["command"], list(s.get("args", []))
    if Path(cmd).stem.lower() == "uv" and args[:1] == ["run"] and os.environ.get("QUIRON_MCP_VIA_UV") != "1":
        direto = shutil.which(args[-1], path=str(Path(sys.executable).parent))  # .venv/bin ou .venv\Scripts (.exe)
        if direto:
            return direto, []
    return shutil.which(cmd) or cmd, args


@dataclass
class ConexaoMCP:
    servidores: list[str] | None = None  # None = todos do .mcp.json
    _pilha: AsyncExitStack = field(default_factory=AsyncExitStack, init=False)
    _sessoes: dict[str, ClientSession] = field(default_factory=dict, init=False)
    ferramentas: list[dict[str, Any]] = field(default_factory=list, init=False)
    falhas: dict[str, str] = field(default_factory=dict, init=False)

    async def __aenter__(self) -> "ConexaoMCP":
        from quiron.nucleo import offline

        cfg = ler_mcp_json()
        permitidas = offline.servidores() if offline.ativo() else {}  # offline: servidores leves e poucas ferramentas
        sessoes: dict[str, ClientSession] = {}
        for nome, s in cfg.items():
            if self.servidores and nome not in self.servidores:
                continue
            if offline.ativo() and nome not in permitidas:
                continue
            comando, args = _comando(s)
            params = StdioServerParameters(command=comando, args=args, cwd=str(RAIZ), env={**os.environ, **s.get("env", {})})
            try:  # só abre os processos aqui (rápido); a apresentação de cada um corre em paralelo logo abaixo
                leitura, escrita = await self._pilha.enter_async_context(stdio_client(params))
                sessoes[nome] = await self._pilha.enter_async_context(ClientSession(leitura, escrita))
            except Exception as e:  # noqa: BLE001 — um servidor com problema não impede os outros
                self.falhas[nome] = f"{type(e).__name__}: {e}"

        async def subir(sessao: ClientSession):
            # servidor que trava ao subir não pode prender o bot/Terminal para sempre
            await asyncio.wait_for(sessao.initialize(), INICIO_MAX_S)
            return (await asyncio.wait_for(sessao.list_tools(), INICIO_MAX_S)).tools

        # 10 servidores um depois do outro levavam ~12 s; juntos, ~3 s (a ordem das ferramentas é a do .mcp.json)
        respostas = await asyncio.gather(*(subir(sessao) for sessao in sessoes.values()), return_exceptions=True)
        for (nome, sessao), resposta in zip(sessoes.items(), respostas):
            if isinstance(resposta, BaseException):
                self.falhas[nome] = f"{type(resposta).__name__}: {resposta}"
                continue
            self._sessoes[nome] = sessao
            for t in resposta:
                if permitidas.get(nome) and t.name not in permitidas[nome]:
                    continue
                self.ferramentas.append({
                    "type": "function",
                    "function": {
                        "name": f"{nome}{SEPARADOR}{t.name}".replace("-", "_"),
                        "description": (t.description or "")[:1000],
                        "parameters": _enxuto(t.input_schema) if permitidas else (t.input_schema or {"type": "object", "properties": {}}),
                    },
                })
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
        limite = float(os.environ.get("QUIRON_TIMEOUT_FERRAMENTA", "180"))
        try:
            sessao, ferramenta = self._localizar(nome_funcao)
            r = await asyncio.wait_for(sessao.call_tool(ferramenta, argumentos), limite)
        except TimeoutError:  # fonte lenta/travada não pode prender a conversa (e o bot inteiro, que atende em fila)
            return (f"ERRO: {nome_funcao} não respondeu em {limite:.0f} s (fonte lenta ou fora do ar). Diga isso ao Rickson "
                    "e ofereça tentar mais tarde ou pedir como análise em segundo plano.")
        except Exception as e:  # noqa: BLE001 — o modelo recebe o erro e decide o que fazer
            return f"ERRO ao chamar {nome_funcao}: {type(e).__name__}: {str(e)[:300]}"
        texto = "\n".join(getattr(c, "text", "") for c in r.content)
        return ("ERRO: " if r.is_error else "") + texto
