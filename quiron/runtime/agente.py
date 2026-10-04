"""Laço do agente do runtime "bot próprio": persona + skills + ferramentas MCP + cérebro (Gemini → Groq).

Independente de canal: o Telegram e o modo de linha de comando usam a mesma classe `Agente`.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from quiron.nucleo import cerebro
from quiron.nucleo.config import PASTA_AGENTE, Config, carregar_config
from quiron.runtime.ferramentas_mcp import ConexaoMCP

MAX_PASSOS = 8  # limite de idas e vindas com ferramentas por pergunta
PASTA_SKILLS = PASTA_AGENTE / "skills"

FERRAMENTA_SKILL = {
    "type": "function",
    "function": {
        "name": "ler_skill",
        "description": "Lê as instruções completas de uma skill do Quíron (ex.: briefing, noticias, biblioteca-estudo). "
                       "Leia a skill indicada ANTES de responder pedidos desse tipo.",
        "parameters": {"type": "object", "properties": {"nome": {"type": "string"}}, "required": ["nome"]},
    },
}


def indice_skills(pasta: Path = PASTA_SKILLS) -> str:
    linhas = []
    for arq in sorted(pasta.glob("*.md")):
        quando = re.search(r"\*\*Quando usar:\*\*\s*(.+)", arq.read_text(encoding="utf-8"))
        linhas.append(f"- `{arq.stem}`: {quando.group(1).strip() if quando else ''}")
    return "\n".join(linhas)


def prompt_sistema(agora: datetime | None = None) -> str:
    agora = agora or datetime.now(ZoneInfo("America/Sao_Paulo"))
    persona = (PASTA_AGENTE / "persona.md").read_text(encoding="utf-8")
    return (
        f"{persona}\n\n## Agora\n{agora:%A, %d/%m/%Y %H:%M} (horário de Brasília).\n\n"
        "## Como trabalhar\n"
        "- Use as ferramentas para qualquer dado (mercado, notícias, livros). Nunca responda número de memória.\n"
        "- Antes de responder um pedido coberto por uma skill, chame `ler_skill` e siga as instruções.\n"
        "- Respostas curtas, para ler no celular. Português do Brasil.\n\n"
        f"## Skills disponíveis\n{indice_skills()}\n"
    )


@dataclass
class Registro:
    """O que aconteceu numa resposta (usado no comparativo e nos logs)."""

    pergunta: str
    resposta: str = ""
    ferramentas: list[str] = field(default_factory=list)
    modelos: list[str] = field(default_factory=list)
    segundos: float = 0.0
    erro: str = ""
    tokens: int = 0


class Agente:
    def __init__(self, conexao: ConexaoMCP, config: Config | None = None):
        self.conexao = conexao
        self.config = config or carregar_config()

    async def responder(self, pergunta: str, historico: list[dict[str, Any]] | None = None) -> Registro:
        reg = Registro(pergunta)
        inicio = time.time()
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": prompt_sistema()}, *(historico or []),
                                           {"role": "user", "content": pergunta}]
        ferramentas = [FERRAMENTA_SKILL, *self.conexao.ferramentas]
        try:
            for _ in range(MAX_PASSOS):
                turno = await asyncio.to_thread(cerebro.conversar, mensagens, ferramentas, config=self.config)
                reg.modelos.append(turno.modelo)
                reg.tokens += getattr(turno, "tokens", 0)
                mensagens.append(turno.mensagem)
                if not turno.chamadas:
                    reg.resposta = turno.texto.strip()
                    break
                for c in turno.chamadas:
                    reg.ferramentas.append(c["nome"])
                    resultado = self._ler_skill(c["argumentos"]) if c["nome"] == "ler_skill" else \
                        await self.conexao.chamar(c["nome"], c["argumentos"])
                    mensagens.append({"role": "tool", "tool_call_id": c["id"], "name": c["nome"], "content": resultado[:12000]})
            else:
                reg.resposta = "Não consegui concluir em poucas etapas. Pode reformular ou dividir o pedido?"
        except cerebro.CerebroIndisponivel as e:
            reg.erro = str(e)
            reg.resposta = "O cérebro está indisponível agora (limite gratuito ou chave). Tente de novo em alguns minutos."
        reg.segundos = round(time.time() - inicio, 1)
        return reg

    @staticmethod
    def _ler_skill(args: dict[str, Any]) -> str:
        nome = re.sub(r"[^a-z0-9\-]", "", str(args.get("nome", "")).lower().removeprefix("quiron-"))
        arq = PASTA_SKILLS / f"{nome}.md"
        if not arq.exists():
            return f"Skill '{nome}' não existe. Disponíveis: {', '.join(p.stem for p in PASTA_SKILLS.glob('*.md'))}"
        return arq.read_text(encoding="utf-8")


async def _pergunta_unica(pergunta: str) -> Registro:
    async with ConexaoMCP() as conexao:
        return await Agente(conexao).responder(pergunta)


def main() -> None:
    """`uv run quiron-agente -q "faça meu briefing"` — o agente do bot próprio no terminal (sem Telegram)."""
    import argparse
    import json

    p = argparse.ArgumentParser(description="Agente Quíron (runtime bot próprio)")
    p.add_argument("-q", "--pergunta", required=True)
    p.add_argument("--json", action="store_true", help="saída em JSON (resposta, ferramentas, tempo)")
    a = p.parse_args()
    reg = asyncio.run(_pergunta_unica(a.pergunta))
    if a.json:
        print(json.dumps(reg.__dict__, ensure_ascii=False))
    else:
        print(reg.resposta)
        print(f"\n— {reg.segundos}s · ferramentas: {', '.join(reg.ferramentas) or 'nenhuma'} · modelo: {', '.join(sorted(set(reg.modelos)))}")
        if reg.erro:
            print(reg.erro)
