"""Servidor MCP `quiron-carreira`: plano de carreira, diário de teses, portfólio de análises, simulação de entrevista
e radar regulatório."""

from __future__ import annotations

from datetime import date

from mcp.server.mcpserver import MCPServer

from quiron.servicos.carreira import diario, entrevista, plano, portfolio, radar

mcp = MCPServer(
    "quiron-carreira",
    instructions=(
        "Carreira do Rickson rumo a analista/estrategista de referência. `plano_de_carreira` mostra onde ele está. "
        "Tese ou decisão de investimento que ele quer registrar → `registrar_tese` com o texto como veio (preço do dia e "
        "data de revisão são calculados). `revisar_teses` traz as que vencem com retorno vs. Ibovespa e calibração; "
        "`fechar_tese` registra o resultado e o aprendizado. `radar_regulatorio` lista normas recentes de fontes oficiais "
        "(CVM, Receita, Banco Central, Câmara) — explique o impacto para um assessor. Uso interno e de estudo."
    ),
)


@mcp.tool()
def plano_de_carreira() -> str:
    """Certificações (com prontidão da Academia e datas de prova), track record, portfólio, competências e próximos 90 dias."""
    return plano.montar()


@mcp.tool()
def registrar_prova(certificacao: str, data_prova: str = "", situacao: str = "agendada") -> str:
    """Registra data (AAAA-MM-DD) e situação (planejada | agendada | aprovado | reprovado) de uma certificação da trilha."""
    try:
        return plano.registrar_prova(certificacao, date.fromisoformat(data_prova) if data_prova else None, situacao)
    except ValueError as e:
        return str(e)


@mcp.tool()
def avaliar_competencia(competencia: str, nota: int) -> str:
    """Autoavaliação de 0 a 10 (ex.: valuation 6) — o plano mostra a evolução."""
    try:
        return plano.avaliar(competencia, int(nota))
    except ValueError as e:
        return str(e)


@mcp.tool()
def registrar_tese(texto: str) -> str:
    """Registra tese/decisão no diário (premissas, invalidação, horizonte, confiança; preço do dia; lembrete de revisão)."""
    try:
        return diario.descrever(diario.registrar(texto))
    except diario.TeseInvalida as e:
        return str(e)


@mcp.tool()
def listar_teses(situacao: str = "aberta") -> str:
    """Teses: aberta | acertou | errou | parcial | abandonada | todas."""
    itens = diario.listar(situacao)
    return "\n".join(t.resumo() for t in itens) or "Nenhuma tese."


@mcp.tool()
def revisar_teses(dias: int = 7) -> str:
    """Revisão das teses que vencem nos próximos dias (ou venceram): retorno, excesso vs. benchmark, premissas, calibração."""
    return diario.revisao_de_teses(dias)


@mcp.tool()
def revisar_tese(numero: int, nota: str = "") -> str:
    """Revisa uma tese agora (números do dia) e guarda a revisão."""
    try:
        return diario.revisar(numero, nota)
    except diario.TeseInvalida as e:
        return str(e)


@mcp.tool()
def fechar_tese(numero: int, resultado: str, aprendizado: str = "") -> str:
    """Fecha a tese: resultado = acertou | parcial | errou | abandonada; aprendizado = o que tirar disso."""
    try:
        t = diario.resolver(numero, resultado, aprendizado)
    except diario.TeseInvalida as e:
        return str(e)
    return f"Fechada: {t.resumo()}\n{diario.texto_estatisticas()}"


@mcp.tool()
def track_record() -> str:
    """Acerto e calibração (Brier) das teses fechadas."""
    return diario.texto_estatisticas()


@mcp.tool()
def portfolio_de_analises() -> str:
    """Análises no portfólio e as que podem entrar (só relatórios sem dados de cliente)."""
    return portfolio.listar_texto()


@mcp.tool()
def adicionar_ao_portfolio(relatorio: int, comentario: str = "") -> str:
    """Põe o relatório #n no portfólio, com o motivo (não aceita relatório com cliente)."""
    try:
        return portfolio.adicionar(relatorio, comentario)
    except ValueError as e:
        return str(e)


@mcp.tool()
def gerar_portfolio_pdf() -> str:
    """Gera o PDF do portfólio (resumos + track record) e devolve o caminho."""
    try:
        return f"PDF do portfólio: {portfolio.gerar_pdf()}"
    except ValueError as e:
        return str(e)


@mcp.tool()
def iniciar_entrevista(cargo: str = "") -> str:
    """Simulação de entrevista: analista_research | estrategista | analista_buyside | consultor_cvm | private_banker."""
    return entrevista.iniciar(cargo)[1]


@mcp.tool()
def responder_entrevista(resposta: str) -> str:
    """Resposta do Rickson na entrevista ativa; devolve a próxima pergunta."""
    try:
        return entrevista.responder(resposta)
    except entrevista.EntrevistaInvalida as e:
        return str(e)


@mcp.tool()
def encerrar_entrevista() -> str:
    """Encerra a entrevista e devolve o feedback."""
    try:
        return entrevista.encerrar()[1]
    except entrevista.EntrevistaInvalida as e:
        return str(e)


@mcp.tool()
def radar_regulatorio(dias: int = 14, so_novidades: bool = False) -> str:
    """Normas e notícias regulatórias recentes (CVM, Receita, Banco Central, Câmara), por relevância para o assessor."""
    return radar.relatorio(max(1, min(int(dias), 90)), so_novidades)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
