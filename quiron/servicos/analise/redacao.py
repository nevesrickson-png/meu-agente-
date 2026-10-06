"""Redação do relatório pelo cérebro, a partir dos números JÁ calculados em Python.

Modos (persona): entregar pronto · debater (prós, contras, perguntas para decidir) · contestar (advogado do diabo).
Conferência: todo número citado no texto tem de existir nos fatos/tabelas/premissas; se o modelo inventar, ele tenta
de novo uma vez e, persistindo, o relatório sai com aviso. Sem cérebro disponível, fica o resumo determinístico
que a própria análise já preencheu (a análise nunca falha por falta de IA).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from quiron.nucleo import cerebro
from quiron.servicos.analise.relatorio import Relatorio, Secao, formatar

SISTEMA = (
    "Você é o Quíron, analista sênior (repertório CFA/CFP/FRM), escrevendo para o Rickson, assessor de investimentos. "
    "Português do Brasil, direto e franco, sem bajulação. Use SOMENTE os números fornecidos (fatos, tabelas, premissas): "
    "nunca calcule de cabeça nem invente dado, data ou taxa. Não faça recomendação personalizada a cliente; é uso interno."
)

INSTRUCOES_MODO = {
    "entregar": "Modo ENTREGAR: conclusão clara primeiro, depois os 2–3 porquês e o principal risco.",
    "debater": ("Modo DEBATER: apresente os argumentos a favor e contra de cada caminho relevante e termine com 3 "
                "perguntas que o Rickson precisa responder para decidir (perfil, liquidez, horizonte…)."),
    "contestar": ("Modo CONTESTAR (advogado do diabo): ataque a conclusão óbvia do cenário base — o que faria ela "
                  "dar errado, quais premissas são frágeis e quando a alternativa vence. Seja rigoroso, não do contra à toa."),
}

FORMATO = ('Responda SOMENTE com JSON: {"resumo": ["3 a 5 frases curtas (cada uma com a conclusão e o número que a '
           'sustenta)"], "analise": "texto em Markdown, 2 a 5 parágrafos curtos ou tópicos"}')


# ---------------------------------------------------------------- conferência de números
RE_NUM = re.compile(r"(?<![\w.,])-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w.,])-?\d+(?:[.,]\d+)?")


def _valores(obj: Any) -> list[float]:
    """Todos os números de um objeto (fatos aninhados, listas, textos)."""
    saida: list[float] = []
    if isinstance(obj, bool):
        return saida
    if isinstance(obj, (int, float)):
        saida.append(float(obj))
    elif isinstance(obj, str):
        saida += numeros_do_texto(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            saida += _valores(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            saida += _valores(v)
    return saida


def numeros_do_texto(texto: str) -> list[float]:
    achados = []
    for m in RE_NUM.finditer(texto):
        s = m.group()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            s = s.replace(".", "")
        try:
            achados.append(float(s))
        except ValueError:
            pass
    return achados


def conferir(texto: str, referencias: list[float]) -> list[float]:
    """Números do texto que não batem com nenhuma referência (tolerância de arredondamento; ignora inteiros ≤ 12
    e anos)."""
    estranhos = []
    for n in numeros_do_texto(texto):
        if (n.is_integer() and 0 <= n <= 12) or (n.is_integer() and 1990 <= n <= 2100):
            continue
        ok = any(abs(n - r) <= max(0.051, abs(r) * 0.0051) or abs(n - r * 100) <= 0.051 or abs(n * 1000 - r) <= max(1, abs(r) * 0.006)
                 for r in referencias)
        if not ok:
            estranhos.append(n)
    return estranhos


def referencias(rel: Relatorio) -> list[float]:
    refs = _valores(rel.fatos) + _valores(rel.premissas) + _valores(rel.resumo) + _valores(rel.parametros)
    for s in rel.secoes:
        refs += _valores(s.texto)
        for t in s.tabelas:
            refs += _valores(t.linhas)
            for linha in t.linhas:
                refs += _valores([formatar(v, t.formato(i)) for i, v in enumerate(linha)])
            for i in range(len(t.colunas)):  # diferenças dentro da mesma coluna ("R$ 5.000 a mais")
                coluna = [float(l[i]) for l in t.linhas if i < len(l) and isinstance(l[i], (int, float))]
                refs += [abs(a - b) for k, a in enumerate(coluna) for b in coluna[k + 1:]]
        for g in s.graficos:
            refs += _valores(g.series)
    # diferenças entre fatos numéricos de primeiro nível costumam ser citadas ("vence por R$ 2.300")
    simples = [float(v) for v in rel.fatos.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    refs += [abs(a - b) for i, a in enumerate(simples) for b in simples[i + 1:]]
    return refs


# ---------------------------------------------------------------- redação
def _contexto(rel: Relatorio) -> str:
    partes = [f"Título: {rel.titulo}", f"Pedido/parâmetros: {json.dumps(rel.parametros, ensure_ascii=False)}",
              "Fatos calculados (JSON):\n" + json.dumps(rel.fatos, ensure_ascii=False, default=str)[:14000],
              "Premissas:\n" + "\n".join(f"- {p}" for p in rel.premissas)]
    for s in rel.secoes:
        for t in s.tabelas:
            linhas = ["| " + " | ".join(t.colunas) + " |"] + \
                     ["| " + " | ".join(formatar(v, t.formato(i)) for i, v in enumerate(l)) + " |" for l in t.linhas]
            partes.append(f"Tabela “{t.titulo}”:\n" + "\n".join(linhas))
    if rel.limitacoes:
        partes.append("Limitações conhecidas:\n" + "\n".join(f"- {l}" for l in rel.limitacoes))
    return "\n\n".join(partes)


def _json(texto: str) -> dict[str, Any]:
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    ini, fim = texto.find("{"), texto.rfind("}")
    return json.loads(texto[ini:fim + 1])


def redigir(rel: Relatorio, modo: str = "entregar", **extras: Any) -> Relatorio:
    """Preenche o resumo e a seção 'Análise' (no topo) conforme o modo. Mantém o resumo determinístico se falhar."""
    refs = referencias(rel)
    pedido = "\n\n".join([_contexto(rel), INSTRUCOES_MODO.get(modo, INSTRUCOES_MODO["entregar"]), FORMATO])
    estranhos: list[float] = []
    for tentativa in range(2):
        try:
            r = cerebro.perguntar(pedido, sistema=SISTEMA, temperatura=0.3, max_tokens=8000,
                                  response_format={"type": "json_object"}, **extras)
            dados = _json(r.texto)
        except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
            logging.warning("redação indisponível (%s): fica o resumo automático", type(e).__name__)
            rel.avisos.append("Texto analítico indisponível agora (limite dos modelos grátis): resumo automático.")
            return rel
        resumo = [str(x).strip() for x in dados.get("resumo") or [] if str(x).strip()][:5]
        analise = str(dados.get("analise") or "").strip()
        estranhos = conferir(" ".join(resumo) + " " + analise, refs)
        if not estranhos and resumo:
            break
        pedido += (f"\n\nATENÇÃO: no texto anterior apareceram números que NÃO estão nos dados: "
                   f"{', '.join(formatar(n, 'num') for n in estranhos[:8])}. Reescreva usando só os números fornecidos.")
    if resumo:
        rel.resumo = resumo
    if analise:
        titulo = {"entregar": "Análise", "debater": "Debate: prós, contras e perguntas",
                  "contestar": "Advogado do diabo"}.get(modo, "Análise")
        rel.secoes.insert(0, Secao(titulo, analise))
    if estranhos:
        rel.avisos.append("Números do texto não conferidos com os cálculos: "
                          + ", ".join(formatar(n, "num") for n in estranhos[:6]) + " — confie nas tabelas.")
    return rel
