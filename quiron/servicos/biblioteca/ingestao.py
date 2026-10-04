"""Ingestão da biblioteca: `biblioteca/entrada/` → texto → trechos → embeddings → índice → fichas e relatório.

Livros já processados (mesmo conteúdo, pelo hash) são pulados. Processa um livro por vez e
os embeddings em lotes pequenos, para caber no PC de 8 GB.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from quiron.servicos.biblioteca import fichas
from quiron.servicos.biblioteca.blocos import Guia, carregar_guia, classificar
from quiron.servicos.biblioteca.extracao import FORMATOS, ArquivoProtegido, OCRIndisponivel, extrair
from quiron.servicos.biblioteca.indice import Indice
from quiron.servicos.biblioteca.trechos import chave, dividir

LOTE_EMBEDDINGS = 32


@dataclass
class ResultadoLivro:
    arquivo: str
    situacao: str  # "ingerido", "já estava", "pulado (DRM)", "precisa de OCR", "erro"
    detalhe: str = ""
    livro_id: str | None = None


@dataclass
class Relatorio:
    livros: list[ResultadoLivro] = field(default_factory=list)

    def resumo(self) -> str:
        cont = Counter(l.situacao for l in self.livros)
        return ", ".join(f"{v} {k}" for k, v in cont.items()) or "nenhum livro encontrado em biblioteca/entrada"


def _hash(arquivo: Path) -> str:
    h = hashlib.sha256()
    with arquivo.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", chave(texto)).strip("-")[:40]


def area_do_arquivo(arquivo: Path, raiz: Path) -> str:
    """Área pela pasta: biblioteca/acervo/<área>/x.pdf ou academia/material/<área>/x.pdf → ÁREA ('' se fora)."""
    from quiron.nucleo.config import RAIZ

    partes: tuple[str, ...] = ()
    for base in (raiz / "acervo", RAIZ / "academia" / "material"):
        try:
            partes = arquivo.resolve().relative_to(base.resolve()).parts
            break
        except ValueError:
            continue
    if len(partes) < 2:
        return ""
    from quiron.servicos import areas

    a = areas.obter(partes[0])
    return a.id if a else partes[0].upper()


def ingerir_arquivo(arquivo: Path, indice: Indice, guia: Guia, forcar: bool = False, area: str | None = None) -> ResultadoLivro:
    sha = _hash(arquivo)
    area = area if area is not None else area_do_arquivo(arquivo, indice.raiz)
    cat = indice.catalogo()
    existente = next((l for l in cat.values() if l["sha256"] == sha), None)
    if existente and not forcar:
        if area and existente.get("area") != area:  # mesmo livro, agora numa pasta de área: só reclassifica
            indice.definir_area(existente["id"], area)
            cat[existente["id"]]["area"] = area
            indice.salvar_catalogo(cat)
            return ResultadoLivro(arquivo.name, "área atualizada", f"{existente['titulo']} → {area}", existente["id"])
        return ResultadoLivro(arquivo.name, "já estava", existente["titulo"], existente["id"])
    try:
        livro = extrair(arquivo, indice.raiz / "texto")
    except ArquivoProtegido as e:
        return ResultadoLivro(arquivo.name, "pulado (DRM)", str(e))
    except OCRIndisponivel as e:
        return ResultadoLivro(arquivo.name, "precisa de OCR", str(e))

    livro_id = f"{_slug(livro.titulo)}-{sha[:8]}"
    trechos = dividir(livro, livro_id)
    if not trechos:
        return ResultadoLivro(arquivo.name, "erro", "nenhum texto aproveitável (arquivo vazio ou só imagens?)")

    vetores: list[list[float]] = []
    for i in range(0, len(trechos), LOTE_EMBEDDINGS):
        vetores += indice.emb.vetores([t.texto for t in trechos[i : i + LOTE_EMBEDDINGS]])
    for t, b in zip(trechos, classificar(vetores, guia, indice.emb)):
        t.bloco = b
        t.area = area

    indice.remover_livro(livro_id)
    indice.adicionar(trechos, vetores)

    paginas = [p.numero for p in livro.paginas if p.numero]
    info = {
        "id": livro_id,
        "titulo": livro.titulo,
        "autor": livro.autor,
        "arquivo": arquivo.name,
        "area": area,
        "formato": livro.formato,
        "sha256": sha,
        "paginas": max(paginas) if paginas else None,
        "secoes": len(livro.paginas),
        "trechos": len(trechos),
        "ocr": livro.ocr,
        "capitulos": livro.capitulos,
        "blocos": {str(k): v for k, v in sorted(Counter(t.bloco for t in trechos).items())},
        "ingerido_em": datetime.now().isoformat(timespec="seconds"),
    }
    cat = indice.catalogo()
    cat[livro_id] = info
    indice.salvar_catalogo(cat)
    fichas.gravar_ficha(info, guia, indice)
    detalhe = f"{livro.titulo} — {livro.autor}: {len(trechos)} trechos" + (" (com OCR)" if livro.ocr else "")
    return ResultadoLivro(arquivo.name, "ingerido", detalhe, livro_id)


def ingerir_pasta(indice: Indice | None = None, guia: Guia | None = None, entrada: Path | None = None, forcar: bool = False,
                  recursivo: bool = False) -> Relatorio:
    indice = indice or Indice()
    guia = guia or carregar_guia()
    entrada = entrada or indice.raiz / "entrada"
    relatorio = Relatorio()
    for arquivo in sorted(entrada.rglob("*") if recursivo else entrada.glob("*")):
        if not arquivo.is_file():
            continue
        if arquivo.suffix.lower() not in FORMATOS or arquivo.name.endswith(".ocr.pdf"):
            continue
        try:
            relatorio.livros.append(ingerir_arquivo(arquivo, indice, guia, forcar))
        except Exception as e:  # noqa: BLE001 — um livro com problema não derruba os outros
            relatorio.livros.append(ResultadoLivro(arquivo.name, "erro", f"{type(e).__name__}: {e}"))
    fichas.gravar_relatorio(relatorio, guia, indice)
    return relatorio


def reclassificar_blocos(indice: Indice | None = None, guia: Guia | None = None) -> dict[int, int]:
    """Religa todos os trechos aos blocos do guia (use depois de editar o guia_22_blocos.yaml)."""
    indice = indice or Indice()
    guia = guia or carregar_guia()
    dados = indice.todos(incluir_vetores=True)
    if not dados["ids"]:
        return {}
    novos = classificar([list(v) for v in dados["embeddings"]], guia, indice.emb)
    metas = [{**m, "bloco": b} for m, b in zip(dados["metadatas"], novos)]
    indice.atualizar_blocos(list(dados["ids"]), metas)
    cat = indice.catalogo()
    for livro_id, info in cat.items():
        cont = Counter(b for m, b in zip(dados["metadatas"], novos) if m["livro_id"] == livro_id)
        info["blocos"] = {str(k): v for k, v in sorted(cont.items())}
        fichas.gravar_ficha(info, guia, indice)
    indice.salvar_catalogo(cat)
    return dict(Counter(novos))
