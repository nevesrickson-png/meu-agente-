"""Servidor MCP `quiron-analise`: motor de análises pesadas (fila → cálculos em Python → relatório PDF + planilha)
e calculadoras financeiras com memória de cálculo."""

from __future__ import annotations


import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from quiron.servicos import calculadoras
from quiron.servicos.analise.fila import carregar_tipos, fila

mcp = MCPServer(
    "quiron-analise",
    instructions=(
        "Motor de análise do Quíron. Para estudos com dados e números (ex.: comparar aplicações de renda fixa), use "
        "`analisar`: a análise entra na fila, os números são calculados em Python e o relatório (resumo + PDF + planilha) "
        "é entregue ao Rickson no Telegram quando ficar pronto — diga isso a ele, com o número do pedido, sem inventar "
        "resultado. Modos: entregar (pronto), debater (prós/contras/perguntas) ou contestar (advogado do diabo); pergunte "
        "ou escolha pelo pedido e diga qual usou. Para contas rápidas use `calcular` (mostre a memória de cálculo). "
        "Tudo é uso interno: não é recomendação a cliente."
    ),
)


@mcp.tool()
def tipos_de_analise() -> str:
    """Lista as análises disponíveis e os parâmetros de cada uma."""
    linhas = []
    for t in carregar_tipos().values():
        linhas.append(f"## {t.nome}\n{t.descricao}\nParâmetros:")
        linhas += [f"- {k}: {v}" for k, v in t.parametros.items()]
    return "\n".join(linhas) or "Nenhum tipo de análise registrado."


@mcp.tool()
def analisar(tipo: str, parametros: dict[str, Any] | None = None, modo: str = "entregar") -> str:
    """Põe uma análise na fila. tipo: veja tipos_de_analise (ex.: 'renda_fixa_comparativo'). parametros: dicionário
    (ex.: {"valor": 100000, "prazo_anos": 2, "opcoes": [{"tipo": "cdb", "percentual_cdi": 110}, {"tipo": "lci",
    "percentual_cdi": 92}, {"tipo": "tesouro_ipca"}]}). modo: entregar | debater | contestar."""
    try:
        t = fila().pedir(tipo, parametros or {}, modo, origem=os.environ.get("QUIRON_ORIGEM", "agente"))
    except ValueError as e:
        return f"Não consegui pedir a análise: {e}"
    na_frente = fila().posicao(t.id)
    entrega = ("o resumo, o PDF e a planilha chegam no Telegram assim que ficar pronta"
               if t.origem == "telegram" else "veja com situacao_analise ou no Terminal (RPT)")
    return (f"Análise #{t.id} na fila ({na_frente} na frente; costuma levar de 30 s a 2 min). Modo: {t.modo}. "
            f"Quando terminar, {entrega}. Não antecipe resultados.")


@mcp.tool()
def situacao_analise(numero: int) -> str:
    """Situação de uma análise pedida (na fila, rodando, pronta ou erro) e, se pronta, o resumo."""
    t = fila().obter(numero)
    if not t:
        return f"Análise #{numero} não existe."
    if t.situacao == "pronta":
        return f"{t.descrever()}\n{t.resumo}\nArquivos: {', '.join(str(p) for p in t.arquivos().values())}"
    if t.situacao == "erro":
        return f"{t.descrever()}: {t.erro}"
    return t.descrever() + (f" — {fila().posicao(t.id)} na frente" if t.situacao == "na fila" else "")


@mcp.tool()
def relatorios(busca: str = "", limite: int = 10) -> str:
    """Arquivo de relatórios do Quíron: os mais recentes ou os que contêm a busca (texto completo)."""
    itens = fila().buscar(busca, limite) if busca.strip() else fila().listar(limite)
    return "\n".join(t.descrever() for t in itens) or "Nenhum relatório ainda."


@mcp.tool()
def ler_relatorio(numero: int) -> str:
    """Conteúdo de um relatório pronto (Markdown: resumo, premissas, tabelas, fontes, limitações) para discutir."""
    rel = fila().relatorio(numero)
    return rel.markdown()[:15000] if rel else f"Relatório #{numero} não encontrado ou ainda não pronto."


@mcp.tool()
def calculadoras_disponiveis() -> str:
    """Calculadoras financeiras e os campos de cada uma."""
    linhas = []
    for nome, esq in calculadoras.ESQUEMAS.items():
        campos = ", ".join(f"{c[0]} ({c[1]}; ex.: {c[2]})" for c in esq["campos"])
        linhas.append(f"- {nome} — {esq['nome']}: {campos}")
    return "\n".join(linhas)


@mcp.tool()
def calcular(nome: str, parametros: dict[str, Any]) -> str:
    """Faz uma conta com uma calculadora (veja calculadoras_disponiveis) e devolve resultado + memória de cálculo."""
    try:
        if nome == "percentual_cdi" and "cdi_aa" not in parametros:
            from quiron.servicos.mercado import bcb

            parametros = {**parametros, "cdi_aa": bcb.sgs("cdi", 2).ultimo.valor}
        r = calculadoras.executar(nome, parametros)
    except KeyError:
        return f"Calculadora “{nome}” não existe. Opções: {', '.join(calculadoras.CALCULADORAS)}"
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as e:
        return f"Entrada inválida: {e}"
    partes = [f"**{r.titulo}**", *[f"- {k}: {v}" for k, v in r.linhas], "Memória de cálculo:", *[f"- {m}" for m in r.memoria]]
    partes += [f"⚠️ {a}" for a in r.avisos]
    return "\n".join(partes) + "\n📊 calculado em Python (quiron/servicos/calculadoras.py)"


def main() -> None:
    fila().iniciar_processador()  # processa a fila em segundo plano enquanto o servidor estiver ligado
    mcp.run()  # stdio


if __name__ == "__main__":
    main()



