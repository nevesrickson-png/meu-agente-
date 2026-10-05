"""Servidor MCP `quiron-conteudo`: pautas, roteiros (reels, YouTube, carrossel, fio, artigo), banco de ideias e
conferência de textos — com compliance, números conferidos, disclaimer e créditos automáticos. Tudo sai como RASCUNHO."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.nucleo.cerebro import CerebroIndisponivel
from quiron.servicos.conteudo import gerador, ideias

mcp = MCPServer(
    "quiron-conteudo",
    instructions=(
        "Conteúdo público do Rickson (Instagram, YouTube, LinkedIn, Threads, Bluesky, newsletter — sem X/Twitter). "
        "`pautas` sugere temas a partir de notícias, Banco Central, radar regulatório, agenda e biblioteca; `roteiro` escreve "
        "a peça já revisada (compliance, números conferidos, disclaimer, créditos). Mostre o resultado como veio: é RASCUNHO "
        "para ele revisar. Para texto escrito por ele, use `conferir_publicacao`."
    ),
)


@mcp.tool()
def pautas(tema: str = "", quantidade: int = 5) -> str:
    """Sugere pautas (título, gancho, ângulo, formato, por que agora, fontes)."""
    try:
        p, origem = gerador.gerar_pautas(tema, max(1, min(int(quantidade), 8)))
    except CerebroIndisponivel as e:
        return f"Sem IA no momento: {str(e)[:150]}"
    return gerador.texto_pautas(p, origem)


@mcp.tool()
def roteiro(tema: str, formato: str = "carrossel") -> str:
    """Escreve a peça: formato = reels | youtube | carrossel | fio | artigo. `tema` pode ser '#12' (ideia do banco)."""
    try:
        return gerador.gerar_peca(tema, formato).entrega()
    except (ValueError, CerebroIndisponivel) as e:
        return f"Não escrevi: {str(e)[:200]}"


@mcp.tool()
def conferir_publicacao(texto: str, tema: str = "") -> str:
    """Confere um texto do Rickson: compliance, números (com o tema, compara com as fontes) e disclaimer sugerido."""
    return gerador.conferir_texto(texto, tema)


@mcp.tool()
def guardar_ideia(titulo: str, angulo: str = "", formato: str = "") -> str:
    """Guarda uma ideia no banco de ideias."""
    try:
        return "Guardada: " + ideias.criar(titulo, angulo, formato).descrever()
    except ValueError as e:
        return str(e)


@mcp.tool()
def banco_de_ideias(busca: str = "", situacao: str = "") -> str:
    """Ideias e rascunhos (busca por palavra; situacao = ideia | rascunho | publicado | descartada)."""
    itens = ideias.listar(busca, situacao)
    return "\n".join(i.descrever() for i in itens) or "Banco de ideias vazio."


@mcp.tool()
def mudar_situacao_ideia(numero: int, situacao: str) -> str:
    """Marca a ideia #numero como ideia | rascunho | publicado | descartada."""
    try:
        return ideias.atualizar(numero, situacao=situacao).descrever()
    except ValueError as e:
        return str(e)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
