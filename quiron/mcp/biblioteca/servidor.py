"""Servidor MCP `quiron-biblioteca`: os livros do Rickson como mentor, sempre com citação."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.biblioteca import consultas
from quiron.servicos.biblioteca.ingestao import ingerir_pasta, reclassificar_blocos

mcp = MCPServer(
    "quiron-biblioteca",
    instructions=(
        "Biblioteca pessoal do Rickson. As ferramentas devolvem trechos dos livros com citação. "
        "Responda apoiado nesses trechos e cite sempre no formato '📚 Livro — Autor, cap. X, p. Y'. "
        "Não reproduza trechos longos; explique com suas palavras. Siga as skills em agente/skills/."
    ),
)


@mcp.tool()
def buscar(pergunta: str, n: int = 6, livro: str | None = None, autor: str | None = None, bloco: int | None = None,
           area: str | None = None) -> str:
    """Busca trechos dos livros sobre uma pergunta, com citação (livro, autor, capítulo, página).
    Filtros opcionais: livro (id ou parte do título), autor, bloco (número do bloco do guia),
    area (pasta do acervo: ECONOMIA, RENDA_FIXA, RISCO, COMERCIAL, CFP…)."""
    return consultas.buscar(pergunta, n, livro, autor, bloco, area=area)


@mcp.tool()
def estudar_tema(tema: str, n: int = 12, area: str | None = None) -> str:
    """Material para estudar um tema: trechos agrupados por livro, capítulos para ler e blocos do guia ligados.
    area opcional limita à pasta do acervo (ex.: RISCO)."""
    return consultas.estudar_tema(tema, n, area=area)


@mcp.tool()
def debate_autores(tema: str, autores: list[str] | None = None, por_autor: int = 2) -> str:
    """O que cada autor da biblioteca diz sobre um tema — base para a mesa-redonda de investidores."""
    return consultas.debate_autores(tema, autores, por_autor)


@mcp.tool()
def mapa_autor(autor: str) -> str:
    """Livros, capítulos e temas (blocos do guia) de um autor presente na biblioteca."""
    return consultas.mapa_autor(autor)


@mcp.tool()
def ficha(livro: str) -> str:
    """Ficha de um livro (id ou parte do título): dados, capítulos e ligação com os 22 blocos."""
    return consultas.ficha(livro)


@mcp.tool()
def conectar_conceitos(conceito_a: str, conceito_b: str) -> str:
    """Como dois conceitos se ligam nos livros (trechos que tratam dos dois juntos)."""
    return consultas.conectar_conceitos(conceito_a, conceito_b)


@mcp.tool()
def pilula(bloco: int | None = None) -> str:
    """Trecho do dia para a pílula diária de estudo (opcional: de um bloco específico do guia)."""
    return consultas.pilula(bloco)


@mcp.tool()
def cobertura() -> str:
    """Quanto material a biblioteca tem para cada um dos 22 blocos do guia (e quais estão sem material)."""
    return consultas.cobertura()


@mcp.tool()
def listar_livros() -> str:
    """Lista os livros indexados."""
    return consultas.listar_livros()


@mcp.tool()
def ingerir(forcar: bool = False) -> str:
    """Processa os livros novos de biblioteca/entrada (PDF, PDF escaneado com OCR, EPUB). Pode demorar."""
    rel = ingerir_pasta(forcar=forcar)
    linhas = [f"Ingestão: {rel.resumo()}"] + [f"- {l.arquivo}: {l.situacao} — {l.detalhe}" for l in rel.livros]
    return "\n".join(linhas + ["", "Relatório completo em biblioteca/relatorio_ingestao.md"])


@mcp.tool()
def reclassificar() -> str:
    """Religa todos os trechos aos 22 blocos (use depois de editar config/guia_22_blocos.yaml)."""
    cont = reclassificar_blocos()
    if not cont:
        return consultas.VAZIA
    return "Trechos por bloco: " + ", ".join(f"{'sem bloco' if b == 0 else f'bloco {b}'}: {q}" for b, q in sorted(cont.items()))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
