"""Pacote para a versão offline: copia o índice da biblioteca, o modelo de embeddings e os dados de trabalho
(fichas, carteiras, reuniões, tarefas, Academia, cache de mercado) num único .tar.gz — gerado no servidor 24h (ou no PC
principal) e importado no PC offline. O cofre de clientes reais NUNCA entra no pacote (ele só existe no PC).

Bancos SQLite são copiados pela API de backup do SQLite (cópia consistente mesmo com o Quíron rodando)."""

from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
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
                with closing(sqlite3.connect(p)) as origem, closing(sqlite3.connect(copia)) as dest:
                    origem.backup(dest)  # fechadas antes do fim: no Windows, arquivo aberto não sai da pasta temporária
                tar.add(copia, arcname=rel)
            else:
                tar.add(p, arcname=rel)
    return destino


def _seguro(nome: str) -> bool:
    """Só caminhos simples dentro de dados/ ou biblioteca/ — nada de '..', absolutos, 'C:', '\\' ou '//'."""
    if not nome or ":" in nome or "\\" in nome or nome.startswith("/") or "//" in nome:
        return False
    partes = nome.rstrip("/").split("/")
    if partes[0] not in {"dados", "biblioteca"} or any(p in {"", ".", ".."} for p in partes):
        return False
    base = _origem(partes[0]).resolve()
    return _origem(nome.rstrip("/")).resolve().is_relative_to(base)


def importar(arquivo: Path) -> dict:
    """Extrai o pacote numa pasta temporária e só depois troca: o que existia vai para
    `dados/antes-da-importacao-<data>/`. Qualquer erro no meio desfaz a troca (nada fica pela metade)."""
    arquivo = Path(arquivo)
    agora = datetime.now()
    reserva = pasta_dados() / f"antes-da-importacao-{agora:%Y%m%d-%H%M%S}"
    copiados = 0
    with tarfile.open(arquivo, "r:gz") as tar:
        membros = [m for m in tar.getmembers() if (m.isfile() or m.isdir()) and _seguro(m.name)]
        if not membros:
            raise ValueError("pacote vazio ou inválido")
        topos = sorted({"/".join(m.name.rstrip("/").split("/")[:2]) for m in membros})
        pasta_dados().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=pasta_dados(), prefix=".importando-") as tmp:
            for m in membros:  # 1) extrai tudo à parte
                if not m.isfile():
                    continue
                destino = Path(tmp) / m.name
                destino.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as f, destino.open("wb") as d:
                    shutil.copyfileobj(f, d)
                copiados += 1
            feitos: list[tuple[Path, Path | None]] = []  # (atual, reserva) para desfazer
            try:  # 2) troca item por item
                for rel in topos:
                    atual, novo = _origem(rel), Path(tmp) / rel
                    guardado = None
                    if atual.exists():
                        guardado = reserva / rel
                        guardado.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(atual), guardado)
                    feitos.append((atual, guardado))
                    if novo.exists():
                        atual.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(novo), atual)
            except OSError as e:
                for atual, guardado in reversed(feitos):
                    if atual.exists():
                        shutil.rmtree(atual) if atual.is_dir() else atual.unlink()
                    if guardado is not None and guardado.exists():
                        shutil.move(str(guardado), atual)
                raise RuntimeError(f"importação desfeita (feche o Quíron e tente de novo): {e}") from e
    return {"arquivos": copiados, "itens": topos, "reserva": str(reserva) if reserva.exists() else ""}
