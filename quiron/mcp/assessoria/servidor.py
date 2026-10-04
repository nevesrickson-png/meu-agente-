"""Servidor MCP `quiron-assessoria`: ficha de planejamento do cliente (CLI-XXX) e LGPD (esquecer cliente).

Os planos em si (completo, aposentadoria, sucessão, tributário, proteção, PF × PJ) são análises da fila do
`quiron-analise`, que leem a ficha guardada aqui pelo código do cliente."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from quiron.servicos import lgpd
from quiron.servicos.planejamento import ficha as fichas

mcp = MCPServer(
    "quiron-assessoria",
    instructions=(
        "Ficha de planejamento dos clientes do Rickson, SEMPRE por código CLI-XXX (nunca nome, CPF, endereço ou "
        "telefone — se vierem, não guarde). Monte a ficha conversando: `campos_da_ficha` diz o que é preciso; grave aos "
        "poucos com `salvar_ficha` (mescla com o que já existe) e mostre as pendências. Com a ficha pronta, peça o plano "
        "com quiron_analise `analisar('planejamento_completo', {'cliente': 'CLI-XXX'})` (ou aposentadoria, sucessao, "
        "tributario, protecao, empresario). `esquecer_cliente` apaga tudo do cliente (LGPD) e pede confirmação."
    ),
)


@mcp.tool()
def campos_da_ficha() -> str:
    """Campos da ficha de planejamento e os valores aceitos."""
    return fichas.campos()


@mcp.tool()
def salvar_ficha(cliente: str, dados: dict[str, Any], substituir: bool = False) -> str:
    """Cria ou atualiza a ficha do cliente (CLI-XXX). `dados` usa os nomes de campos_da_ficha; mescla com o que já
    existe (listas enviadas substituem as antigas). substituir=true recomeça a ficha do zero."""
    try:
        f = fichas.salvar({**dados, "cliente": cliente}, substituir)
    except (ValueError, TypeError) as e:
        return f"Não salvei: {e}"
    return fichas.descrever(f)


@mcp.tool()
def ver_ficha(cliente: str) -> str:
    """Resumo da ficha do cliente com o que falta preencher."""
    try:
        return fichas.descrever(fichas.carregar(cliente))
    except ValueError as e:
        return str(e)


@mcp.tool()
def fichas_de_clientes() -> str:
    """Lista os clientes com ficha (código, idade, ocupação, patrimônio, data da última atualização)."""
    from quiron.servicos.analise.relatorio import brl

    itens = fichas.listar()
    return "\n".join(f"- {f.cliente}: {f.idade} anos, {f.ocupacao or '?'}, patrimônio {brl(f.patrimonio_total)} "
                     f"(atualizada {f.atualizado_em[:10]})" for f in itens) or "Nenhuma ficha ainda."


@mcp.tool()
def esquecer_cliente(cliente: str) -> str:
    """LGPD: apaga TUDO sobre o cliente (ficha, carteiras, relatórios, conversas e memória que citam o código)."""
    try:
        return lgpd.esquecer_cliente(cliente).descrever()
    except ValueError as e:
        return str(e)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
