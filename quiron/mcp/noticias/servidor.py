"""Servidor MCP `quiron-noticias`: notícias por RSS/feeds oficiais e redes sociais por APIs oficiais."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.cartas import consultas as cartas
from quiron.servicos.noticias import consultas

mcp = MCPServer(
    "quiron-noticias",
    instructions=(
        "Notícias (RSS de portais e órgãos oficiais), cartas de gestores e redes sociais (Bluesky, Reddit, YouTube — sem X/Twitter). "
        "Resuma com base SOMENTE nas manchetes e posts devolvidos, citando fonte e horário e mantendo os links. "
        "O 'tom' é calculado por léxico; trate como indicação. Siga agente/skills/noticias.md."
    ),
)


@mcp.tool()
def noticias(termo: str | None = None, horas: int = 24, limite: int = 15, grupo: str | None = None) -> str:
    """Notícias recentes. termo: tema (juros, inflacao, cambio, bolsa, fiscal, copom, banco_central, fed, renda_fixa,
    fundos_previdencia, commodities, tributacao, regulacao, internacional, cripto, empresas), ticker (PETR4)
    ou palavra livre. grupo opcional: brasil, global, asia, oficiais, setores_br, setores_global."""
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


@mcp.tool()
def cartas_gestores(gestora: str | None = None, dias: int = 60, tipo: str | None = None) -> str:
    """Cartas de gestores publicadas recentemente (sites públicos de ~140 gestoras do Brasil e do mundo).
    gestora opcional (ex.: "Verde", "Dynamo") mostra as últimas dela; tipo opcional: gestora (Brasil), global, family_office."""
    return cartas.listar(gestora, dias, tipo)


@mcp.tool()
def situacao_gestoras() -> str:
    """Quantas gestoras da lista seguem publicando cartas, quais pararam (podem ter encerrado) e quais não leem."""
    return cartas.situacao()


@mcp.tool()
def ler_carta(link: str) -> str:
    """Texto de uma carta de gestor (PDF ou página) a partir do link devolvido por cartas_gestores, para resumir.
    Resuma tese, posicionamento e visão de cenário citando a gestora e o mês; não reproduza trechos longos."""
    return cartas.ler(link)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
