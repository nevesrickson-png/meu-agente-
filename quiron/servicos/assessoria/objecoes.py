"""Biblioteca de objeções (`config/objecoes.yaml`): acha a mais parecida com o que o cliente disse."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from quiron.nucleo.config import ler_yaml


def _norm(t: str) -> set[str]:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return {p for p in re.findall(r"[a-z0-9]+", t) if len(p) > 2}


def todas() -> dict[str, dict[str, Any]]:
    return ler_yaml("objecoes")["objecoes"]


def buscar(texto: str, limite: int = 2) -> list[tuple[str, dict[str, Any]]]:
    alvo = _norm(texto)
    notas = []
    for k, o in todas().items():
        frases = [_norm(f) for f in o["frases"]]
        melhor = max((len(alvo & f) / len(f) for f in frases if f), default=0.0)
        notas.append((melhor + 0.1 * len(alvo & _norm(k.replace("_", " "))), k, o))
    notas.sort(key=lambda x: -x[0])
    return [(k, o) for nota, k, o in notas[:limite] if nota >= 0.34]


def descrever(k: str, o: dict[str, Any]) -> str:
    linhas = [f"Objeção: {k.replace('_', ' ')} (ex.: “{o['frases'][0]}”)", f"Por trás, costuma haver: {o['por_tras']}",
              "Perguntas para entender: " + " · ".join(o["perguntas"]), f"Reenquadrar: {o['reenquadrar']}"]
    if o.get("evidencias"):
        linhas.append("Evidências a usar (com números do caso): " + " · ".join(o["evidencias"]))
    linhas.append("Evitar: " + " · ".join(o["evitar"]))
    return "\n".join(linhas)
