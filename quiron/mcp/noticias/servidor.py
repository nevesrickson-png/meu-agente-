"""Servidor MCP `quiron-noticias`: notícias por RSS/feeds oficiais e redes sociais por APIs oficiais."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.noticias import consultas

mcp = MCPServer(
    "quiron-noticias",
    instructions=(
        "Notícias (RSS de portais e órgãos oficiais) e redes sociais (Bluesky, Reddit, YouTube — sem X/Twitter). "
        "Resuma com base SOMENTE nas manchetes e posts devolvidos, citando fonte e horário e mantendo os links. "
        "O 'tom' é calculado por léxico; trate como indicação. Siga agente/skills/noticias.md."
    ),
)


@mcp.tool()
def noticias(termo: str | None = None, horas: int = 24, limite: int = 15, grupo: str | None = None) -> str:
    """Notícias recentes. termo: tema (juros, inflacao, cambio, bolsa, fiscal, copom, banco_central, fed, renda_fixa,
    fundos_previdencia, commodities, tributacao, regulacao, internacional, cripto, empresas), ticker (PETR4)
    ou palavra livre. grupo opcional: brasil, global, oficiais."""
    return consultas.noticias(termo, horas, limite, grupo)


@mcp.tool()
def principais(horas: int = 6) -> str:
    """Principais notícias agora (as que mais portais repetem e as com palavras-alerta primeiro)."""
    return consultas.top(horas)


@mcp.tool()
def alertas(horas: int = 24) -> str:
    """Notícias com palavras-alerta (fato relevante, recuperação judicial, rebaixamento, Copom…)."""
    return consultas.alertas(horas)


@mcp.tool()
def redes_sociais(termo: str, redes: list[str] | None = None) -> str:
    """O que Bluesky, Reddit e YouTube estão dizendo sobre um tema ou ticker, com tom por rede.
    redes opcional: ["bluesky", "reddit", "youtube"]."""
    return consultas.redes_sociais(termo, redes)


@mcp.tool()
def sentimento(termo: str, horas: int = 48) -> str:
    """Resumo de sentimento de um tema/ativo: tom das manchetes por fonte e das redes."""
    return consultas.sentimento_tema(termo, horas)


@mcp.tool()
def status_fontes() -> str:
    """Testa todas as fontes de notícias agora e mostra quais redes sociais têm chave configurada."""
    return consultas.status_fontes()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
