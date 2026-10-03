"""Índice vetorial (Chroma) + catálogo de livros (JSON) da biblioteca."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quiron.nucleo.config import pasta_biblioteca
from quiron.servicos.biblioteca.embeddings import Embeddings, obter_embeddings
from quiron.servicos.biblioteca.trechos import Trecho, chave


@dataclass
class Resultado:
    texto: str
    meta: dict[str, Any]
    semelhanca: float  # 0 a 1 (1 = idêntico)

    @property
    def citacao(self) -> str:
        return citacao(self.meta)


def citacao(meta: dict[str, Any]) -> str:
    partes = [f"📚 {meta.get('titulo')} — {meta.get('autor')}"]
    if meta.get("capitulo"):
        partes.append(f"cap. \"{meta['capitulo']}\"")
    ini, fim = meta.get("pagina_inicio") or 0, meta.get("pagina_fim") or 0
    if ini:
        partes.append(f"p. {ini}" if not fim or fim == ini else f"p. {ini}–{fim}")
    return ", ".join(partes)


class Indice:
    def __init__(self, raiz: Path | None = None, emb: Embeddings | None = None):
        self.raiz = raiz or pasta_biblioteca()
        self.emb = emb or obter_embeddings()
        self.pasta_indice = self.raiz / "indice"
        self.pasta_indice.mkdir(parents=True, exist_ok=True)
        self.arquivo_catalogo = self.pasta_indice / "catalogo.json"
        self._colecao = None

    # ------------------------------------------------------------ catálogo
    def catalogo(self) -> dict[str, dict]:
        if not self.arquivo_catalogo.exists():
            return {}
        return json.loads(self.arquivo_catalogo.read_text(encoding="utf-8"))

    def salvar_catalogo(self, cat: dict[str, dict]) -> None:
        self.arquivo_catalogo.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")

    def achar_livro(self, termo: str) -> dict | None:
        """Por id exato ou parte do título (sem acento/maiúsculas)."""
        cat = self.catalogo()
        if termo in cat:
            return cat[termo]
        k = chave(termo)
        candidatos = [l for l in cat.values() if k in chave(l["titulo"])]
        return candidatos[0] if len(candidatos) >= 1 else None

    # ------------------------------------------------------------ Chroma
    @property
    def colecao(self):
        if self._colecao is None:
            import chromadb
            from chromadb.config import Settings

            cliente = chromadb.PersistentClient(path=str(self.pasta_indice / "chroma"), settings=Settings(anonymized_telemetry=False))
            self._colecao = cliente.get_or_create_collection(f"trechos-{self.emb.nome}", metadata={"hnsw:space": "cosine"})
        return self._colecao

    def adicionar(self, trechos: list[Trecho], vetores: list[list[float]]) -> None:
        for i in range(0, len(trechos), 500):
            lote = trechos[i : i + 500]
            self.colecao.add(
                ids=[t.id for t in lote],
                documents=[t.texto for t in lote],
                metadatas=[t.metadados() for t in lote],
                embeddings=vetores[i : i + 500],
            )

    def remover_livro(self, livro_id: str) -> None:
        self.colecao.delete(where={"livro_id": livro_id})

    def total_trechos(self) -> int:
        return self.colecao.count()

    def buscar(
        self, consulta: str, n: int = 6, *, livro_id: str | None = None, autor: str | None = None, bloco: int | None = None
    ) -> list[Resultado]:
        if self.total_trechos() == 0:
            return []
        filtros: list[dict] = []
        if livro_id:
            filtros.append({"livro_id": livro_id})
        if autor:
            filtros.append({"autor_chave": chave(autor)})
        if bloco is not None:
            filtros.append({"bloco": int(bloco)})
        where = None if not filtros else filtros[0] if len(filtros) == 1 else {"$and": filtros}
        r = self.colecao.query(
            query_embeddings=[self.emb.vetor_consulta(consulta)],
            n_results=min(n, self.total_trechos()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            Resultado(doc, meta, max(0.0, 1.0 - dist))
            for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])
        ]

    def todos(self, incluir_vetores: bool = False, where: dict | None = None) -> dict:
        include = ["metadatas", "documents"] + (["embeddings"] if incluir_vetores else [])
        return self.colecao.get(where=where, include=include)

    def atualizar_blocos(self, ids: list[str], metadados: list[dict]) -> None:
        for i in range(0, len(ids), 500):
            self.colecao.update(ids=ids[i : i + 500], metadatas=metadados[i : i + 500])
