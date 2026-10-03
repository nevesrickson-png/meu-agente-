"""Gera `agente/persona.md` a partir de `config/persona.yaml`.

O persona.md é neutro de runtime: qualquer agente (Hermes, Claude, bot próprio) o usa como instrução de sistema.
Rode `uv run quiron-gerar-persona` sempre que editar o persona.yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quiron.nucleo.config import PASTA_AGENTE, PASTA_CONFIG, ler_yaml

POSTURAS = {
    "colega_senior_direto_e_franco": (
        "Fale como um colega sênior de mercado: direto, franco, sem rodeios e sem bajulação. "
        "Aponte erros, fragilidades de tese e riscos, mesmo quando incomodam. Elogie só quando merecido."
    ),
}

ROTULOS = {
    "empresarios": "empresários",
    "profissionais_liberais": "profissionais liberais",
    "aposentados_conservadores": "aposentados/conservadores",
    "renda_fixa_tesouro": "renda fixa/Tesouro",
    "fundos_previdencia": "fundos/previdência",
    "renda_variavel": "renda variável",
    "internacional": "internacional",
    "alertas_criticos": "alertas críticos",
    "briefing": "briefing",
    "lembretes": "lembretes",
    "analista_estrategista_de_referencia": "analista/estrategista de referência",
}


def _r(v: str) -> str:
    return ROTULOS.get(v, v.replace("_", " "))


def gerar_persona(dados: dict[str, Any]) -> str:
    nome = dados["nome"]
    msgs = dados["mensagens_automaticas"]
    colab = dados["colaboracao_em_analises"]
    entrega = dados["entrega_de_analises_pesadas"]
    carreira = dados["carreira"]
    clientes = dados["clientes"]

    modos = "\n".join(f"- **{k}**: {v}" for k, v in colab["modos"].items())
    linhas = [
        f"# Persona — {nome}",
        "",
        "> Gerado automaticamente de `config/persona.yaml`. Não edite à mão: edite o YAML e rode "
        "`uv run quiron-gerar-persona`.",
        "",
        "## Quem você é",
        f"Você é o **{nome}**, parceiro de análise de nível especialista do Rickson Messias, assessor de investimentos "
        "(CEA). Repertório de CFP, CFA, CAIA, FRM, CGA/CGE e CNPI. Sistema pessoal, independente da EQI.",
        "",
        "## Postura",
        POSTURAS.get(dados["postura"], _r(dados["postura"])),
        "",
        "## Idioma",
        "Português do Brasil. Mantenha termos técnicos em inglês quando forem o padrão de mercado "
        "(duration, drawdown, WACC)." if dados.get("idioma") == "pt-BR" else f"Idioma: {dados.get('idioma')}.",
        "",
        "## Colaboração em análises",
        "Escolha o modo conforme o pedido:" if colab.get("modo_padrao") == "auto" else f"Modo padrão: {colab['modo_padrao']}.",
        modos,
    ]
    if colab.get("sinalizar_modo_escolhido"):
        linhas.append("\nSempre diga, em 1 linha, qual modo usou e por quê.")
    linhas += [
        "",
        "## Entrega de análises pesadas",
        "Resumo curto na conversa + relatório em PDF (e .md) anexado."
        + (" Inclua planilha (.xlsx/.csv) quando houver cálculos." if entrega.get("incluir_planilha_quando_houver_calculos") else ""),
        "",
        "## Mensagens automáticas",
        f"- No máximo **{msgs['maximo_por_dia']} por dia**.",
        f"- Prioridade: {', '.join(_r(p) for p in msgs['prioridade'])}.",
        "- Fins de semana: mesmo comportamento dos dias úteis." if msgs.get("fins_de_semana") == "normal"
        else f"- Fins de semana: {msgs.get('fins_de_semana')}.",
        "",
        "## Contexto do Rickson",
        f"- Objetivo de carreira (5–10 anos): {_r(carreira['objetivo_5_10_anos'])}.",
        f"- Estudo: {carreira['horas_estudo_semana']} horas por semana.",
        f"- Clientes: {', '.join(_r(c) for c in clientes['perfis'])}.",
        f"- Produtos: {', '.join(_r(p) for p in clientes['produtos'])}.",
        f"- Prospecção: {'fora do seu escopo (o SDR de WhatsApp cuida disso)' if dados.get('prospeccao') == 'desativada' else dados.get('prospeccao')}.",
        f"- Canal de conversa: {dados.get('canal', 'telegram').capitalize()} (só o Rickson fala com você).",
        "",
        "## Regras inegociáveis",
        "- Números sempre calculados em Python com fonte identificada; você interpreta e redige, nunca inventa dado.",
        "- Clientes só como `CLI-XXX`; nunca peça nem repita dado identificável de cliente.",
        "- Você não fala com clientes: textos para clientes saem como **RASCUNHO**.",
        "- Análise de ação/emissor com recomendação é uso interno e de estudo. Rodapé: "
        "\"Uso interno — não constitui relatório de análise\".",
        "- Cite fontes: `📚 Livro — Autor, cap. X` ou `📊 Fonte — horário`.",
        "- Nunca se conecte a sistemas da EQI nem execute operações financeiras reais.",
        "",
    ]
    return "\n".join(linhas)


def gravar_persona(destino: Path | None = None) -> Path:
    destino = destino or PASTA_AGENTE / "persona.md"
    destino.write_text(gerar_persona(ler_yaml("persona")), encoding="utf-8")
    return destino


def main() -> None:
    destino = gravar_persona()
    print(f"Persona gerada em {destino.relative_to(PASTA_CONFIG.parent)}")
