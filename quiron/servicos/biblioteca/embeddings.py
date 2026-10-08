"""Embeddings (vetores de significado) dos trechos.

- `fastembed` (padrão): modelo multilíngue leve rodando em ONNX, sem PyTorch — cabe no PC de 8 GB.
  Padrão: paraphrase-multilingual-MiniLM-L12-v2 (~220 MB, baixado uma vez do Hugging Face).
  No host 24h pode trocar por um mais robusto (QUIRON_MODELO_EMBEDDINGS).
- `lexico`: vetores por hashing de palavras, sem download. Usado nos testes e como plano B offline.
  Acha trechos que usam as mesmas palavras, mas não entende sinônimos.

Escolha por QUIRON_EMBEDDINGS=fastembed|lexico no `.env`.
"""

from __future__ import annotations

import gc
import hashlib
import math
import os
import re
import sys
import threading
import time
from functools import lru_cache
from typing import Protocol

from quiron.nucleo.config import pasta_dados
from quiron.servicos.biblioteca.trechos import chave

MODELO_PADRAO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embeddings(Protocol):
    nome: str

    def vetores(self, textos: list[str]) -> list[list[float]]: ...

    def vetor_consulta(self, texto: str) -> list[float]: ...


OCIOSO_S = float(os.environ.get("QUIRON_EMBEDDINGS_OCIOSO_S", "600"))


def _devolver_memoria() -> None:
    gc.collect()
    if sys.platform.startswith("linux"):  # devolve ao sistema a memória que o Python liberou (no Windows já é assim)
        try:
            import ctypes

            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


class FastEmbed:
    """O modelo ocupa ~640 MB (ONNX + tokenizador). Fica carregado enquanto é usado e sai da memória depois de
    `OCIOSO_S` segundos parado (o próximo uso recarrega em 1–3 s). Num PC de 8 GB com bot, Terminal e servidores MCP,
    isso evita 2 a 4 cópias paradas para sempre."""

    def __init__(self, modelo: str = MODELO_PADRAO):
        self.modelo = modelo
        self.nome = "fe-" + re.sub(r"[^a-z0-9]+", "-", modelo.split("/")[-1].lower())[:40]
        self._motor = None
        self._trava = threading.RLock()  # o escriba da memória usa em segundo plano, junto com a conversa
        self._uso = 0.0
        self._timer: threading.Timer | None = None

    def _agendar_descarga(self, espera: float) -> None:
        self._timer = threading.Timer(espera, self._descarregar)
        self._timer.daemon = True
        self._timer.start()

    def _descarregar(self) -> None:
        with self._trava:
            self._timer = None
            parado = time.monotonic() - self._uso
            if self._motor is None:
                return
            if parado < OCIOSO_S:  # foi usado nesse meio-tempo: confere de novo mais tarde
                self._agendar_descarga(OCIOSO_S - parado + 1)
                return
            self._motor = None
        _devolver_memoria()

    def _carregar(self):
        if self._motor is None:
            from fastembed import TextEmbedding

            pasta = pasta_dados() / "modelos"
            pasta.mkdir(parents=True, exist_ok=True)
            self._motor = TextEmbedding(self.modelo, cache_dir=str(pasta), threads=2)
        return self._motor

    def vetores(self, textos: list[str]) -> list[list[float]]:
        with self._trava:
            saida = [v.tolist() for v in self._carregar().embed(textos, batch_size=16)]
            self._uso = time.monotonic()
            if self._timer is None and OCIOSO_S > 0:
                self._agendar_descarga(OCIOSO_S)
        return saida

    def vetor_consulta(self, texto: str) -> list[float]:
        return self.vetores([texto])[0]


_PALAVRAS_VAZIAS = set(
    """a o as os um uma uns umas de da do das dos em na no nas nos por para com sem que e ou se ao aos à às
    é ser são foi como mais menos muito pelo pela pelos pelas entre sobre seu sua seus suas isso este esta
    the of and to in is for on with as by an be are or that this it from at""".split()
)


class Lexico:
    """Hashing de palavras (radical de até 6 letras) e pares de palavras. Determinístico e sem download."""

    def __init__(self, dim: int = 768):
        self.dim = dim
        self.nome = f"lexico-{dim}"

    def _tokens(self, texto: str) -> list[str]:
        palavras = [p[:6] for p in re.findall(r"[a-z0-9]+", chave(texto)) if p not in _PALAVRAS_VAZIAS and len(p) > 1]
        return palavras + [f"{a}_{b}" for a, b in zip(palavras, palavras[1:])]

    def _vetor(self, texto: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in self._tokens(texto):
            h = int.from_bytes(hashlib.md5(tok.encode()).digest()[:8], "little")
            v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norma = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norma for x in v]

    def vetores(self, textos: list[str]) -> list[list[float]]:
        return [self._vetor(t) for t in textos]

    def vetor_consulta(self, texto: str) -> list[float]:
        return self._vetor(texto)


@lru_cache(maxsize=4)
def _criar(tipo: str, modelo: str) -> Embeddings:
    if tipo == "lexico":
        return Lexico()
    if tipo == "fastembed":
        return FastEmbed(modelo)
    raise ValueError(f"QUIRON_EMBEDDINGS inválido: {tipo} (use fastembed ou lexico)")


def obter_embeddings() -> Embeddings:
    tipo = (os.environ.get("QUIRON_EMBEDDINGS") or "fastembed").strip().lower()
    modelo = (os.environ.get("QUIRON_MODELO_EMBEDDINGS") or MODELO_PADRAO).strip()
    return _criar(tipo, modelo)


def similaridade(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0
