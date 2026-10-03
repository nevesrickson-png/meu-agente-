"""Os 22 blocos do guia de estudo do Rickson (`config/guia_22_blocos.yaml`).

Cada trecho da biblioteca é ligado ao bloco mais parecido (por embeddings), se a semelhança passar do limiar.
Blocos ainda sem nome no YAML são ignorados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos.biblioteca.embeddings import Embeddings, similaridade

ARQUIVO_GUIA = PASTA_CONFIG / "guia_22_blocos.yaml"


@dataclass
class Bloco:
    id: int
    nome: str
    descricao: str = ""
    palavras_chave: list[str] = field(default_factory=list)

    @property
    def texto_referencia(self) -> str:
        return " ".join([self.nome, self.descricao, " ".join(self.palavras_chave)]).strip()


@dataclass
class Guia:
    blocos: list[Bloco]
    limiar: float

    def nome(self, bloco_id: int) -> str:
        for b in self.blocos:
            if b.id == bloco_id:
                return f"Bloco {b.id} — {b.nome}"
        return "Sem bloco"


def carregar_guia(caminho: Path | None = None) -> Guia:
    caminho = caminho or ARQUIVO_GUIA
    if not caminho.exists():
        return Guia([], 0.3)
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    blocos = [
        Bloco(int(b["id"]), str(b.get("nome") or "").strip(), str(b.get("descricao") or "").strip(), list(b.get("palavras_chave") or []))
        for b in dados.get("blocos", [])
        if str(b.get("nome") or "").strip()
    ]
    return Guia(blocos, float(dados.get("limiar_semelhanca", 0.3)))


def classificar(vetores: list[list[float]], guia: Guia, emb: Embeddings) -> list[int]:
    """Bloco mais parecido para cada vetor (0 = nenhum passou do limiar)."""
    if not guia.blocos:
        return [0] * len(vetores)
    refs = emb.vetores([b.texto_referencia for b in guia.blocos])
    saida = []
    for v in vetores:
        notas = [similaridade(v, r) for r in refs]
        melhor = max(range(len(notas)), key=notas.__getitem__)
        saida.append(guia.blocos[melhor].id if notas[melhor] >= guia.limiar else 0)
    return saida
