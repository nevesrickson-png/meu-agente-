"""Última barreira de LGPD antes de qualquer modelo na NUVEM (camada gratuita pode guardar o que recebe).

O agente já recusa a pergunta com CPF/telefone/e-mail, mas o mesmo dado pode chegar por outros caminhos: histórico
de comandos diretos (/tarefa … (11) 98888-7777), resultado de ferramenta (tarefas, notas, conversas), escriba da
memória. `cerebro` passa tudo por `mascarar` quando o modelo não é local. Os padrões exigem a FORMA de um dado
pessoal (parênteses, hífen, pontos, +55, "CPF", @) para não apagar números financeiros de 10–11 dígitos."""

from __future__ import annotations

import re
from typing import Any

_PADROES = [
    ("[e-mail]", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("[CPF]", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\bcpf\W{0,3}\d[\d.\s-]{9,13}\d", re.I)),
    ("[telefone]", re.compile(r"(?:\+\s?55\s?)?\(\d{2}\)\s?9?\s?\d{4}[\s.-]?\d{4}\b"
                              r"|(?:\+\s?55\s?)?\b\d{2}[\s.-]9?\s?\d{4}[\s.-]\d{4}\b"
                              r"|\+\s?55\s?\d{10,11}\b")),
]
_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")  # CNPJ de fundo/empresa é público


def mascarar(texto: str) -> str:
    if not texto:
        return texto
    guardados: list[str] = []

    def guardar(m: re.Match) -> str:
        guardados.append(m.group(0))
        return f"\x00{len(guardados) - 1}\x00"

    t = _CNPJ.sub(guardar, texto)
    for rotulo, padrao in _PADROES:
        t = padrao.sub(rotulo, t)
    return re.sub(r"\x00(\d+)\x00", lambda m: guardados[int(m.group(1))], t)


def mascarar_mensagens(mensagens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cópia das mensagens com o texto mascarado (o original fica intacto para o histórico local)."""
    saida = []
    for m in mensagens:
        c = m.get("content")
        if isinstance(c, str):
            m = {**m, "content": mascarar(c)}
        elif isinstance(c, list):  # partes (texto + imagem)
            m = {**m, "content": [{**p, "text": mascarar(p["text"])} if isinstance(p, dict) and isinstance(p.get("text"), str)
                                  else p for p in c]}
        saida.append(m)
    return saida
