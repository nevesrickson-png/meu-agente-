"""Servidor MCP `quiron-organizacao`: tarefas com lembrete, notas, metas, o dia de hoje, revisão semanal e Google Agenda."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from quiron.servicos.organizacao import google_agenda, hoje, metas, notas, tarefas

mcp = MCPServer(
    "quiron-organizacao",
    instructions=(
        "Organização do Rickson. Quando ele pedir para lembrar/anotar uma tarefa (\"amanhã às 10h ligar para o CLI-012\"), "
        "use `criar_tarefa` com a frase EXATAMENTE como veio: a data e a hora são calculadas pela ferramenta e o lembrete é "
        "criado. Não use para rotinas recorrentes (essas vão no agendador interno). `hoje` monta o dia; `revisao_semanal` a "
        "semana. Notas com `anotar`/`buscar_notas`; metas com `criar_meta`/`registrar_meta`. Google Agenda: `agenda` e "
        "`criar_evento` (só se configurado). Cliente só como CLI-XXX."
    ),
)


@mcp.tool()
def criar_tarefa(texto: str) -> str:
    """Cria tarefa a partir da frase do Rickson (ex.: 'amanhã às 10h ligar para o CLI-012'); cria o lembrete na hora."""
    try:
        return tarefas.confirmar(tarefas.criar(texto, origem="agente"))
    except tarefas.TarefaInvalida as e:
        return f"Não criei: {e}"


@mcp.tool()
def listar_tarefas(filtro: str = "pendentes") -> str:
    """Tarefas: filtro = pendentes | hoje | atrasadas | concluidas."""
    itens = tarefas.listar(filtro)
    if filtro == "concluidas":
        return "\n".join(t.descrever() for t in itens) or "Nenhuma tarefa concluída."
    return tarefas.descrever_lista(itens)


@mcp.tool()
def concluir_tarefa(numero: int) -> str:
    """Marca a tarefa #numero como feita (e cancela o lembrete)."""
    try:
        return "✅ " + tarefas.concluir(numero).texto
    except tarefas.TarefaInvalida as e:
        return str(e)


@mcp.tool()
def adiar_tarefa(numero: int, para: str) -> str:
    """Adia a tarefa: para = '1h', '30min', 'amanhã', 'sexta às 15h'…"""
    try:
        return "⏰ " + tarefas.confirmar(tarefas.adiar(numero, para)).removeprefix("📌 Tarefa criada: ")
    except tarefas.TarefaInvalida as e:
        return str(e)


@mcp.tool()
def remover_tarefa(numero: int) -> str:
    """Apaga a tarefa #numero."""
    return "Removida." if tarefas.remover(numero) else "Não encontrei essa tarefa."


@mcp.tool()
def hoje_do_rickson() -> str:
    """O dia: Google Agenda, tarefas atrasadas e de hoje, lembretes, vencimentos de clientes em 7 dias e metas."""
    return hoje.montar_hoje()


@mcp.tool()
def revisao_semanal() -> str:
    """Revisão da semana: feito, metas, o que ficou para trás e a próxima semana."""
    return hoje.montar_revisao()


@mcp.tool()
def anotar(texto: str) -> str:
    """Guarda uma nota (#tags ajudam a achar depois)."""
    try:
        return "Anotado: " + notas.criar(texto).descrever()
    except ValueError as e:
        return str(e)


@mcp.tool()
def buscar_notas(termo: str = "") -> str:
    """Procura nas notas por palavra ou #tag (vazio = últimas)."""
    return notas.descrever(notas.buscar(termo), termo)


@mcp.tool()
def criar_meta(texto: str) -> str:
    """Cria meta: 'estudar 5 horas por semana', 'captar 2 milhões até dezembro', 'ler 12 livros até 31/12'."""
    try:
        return metas.descrever(metas.criar(texto))
    except metas.MetaInvalida as e:
        return str(e)


@mcp.tool()
def registrar_meta(numero: int, valor: float, nota: str = "") -> str:
    """Soma progresso à meta #numero (ex.: valor=2 para 2 horas)."""
    try:
        return metas.descrever(metas.registrar(numero, valor, nota))
    except metas.MetaInvalida as e:
        return str(e)


@mcp.tool()
def ver_metas() -> str:
    """Metas ativas com progresso e ritmo."""
    return metas.descrever_todas()


@mcp.tool()
def agenda(dias: int = 1) -> str:
    """Eventos do Google Agenda de hoje (dias=1) ou dos próximos dias."""
    from datetime import date

    try:
        return "\n".join(hoje._agenda(date.today(), max(1, min(dias, 31)))) or "Agenda livre."
    except google_agenda.AgendaIndisponivel as e:
        return str(e)


@mcp.tool()
def criar_evento(texto: str) -> str:
    """Cria evento no Google Agenda a partir da frase (ex.: 'quinta às 15h reunião com CLI-012 por 1h30')."""
    try:
        e = google_agenda.evento_de_texto(texto)
    except google_agenda.AgendaIndisponivel as e:
        return str(e)
    return f"📅 Evento criado: {e.inicio:%d/%m %H:%M}–{e.fim:%H:%M} {e.titulo}"


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
