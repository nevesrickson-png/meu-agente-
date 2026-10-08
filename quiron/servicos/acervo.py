"""Acervo: arquivos enviados pela tela do Terminal, guardados por área e processados para a biblioteca.

- Pastas: `biblioteca/acervo/<área>/` (ex.: `acervo/economia/`, `acervo/cfp/`). Arquivos colocados à mão nessas
  pastas também entram (a fila confere a pasta ao ligar).
- Fila em `dados/acervo.db`: cada arquivo passa por na_fila → processando → pronto (ou erro/precisa de OCR/DRM).
- Um único processador em segundo plano (o embeddings e o OCR são pesados: um livro por vez).
- O trecho de cada livro guarda a área (`area`) para buscas e para a Academia citar o material da área certa.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from quiron.nucleo.config import pasta_biblioteca, pasta_dados
from quiron.servicos import areas

FORMATOS = {".pdf", ".epub"}
LIMITE_BYTES = 300 * 1024 * 1024  # 300 MB por arquivo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS arquivos (
  id INTEGER PRIMARY KEY, area TEXT NOT NULL, nome TEXT NOT NULL, caminho TEXT NOT NULL UNIQUE, tamanho INTEGER,
  enviado_em TEXT NOT NULL, situacao TEXT NOT NULL DEFAULT 'na fila', detalhe TEXT DEFAULT '', livro_id TEXT DEFAULT '',
  atualizado_em TEXT
);
"""


class AcervoErro(ValueError):
    pass


def pasta_acervo() -> Path:
    return pasta_biblioteca() / "acervo"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def nome_seguro(nome: str) -> str:
    """Só o nome do arquivo (sem pastas), sem caracteres estranhos, com a extensão em minúsculas."""
    nome = Path(nome.replace("\\", "/")).name
    nome = unicodedata.normalize("NFC", nome)
    base, ext = Path(nome).stem, Path(nome).suffix.lower()
    base = re.sub(r"[^\w\s().,'-]+", "", base, flags=re.UNICODE).strip(" .")[:120] or "arquivo"
    return f"{base}{ext}"


@dataclass
class Registro:
    id: int
    area: str
    nome: str
    caminho: str
    tamanho: int
    enviado_em: str
    situacao: str
    detalhe: str
    livro_id: str


class Acervo:
    def __init__(self, banco: Path | None = None):
        self.banco = banco or pasta_dados() / "acervo.db"
        self.banco.parent.mkdir(parents=True, exist_ok=True)
        with self._con() as c:
            c.executescript(ESQUEMA)
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self._processador: threading.Thread | None = None

    @contextmanager
    def _con(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.banco, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------ áreas
    def resumo_areas(self) -> list[dict[str, Any]]:
        with self._con() as c:
            contagem = {r["area"]: (r["n"], r["prontos"]) for r in c.execute(
                "SELECT area, COUNT(*) n, SUM(situacao IN ('pronto','já estava','área atualizada')) prontos "
                "FROM arquivos WHERE situacao != 'removido' GROUP BY area")}
        saida = []
        for a in areas.listar():
            n, prontos = contagem.get(a.id, (0, 0))
            saida.append({"id": a.id, "nome": a.nome, "tipo": a.tipo, "descricao": a.descricao, "pasta": a.pasta,
                          "arquivos": n, "prontos": prontos or 0, "personalizada": a.personalizada})
        return saida

    # ------------------------------------------------------------ envio
    def destino(self, area_id: str, nome: str) -> tuple[areas.Area, Path]:
        area = areas.obter(area_id)
        if not area:
            raise AcervoErro(f"Área “{area_id}” não existe.")
        nome = nome_seguro(nome)
        if Path(nome).suffix not in FORMATOS:
            raise AcervoErro(f"{nome}: por enquanto só PDF e EPUB.")
        pasta = pasta_acervo() / area.pasta
        pasta.mkdir(parents=True, exist_ok=True)
        alvo, i = pasta / nome, 2
        while alvo.exists():  # nunca sobrescreve: "livro (2).pdf"
            alvo = pasta / f"{Path(nome).stem} ({i}){Path(nome).suffix}"
            i += 1
        return area, alvo

    def _publicar(self, temp: Path, alvo: Path) -> Path:
        """Põe o temporário no nome final SEM sobrescrever: dois envios com o mesmo nome ao mesmo tempo ganham
        "livro.pdf" e "livro (2).pdf" (o nome é reservado de forma atômica pelo sistema de arquivos)."""
        base, i = alvo, 2
        while True:
            try:
                os.link(temp, alvo)  # falha se o nome já existe
                return alvo  # o temporário é apagado por quem chamou (finally) — erro ao apagá-lo não republica
            except FileExistsError:
                pass
            except OSError:  # sistema de arquivos sem link: reserva exclusiva + troca
                try:
                    os.close(os.open(alvo, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                    os.replace(temp, alvo)
                    return alvo
                except FileExistsError:
                    pass
            alvo = base.with_name(f"{Path(base.name).stem} ({i}){base.suffix}")
            i += 1

    def _temporario(self, alvo: Path) -> Path:
        fd, nome = tempfile.mkstemp(prefix=f".{alvo.name}.", suffix=".parcial", dir=alvo.parent)
        os.close(fd)
        return Path(nome)

    def registrar(self, area_id: str, caminho: Path) -> int:
        with self._con() as c:
            cur = c.execute("INSERT INTO arquivos (area, nome, caminho, tamanho, enviado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
                            (area_id, caminho.name, str(caminho), caminho.stat().st_size, _agora(), _agora()))
            ident = int(cur.lastrowid)
        self.acordar()
        return ident

    def salvar(self, area_id: str, nome: str, conteudo: bytes) -> int:
        """Grava um arquivo inteiro de uma vez (uso em testes e scripts). A tela usa `salvar_em_partes`."""
        if len(conteudo) > LIMITE_BYTES:
            raise AcervoErro("Arquivo grande demais (máximo 300 MB).")
        area, alvo = self.destino(area_id, nome)
        temp = self._temporario(alvo)
        try:
            temp.write_bytes(conteudo)
            alvo = self._publicar(temp, alvo)
        finally:
            temp.unlink(missing_ok=True)
        return self.registrar(area.id, alvo)

    async def salvar_em_partes(self, area_id: str, nome: str, partes) -> int:
        """Grava o corpo da requisição aos pedaços (sem carregar 300 MB na memória)."""
        area, alvo = self.destino(area_id, nome)
        temp = self._temporario(alvo)  # nome único: dois envios simultâneos não escrevem no mesmo arquivo
        total = 0
        try:
            with temp.open("wb") as f:
                async for pedaco in partes:
                    total += len(pedaco)
                    if total > LIMITE_BYTES:
                        raise AcervoErro("Arquivo grande demais (máximo 300 MB).")
                    f.write(pedaco)
            if total == 0:
                raise AcervoErro("Arquivo vazio.")
            alvo = self._publicar(temp, alvo)
        finally:
            temp.unlink(missing_ok=True)
        return self.registrar(area.id, alvo)

    # ------------------------------------------------------------ consulta e ajustes
    def listar(self, limite: int = 200, area: str | None = None) -> list[Registro]:
        sql = "SELECT * FROM arquivos WHERE situacao != 'removido'" + (" AND area=?" if area else "") + " ORDER BY id DESC LIMIT ?"
        with self._con() as c:
            rows = c.execute(sql, (area, limite) if area else (limite,)).fetchall()
        return [Registro(r["id"], r["area"], r["nome"], r["caminho"], r["tamanho"] or 0, r["enviado_em"], r["situacao"],
                         r["detalhe"] or "", r["livro_id"] or "") for r in rows]

    def obter(self, ident: int) -> Registro | None:
        return next((r for r in self.listar(10_000) if r.id == ident), None)

    def _atualizar(self, ident: int, **campos: Any) -> None:
        campos["atualizado_em"] = _agora()
        with self._con() as c:
            c.execute(f"UPDATE arquivos SET {', '.join(f'{k}=?' for k in campos)} WHERE id=?", (*campos.values(), ident))

    def mover(self, ident: int, nova_area: str) -> Registro:
        """Troca a área de um arquivo (pasta + metadados na biblioteca, sem reprocessar)."""
        r = self.obter(ident)
        area = areas.obter(nova_area)
        if not r or not area:
            raise AcervoErro("Arquivo ou área inexistente.")
        _, alvo = self.destino(area.id, r.nome)
        if Path(r.caminho).exists():
            shutil.move(r.caminho, alvo)
        self._atualizar(ident, area=area.id, caminho=str(alvo), nome=alvo.name)
        if r.livro_id:
            from quiron.servicos.biblioteca.indice import Indice

            indice = Indice()
            indice.definir_area(r.livro_id, area.id)
            cat = indice.catalogo()
            if r.livro_id in cat:
                cat[r.livro_id]["area"] = area.id
                indice.salvar_catalogo(cat)
        return self.obter(ident)  # type: ignore[return-value]

    def remover(self, ident: int) -> None:
        """Tira o arquivo do acervo e os trechos dele da biblioteca."""
        r = self.obter(ident)
        if not r:
            raise AcervoErro("Arquivo inexistente.")
        if r.livro_id:
            from quiron.servicos.biblioteca.indice import Indice

            indice = Indice()
            outros = [x for x in self.listar(10_000) if x.livro_id == r.livro_id and x.id != ident]
            nome_cat = str((indice.catalogo().get(r.livro_id) or {}).get("arquivo") or "")
            de_fora = bool(nome_cat) and (pasta_biblioteca() / "entrada" / nome_cat).exists()  # ingerido de lá antes
            if not outros and not de_fora:  # o mesmo livro pode ter sido enviado duas vezes ou vir de biblioteca/entrada
                indice.remover_livro(r.livro_id)
                cat = indice.catalogo()
                cat.pop(r.livro_id, None)
                indice.salvar_catalogo(cat)
        Path(r.caminho).unlink(missing_ok=True)
        self._atualizar(ident, situacao="removido")

    def conferir_pastas(self) -> int:
        """Põe na fila os arquivos colocados à mão em biblioteca/acervo/<área>/."""
        conhecidos = {r.caminho for r in self.listar(100_000)}
        with self._con() as c:
            conhecidos |= {r[0] for r in c.execute("SELECT caminho FROM arquivos")}
        novos = 0
        raiz = pasta_acervo()
        if not raiz.exists():
            return 0
        for arq in sorted(raiz.glob("*/*")):
            if arq.suffix.lower() in FORMATOS and str(arq) not in conhecidos and not arq.name.endswith(".ocr.pdf"):
                area = areas.obter(arq.parent.name)
                if area:
                    try:
                        tamanho = arq.stat().st_size
                    except OSError:
                        continue  # movido/apagado entre a listagem e agora
                    with self._con() as c:
                        c.execute("INSERT INTO arquivos (area, nome, caminho, tamanho, enviado_em, atualizado_em) "
                                  "VALUES (?,?,?,?,?,?)", (area.id, arq.name, str(arq), tamanho, _agora(), _agora()))
                    novos += 1
        if novos:
            self.acordar()
        return novos

    # ------------------------------------------------------------ processamento
    def processar_um(self) -> Registro | None:
        """Processa o próximo arquivo da fila (o mais antigo). Devolve o registro ou None se a fila está vazia."""
        with self._trava:
            with self._con() as c:
                row = c.execute("SELECT id FROM arquivos WHERE situacao='na fila' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            r = self.obter(row["id"])
            self._atualizar(r.id, situacao="processando", detalhe="extraindo texto e indexando…")
            try:
                from quiron.servicos.biblioteca.blocos import carregar_guia
                from quiron.servicos.biblioteca.indice import Indice
                from quiron.servicos.biblioteca.ingestao import ingerir_arquivo

                res = ingerir_arquivo(Path(r.caminho), Indice(), carregar_guia(), area=r.area)
                situacao = "pronto" if res.situacao == "ingerido" else res.situacao
                self._atualizar(r.id, situacao=situacao, detalhe=res.detalhe, livro_id=res.livro_id or "")
            except Exception as e:  # noqa: BLE001 — um arquivo com problema não trava a fila
                logging.exception("falha ao processar %s", r.caminho)
                self._atualizar(r.id, situacao="erro", detalhe=f"{type(e).__name__}: {str(e)[:200]}")
            return self.obter(r.id)

    def acordar(self) -> None:
        self._acordar.set()

    def iniciar_processador(self) -> None:
        """Liga o processador em segundo plano (idempotente)."""
        if self._processador and self._processador.is_alive():
            return
        with self._con() as c:  # o que estava "processando" quando o programa fechou volta para a fila
            c.execute("UPDATE arquivos SET situacao='na fila' WHERE situacao='processando'")

        def passo(funcao) -> bool:
            try:
                return bool(funcao())
            except Exception:  # noqa: BLE001 — arquivo sumido no meio, banco ocupado…: a fila não pode morrer calada
                logging.exception("acervo: falha no processador (segue rodando)")
                time.sleep(5)
                return False

        def laco() -> None:
            passo(self.conferir_pastas)
            while True:
                while passo(self.processar_um):
                    pass
                self._acordar.wait(timeout=300)
                self._acordar.clear()
                passo(self.conferir_pastas)

        self._processador = threading.Thread(target=laco, name="acervo", daemon=True)
        self._processador.start()


_ACERVO: Acervo | None = None


def acervo() -> Acervo:
    global _ACERVO
    if _ACERVO is None or _ACERVO.banco != pasta_dados() / "acervo.db":
        _ACERVO = Acervo()
    return _ACERVO
