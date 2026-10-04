"""Servidor MCP `quiron-academia`: trilha, edital, questões, diagnóstico e plano de estudo (CFP primeiro)."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.academia import consultas, diagnostico
from quiron.servicos.academia.banco import Banco

mcp = MCPServer(
    "quiron-academia",
    instructions=(
        "Academia de certificações do Rickson (trilha CFP → CNPI → CFA…). O edital oficial está mapeado em tópicos "
        "(códigos como 3.5.2): use `edital`/`topico` para situar qualquer assunto antes de ensinar. Questões são "
        "geradas por IA e conferidas por um 2º modelo; números e diagnóstico vêm do Python. Não invente regra: "
        "na dúvida, diga que é preciso conferir. Siga agente/skills/academia-aula.md e academia-caso.md."
    ),
)


@mcp.tool()
def trilha() -> str:
    """Trilha de certificações e painel de progresso (prontidão, ritmo, revisões pendentes)."""
    return consultas.trilha()


@mcp.tool()
def edital(cert: str = "CFP", modulo: int | None = None, busca: str | None = None) -> str:
    """Edital oficial mapeado: sem argumentos = formato da prova e módulos com peso; modulo = tópicos do módulo;
    busca = tópicos do edital que tratam de um assunto (ex.: 'come-cotas', 'sucessão', 'PGBL')."""
    return consultas.mapa_edital(cert, modulo, busca)


@mcp.tool()
def topico(codigo: str, cert: str = "CFP") -> str:
    """Detalhe de um tópico do edital (ex.: '6.2.1'): itens, subtópicos e o desempenho do Rickson nele."""
    return consultas.detalhar_topico(codigo, cert)


@mcp.tool()
def diagnostico_estudo() -> str:
    """Diagnóstico por módulo (acerto estimado, situação vs. meta de 70%) e pontos fracos por tópico."""
    banco = Banco()
    return diagnostico.texto_diagnostico(diagnostico.diagnosticar(banco))


@mcp.tool()
def plano_estudo(horas_semana: float | None = None) -> str:
    """Plano da semana distribuído pelos pontos fracos e pelos pesos do edital (padrão 5 h; o Rickson estuda 3–7 h)."""
    return consultas.plano(horas_semana)


@mcp.tool()
def configurar_estudo(data_prova: str | None = None, horas_semana: float | None = None, dias: list[str] | None = None) -> str:
    """Guarda a data da prova (dd/mm/aaaa), as horas por semana e os dias de estudo (segunda…domingo)."""
    return consultas.configurar(data_prova, horas_semana, dias)


@mcp.tool()
def gerar_questoes(alvo: str, quantidade: int = 4) -> str:
    """Gera questões novas (revisadas por um 2º modelo) para um módulo ('3'), tópico ('3.5.2') ou tema do edital."""
    return consultas.gerar(alvo, quantidade)


@mcp.tool()
def questoes(alvo: str = "", quantidade: int = 3) -> str:
    """Questões para responder na conversa (gabarito separado no fim — só revele depois da resposta).
    No Telegram, prefira sugerir /questoes (tem botões A–D)."""
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
