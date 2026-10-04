"""Edital/programa oficial de cada certificação → mapa de tópicos (`config/editais/<ID>.yaml`).

O mapa é a espinha da Academia: aulas, questões, simulados, diagnóstico e plano de estudo apontam para códigos
de tópico (ex.: CFP `3.5.2`). O YAML é gerado do PDF oficial e depois pode ser editado à mão.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from quiron.nucleo.config import PASTA_CONFIG

PASTA_EDITAIS = PASTA_CONFIG / "editais"
RE_CODIGO = re.compile(r"^(\d+(?:\.\d+)+)\.?(?:\s+(.*))?$")
RE_MODULO = re.compile(r"^M[óo]dulo\s+(\d+)\s*[-–]\s*(.+)$", re.I)
RE_PESO = re.compile(r"^Peso:\s*(\d+)\s*%", re.I)
MARCADORES = ("•", "", "▪", "-", "–")


@dataclass
class Topico:
    codigo: str
    titulo: str
    itens: list[str] = field(default_factory=list)

    @property
    def nivel(self) -> int:
        return self.codigo.count(".")

    @property
    def modulo(self) -> str:
        return self.codigo.split(".")[0]


def _limpa(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\t", " ")).strip()


def extrair_programa(texto: str) -> dict[str, Any]:
    """Lê o texto do "Programa Detalhado" (CFP/Planejar) e devolve módulos com peso e tópicos numerados."""
    linhas = [_limpa(l) for l in texto.splitlines()]
    modulos: dict[str, dict[str, Any]] = {}
    topicos: list[Topico] = []
    atual: str | None = None
    i = 0
    while i < len(linhas):
        l = linhas[i]
        if m := RE_MODULO.match(l):
            numero, titulo = m.group(1), m.group(2)
            if i + 2 < len(linhas) and linhas[i + 1] and not RE_PESO.match(linhas[i + 1]) and RE_PESO.match(linhas[i + 2]):
                titulo += " " + linhas[i + 1]  # título quebrado em duas linhas
                i += 1
            # o índice também tem "Módulo N - ..." com número de página no fim: só vale se o peso vier logo depois
            prox = next((x for x in linhas[i + 1:i + 4] if x), "")
            if p := RE_PESO.match(prox):
                atual = numero
                modulos[numero] = {"numero": int(numero), "titulo": _limpa(re.sub(r"\s+\d+$", "", titulo)),
                                   "peso": int(p.group(1))}
        elif atual and (m := RE_CODIGO.match(l)) and m.group(1).split(".")[0] == atual:
            titulo = m.group(2) or ""
            j = i
            while not titulo and j + 1 < len(linhas):  # código sozinho na linha: o título vem depois
                j += 1
                titulo = linhas[j]
            while j + 1 < len(linhas) and linhas[j + 1] and linhas[j + 1][0].islower() and len(titulo) < 120:
                j += 1
                titulo += " " + linhas[j]  # continuação do título
            topicos.append(Topico(m.group(1), titulo.rstrip(" :")))
            i = j
        elif atual and topicos and l in MARCADORES:
            j = i + 1
            while j < len(linhas) and not linhas[j]:
                j += 1
            if j < len(linhas) and not RE_CODIGO.match(linhas[j]):
                topicos[-1].itens.append(linhas[j].rstrip(" ;."))
                i = j
        elif atual and topicos and l[:1] in MARCADORES and len(l) > 2:
            topicos[-1].itens.append(l[1:].strip().rstrip(" ;."))
        i += 1
    vistos: set[str] = set()
    unicos = [t for t in topicos if not (t.codigo in vistos or vistos.add(t.codigo))]
    return {"modulos": [modulos[k] | {"topicos": [{"codigo": t.codigo, "titulo": t.titulo, **({"itens": t.itens} if t.itens else {})}
                                                  for t in unicos if t.modulo == k]}
                        for k in sorted(modulos, key=int)]}


# ---------------------------------------------------------------- leitura do YAML
@lru_cache(maxsize=8)
def carregar(cert: str = "CFP") -> dict[str, Any]:
    arq = PASTA_EDITAIS / f"{cert.upper()}.yaml"
    if not arq.exists():
        raise FileNotFoundError(f"Edital de {cert} ainda não mapeado ({arq.name}).")
    return yaml.safe_load(arq.read_text(encoding="utf-8"))


def modulos(cert: str = "CFP") -> list[dict[str, Any]]:
    return carregar(cert)["modulos"]


def topico(codigo: str, cert: str = "CFP") -> dict[str, Any] | None:
    for m in modulos(cert):
        for t in m["topicos"]:
            if t["codigo"] == codigo:
                return t | {"modulo": m["numero"], "modulo_titulo": m["titulo"]}
    return None


def topicos(cert: str = "CFP", nivel_max: int = 9, modulo: int | None = None) -> list[dict[str, Any]]:
    return [t | {"modulo": m["numero"]} for m in modulos(cert) if modulo in (None, m["numero"])
            for t in m["topicos"] if t["codigo"].count(".") <= nivel_max]


def filhos(codigo: str, cert: str = "CFP") -> list[dict[str, Any]]:
    return [t for t in topicos(cert) if t["codigo"].startswith(codigo + ".")]


def buscar(termo: str, cert: str = "CFP", limite: int = 10) -> list[dict[str, Any]]:
    """Busca tópicos pelo título/itens (sem acento, por palavras)."""
    from unicodedata import normalize

    def n(s: str) -> str:
        return normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()

    palavras = n(termo).split()
    achados = []
    for t in topicos(cert):
        alvo = n(t["titulo"] + " " + " ".join(t.get("itens", [])))
        pontos = sum(p in alvo for p in palavras)
        if pontos:
            achados.append((pontos, -t["codigo"].count("."), t))
    achados.sort(key=lambda x: (-x[0], -x[1]))
    return [t for _, _, t in achados[:limite]]
