"""Servidor MCP `quiron-sistema`: esqueleto e ferramentas de diagnóstico.

É o modelo para os demais servidores (biblioteca, mercado, notícias...): cada um é um servidor
(MCPServer, SDK oficial v2) independente de runtime, registrado no `.mcp.json` para uso pelo Claude Code.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

from quiron.nucleo import regras
from quiron.nucleo.anonimizador import Anonimizador, carregar_nomes_protegidos
from quiron.nucleo.cerebro import ARQUIVO_NOMES_PROTEGIDOS
from quiron.nucleo.config import carregar_config

mcp = MCPServer("quiron-sistema")


@mcp.tool()
def ping() -> str:
    """Confere se o Quíron está no ar. Responde 'pong' com data e hora de Brasília."""
    agora = datetime.now(ZoneInfo(carregar_config().fuso_horario))
    return f"pong — Quíron no ar ({agora:%d/%m/%Y %H:%M}, horário de Brasília)"


@mcp.tool()
def status() -> str:
    """Saúde do sistema: cérebro configurado, host, runtime e regras de mercado que precisam de conferência."""
    cfg = carregar_config()
    linhas = ["Status do Quíron", f"- Host: {cfg.host_atual} · Runtime do agente: {cfg.runtime_agente}", "- Cérebro:"]
    for modelo in cfg.modelos:
        linhas.append(f"  - {modelo}: {'chave configurada' if cfg.tem_chave_para(modelo) else 'SEM chave no .env'}")
    pendencias = regras.avisos()
    linhas.append("- Regras de mercado: " + ("todas verificadas" if not pendencias else f"{len(pendencias)} bloco(s) pendente(s)"))
    linhas += [f"  - {a}" for a in pendencias]
    return "\n".join(linhas)


@mcp.tool()
def previa_anonimizacao(texto: str) -> str:
    """Mostra como um texto sairia para o modelo de linguagem depois do anonimizador (nada é enviado)."""
    anon = Anonimizador(carregar_nomes_protegidos(ARQUIVO_NOMES_PROTEGIDOS))
    resultado = anon.anonimizar(texto)
    trocas = len(anon.mapa)
    return f"{resultado}\n\n({trocas} dado(s) substituído(s); o mapa fica só na memória e não é exibido.)"


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
