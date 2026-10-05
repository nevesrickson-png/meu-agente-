"""Servidor MCP `quiron-assessoria`: ficha de planejamento do cliente (CLI-XXX), LGPD (esquecer cliente) e o dia a dia
da assessoria (dossiê de reunião, pós-reunião, objeções, compliance de mensagens, vencimentos e treino).

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
        "tributario, protecao, empresario). `esquecer_cliente` apaga tudo do cliente (LGPD) e pede confirmação. "
        "Dia a dia: `dossie_reuniao` antes da reunião; `registrar_pos_reuniao` com o texto/transcrição inteiro depois dela "
        "(cria lembretes); `objecoes`; `conferir_compliance` em todo rascunho para cliente; `vencimentos`; treino com "
        "cliente simulado em `iniciar_treino`/`responder_treino`/`encerrar_treino`."
    ),
)


@mcp.tool()
def simular_patrimonio(patrimonio: float = 0, aporte_mensal: float = 0, idade: int = 40, perfil: str = "moderado",
                       meta: float = 0, renda_desejada: float = 0, idade_meta: int | None = None,
                       crescimento_aporte_aa: float = 0, imovel_valor: float = 0, horizonte_imovel_anos: int = 20,
                       cliente: str = "") -> str:
    """Simulador de patrimônio (R$ de hoje, 3 cenários + Monte Carlo): quanto investir por mês para a meta, quando dá
    para parar de trabalhar (renda_desejada mensal), em quanto tempo chega a R$ X (meta) e imóvel × aplicações
    (imovel_valor). `cliente`=CLI-XXX usa a ficha de planejamento e os outros campos ajustam. Use para essas perguntas
    em vez de fazer contas; mostre as premissas e o aviso de que é simulação."""
    from quiron.servicos.planejamento import simulador

    dados = {"patrimonio": patrimonio, "aporte_mensal": aporte_mensal, "idade": idade, "perfil": perfil, "meta": meta,
             "renda_desejada": renda_desejada, "idade_meta": idade_meta, "crescimento_aporte_aa": crescimento_aporte_aa,
             "imovel_valor": imovel_valor, "horizonte_imovel_anos": horizonte_imovel_anos}
    try:
        e = simulador.de_ficha(cliente, **{k: v for k, v in dados.items() if k not in {"idade", "perfil", "horizonte_imovel_anos"}}) \
            if cliente else simulador.Entrada.de_dict(dados)
        return simulador.texto(simulador.simular(e))
    except (ValueError, TypeError) as e:
        return f"Não simulei: {e}"


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


# ---------------------------------------------------------------- dia a dia (Fase 13)
@mcp.tool()
def dossie_reuniao(cliente: str) -> str:
    """Tudo o que o Quíron sabe do cliente (CLI-XXX) para preparar a reunião: ficha, carteira e enquadramento,
    vencimentos, últimas reuniões, lembretes em aberto e relatórios já feitos."""
    from quiron.servicos.assessoria import dossie

    try:
        return dossie.montar(cliente)
    except ValueError as e:
        return str(e)


@mcp.tool()
def registrar_pos_reuniao(cliente: str, texto: str) -> str:
    """Pós-reunião: organiza a anotação/transcrição (resumo, decisões, tarefas com prazo, sugestões para a ficha,
    alertas de compliance), cria os lembretes e guarda. Mande o texto inteiro, como veio."""
    from quiron.servicos.assessoria import pos_reuniao

    try:
        r = pos_reuniao.processar(cliente, texto)
    except ValueError as e:
        return f"Não registrei: {e}"
    extra = f"\n\n(id da reunião: {r.id} — para aplicar as sugestões na ficha use aplicar_reuniao_na_ficha)" if r.ficha else ""
    return r.markdown() + extra


@mcp.tool()
def aplicar_reuniao_na_ficha(cliente: str, reuniao_id: str) -> str:
    """Aplica na ficha as sugestões de uma reunião registrada (só depois de o Rickson confirmar)."""
    from quiron.servicos.assessoria import pos_reuniao

    try:
        return pos_reuniao.aplicar_na_ficha(cliente, reuniao_id)
    except ValueError as e:
        return str(e)


@mcp.tool()
def reunioes_do_cliente(cliente: str, limite: int = 5) -> str:
    """Últimas reuniões registradas do cliente (resumo, decisões e tarefas)."""
    from quiron.servicos.assessoria import pos_reuniao

    try:
        itens = pos_reuniao.listar(cliente, limite)
    except ValueError as e:
        return str(e)
    return "\n\n---\n\n".join(r.markdown() for r in itens) or "Nenhuma reunião registrada."


@mcp.tool()
def objecoes(texto: str) -> str:
    """Roteiro para tratar uma objeção de cliente (biblioteca em config/objecoes.yaml)."""
    from quiron.servicos.assessoria import objecoes as obj

    achadas = obj.buscar(texto)
    if not achadas:
        return ("Não achei essa objeção na biblioteca. Use o método: validar → perguntar o que há por trás → reenquadrar "
                "pelo objetivo do cliente → evidência com fonte → próximo passo pequeno.")
    return "\n\n".join(obj.descrever(k, o) for k, o in achadas)


@mcp.tool()
def conferir_compliance(texto: str) -> str:
    """Confere um rascunho para cliente: promessa de rentabilidade, negar risco, certezas, rentabilidade passada sem
    ressalva, FGC exagerado, pressão e dados pessoais."""
    from quiron.servicos.assessoria import compliance

    return compliance.resumo(compliance.conferir(texto))


@mcp.tool()
def vencimentos(dias: int = 90, cliente: str = "") -> str:
    """Aplicações das carteiras guardadas que vencem nos próximos `dias` (opcional: só de um cliente)."""
    from quiron.servicos.assessoria import vencimentos as venc

    dias = max(1, min(int(dias or 90), 720))
    return venc.descrever(venc.proximos(dias, cliente), dias)


@mcp.tool()
def iniciar_treino(pedido: str = "") -> str:
    """Começa um treino com cliente simulado. `pedido` pode citar personagem, cenário e dificuldade (veja
    opcoes_de_treino); vazio = sorteio. Depois, cada fala do Rickson vai em responder_treino."""
    from quiron.servicos.assessoria import treino

    if pedido.strip().lower() in {"opcoes", "opções"}:
        return treino.opcoes()
    try:
        return treino.iniciar(pedido)[1]
    except cerebro_indisponivel() as e:
        return f"Sem IA no momento para interpretar o cliente: {str(e)[:200]}"


@mcp.tool()
def opcoes_de_treino() -> str:
    """Personagens, cenários e dificuldades do treino."""
    from quiron.servicos.assessoria import treino

    return treino.opcoes()


@mcp.tool()
def responder_treino(fala: str) -> str:
    """Fala do assessor no treino ativo; devolve a resposta do cliente simulado."""
    from quiron.servicos.assessoria import treino

    try:
        return treino.responder(fala)
    except (treino.TreinoInvalido, cerebro_indisponivel()) as e:
        return str(e)


@mcp.tool()
def encerrar_treino() -> str:
    """Encerra o treino ativo e devolve o feedback (nota por critério, números calculados, objeções, reescritas)."""
    from quiron.servicos.assessoria import treino

    try:
        return treino.encerrar()[1]
    except treino.TreinoInvalido as e:
        return str(e)


@mcp.tool()
def evolucao_treinos() -> str:
    """Notas dos últimos treinos e média por critério."""
    from quiron.servicos.assessoria import treino

    return treino.evolucao()


def cerebro_indisponivel() -> type[Exception]:
    from quiron.nucleo.cerebro import CerebroIndisponivel

    return CerebroIndisponivel


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
