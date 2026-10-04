"""Servidor MCP `quiron-academia`: áreas de conhecimento (campos + certificações), programas, questões,
diagnóstico e plano de estudo."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.academia import consultas

mcp = MCPServer(
    "quiron-academia",
    instructions=(
        "Academia do Rickson: áreas de conhecimento de finanças (campos como ECONOMIA, RENDA_FIXA, RISCO, COMERCIAL… e "
        "certificações como CFP, CNPI, CFA). Cada área tem um programa em tópicos (códigos como 3.5.2): use `programa` "
        "para situar qualquer assunto antes de ensinar. `area` aceita o id (RENDA_FIXA) ou o nome (renda fixa); vazio = "
        "área ativa. Questões são geradas por IA e conferidas por um 2º modelo; números e diagnóstico vêm do Python. "
        "Não invente regra. Siga agente/skills/academia-aula.md e academia-caso.md."
    ),
)


@mcp.tool()
def trilha() -> str:
    """Trilha de certificações e painel de progresso de todas as áreas."""
    return consultas.trilha()


@mcp.tool()
def areas() -> str:
    """Lista as áreas de conhecimento (campos e certificações) e se cada uma tem programa mapeado."""
    return consultas.listar_areas()


@mcp.tool()
def programa(area: str = "CFP", modulo: int | None = None, busca: str | None = None) -> str:
    """Programa de estudo de uma área (edital oficial nas certificações mapeadas): sem argumentos = módulos;
    modulo = tópicos do módulo; busca = tópicos que tratam de um assunto (ex.: 'come-cotas', 'duration', 'objeções')."""
    return consultas.mapa_edital(area, modulo, busca)


@mcp.tool()
def topico(codigo: str, area: str = "CFP") -> str:
    """Detalhe de um tópico (ex.: '6.2.1' no CFP, '5.1' em RENDA_FIXA): itens, subtópicos e desempenho do Rickson."""
    return consultas.detalhar_topico(codigo, area)


@mcp.tool()
def diagnostico_estudo(area: str | None = None) -> str:
    """Diagnóstico da área (acerto estimado por módulo vs. 70%) e pontos fracos por tópico."""
    return consultas.diagnostico_texto(area)


@mcp.tool()
def plano_estudo(area: str | None = None, horas_semana: float | None = None) -> str:
    """Plano da semana da área pelos pontos fracos e pesos do programa (padrão 5 h; o Rickson estuda 3–7 h)."""
    return consultas.plano(horas_semana, area=area)


@mcp.tool()
def configurar_estudo(area: str | None = None, data_prova: str | None = None, horas_semana: float | None = None,
                      dias: list[str] | None = None) -> str:
    """Troca a área ativa e/ou guarda a data da prova dessa área (dd/mm/aaaa), horas por semana e dias de estudo."""
    return consultas.configurar(data_prova, horas_semana, dias, area=area)


@mcp.tool()
def gerar_questoes(alvo: str, quantidade: int = 4) -> str:
    """Gera questões novas (revisadas por um 2º modelo). alvo: 'economia 2', 'cfp 3.5.2', 'renda fixa duration'…"""
    return consultas.gerar(alvo, quantidade)


@mcp.tool()
def questoes(alvo: str = "", quantidade: int = 3) -> str:
    """Questões para responder na conversa (gabarito separado no fim — só revele depois da resposta).
    alvo como em gerar_questoes. No Telegram, prefira sugerir /questoes (tem botões A–D)."""
    return consultas.questoes_texto(alvo, quantidade)


@mcp.tool()
def registrar_resposta(questao_id: int, letra: str) -> str:
    """Registra a resposta do Rickson a uma questão (entra no diagnóstico e na revisão espaçada)."""
    return consultas.registrar(questao_id, letra)


@mcp.tool()
def materiais_gratuitos(cert: str | None = None) -> str:
    """Catálogo de materiais gratuitos confirmados (editais, livros, cursos) por certificação."""
    return consultas.materiais(cert)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
