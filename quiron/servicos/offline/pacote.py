"""Pacote para a versão offline: copia o índice da biblioteca, o modelo de embeddings e os dados de trabalho
(fichas, carteiras, reuniões, tarefas, Academia, cache de mercado) num único .tar.gz — gerado no servidor 24h (ou no PC
principal) e importado no PC offline. O cofre de clientes reais NUNCA entra no pacote (ele só existe no PC).

Bancos SQLite são copiados pela API de backup do SQLite (cópia consistente mesmo com o Quíron rodando)."""

from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from quiron.nucleo import offline
from quiron.nucleo.config import RAIZ, pasta_biblioteca, pasta_dados


def _origem(rel: str) -> Path:
    """'dados/x' e 'biblioteca/x' respeitam QUIRON_DADOS e QUIRON_BIBLIOTECA."""
    raiz, _, resto = rel.partition("/")
    base = {"dados": pasta_dados(), "biblioteca": pasta_biblioteca()}.get(raiz, RAIZ / raiz)
    return base / resto if resto else base


def gerar(destino: Path | None = None) -> Path:
    cfg = offline.config().get("pacote", {})
    destino = destino or pasta_dados() / "exportacoes" / f"quiron-offline-{datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(destino, "w:gz") as tar:
        for rel in cfg.get("pastas", []):
            p = _origem(rel)
            if p.exists():
                tar.add(p, arcname=rel)
        for rel in cfg.get("arquivos", []):
            p = _origem(rel)
            if not p.exists():
                continue
            if p.suffix == ".db":
                copia = Path(tmp) / p.name
                with sqlite3.connect(p) as origem, sqlite3.connect(copia) as dest:
                    origem.backup(dest)
                tar.add(copia, arcname=rel)
            else:
                tar.add(p, arcname=rel)
    return destino


def _seguro(nome: str) -> bool:
    caminho = Path(nome)
    return not caminho.is_absolute() and ".." not in caminho.parts and caminho.parts[0] in {"dados", "biblioteca"}


def importar(arquivo: Path) -> dict:
    """Extrai o pacote. O que já existia e seria sobrescrito vai antes para `dados/antes-da-importacao-<data>/`."""
    arquivo = Path(arquivo)
    reserva = pasta_dados() / f"antes-da-importacao-{datetime.now():%Y%m%d-%H%M%S}"
    copiados = 0
    with tarfile.open(arquivo, "r:gz") as tar:
        membros = [m for m in tar.getmembers() if (m.isfile() or m.isdir()) and _seguro(m.name)]
        if not membros:
            raise ValueError("pacote vazio ou inválido")
        topos = sorted({"/".join(Path(m.name).parts[:2]) for m in membros})
        for rel in topos:  # guarda o que vai ser substituído
            atual = _origem(rel)
            if atual.exists():
                alvo = reserva / rel
                alvo.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(atual), alvo)
        for m in membros:
            if not m.isfile():
                continue
            destino = _origem(m.name)
            destino.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as f, destino.open("wb") as d:
                shutil.copyfileobj(f, d)
            copiados += 1
    return {"arquivos": copiados, "itens": topos, "reserva": str(reserva) if reserva.exists() else ""}
