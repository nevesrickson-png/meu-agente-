"""Divisão do livro em trechos com metadados (livro, autor, capítulo, página)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from quiron.servicos.biblioteca.extracao import LivroExtraido

TAMANHO_PADRAO = 1200  # caracteres (~250 palavras)
SOBREPOSICAO_PADRAO = 200


@dataclass
class Trecho:
    id: str
    livro_id: str
    titulo: str
    autor: str
    capitulo: str | None
    pagina_inicio: int | None
    pagina_fim: int | None
    texto: str
    bloco: int = 0  # 0 = sem bloco do guia

    def metadados(self) -> dict:
        """Metadados para o índice (Chroma não aceita None)."""
        return {
            "livro_id": self.livro_id,
            "titulo": self.titulo,
            "autor": self.autor,
            "autor_chave": chave(self.autor),
            "capitulo": self.capitulo or "",
            "pagina_inicio": self.pagina_inicio or 0,
            "pagina_fim": self.pagina_fim or 0,
            "bloco": self.bloco,
        }


def chave(texto: str) -> str:
    """Normaliza para comparação: minúsculas, sem acento."""
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).casefold().strip()


def limpar_texto(texto: str) -> str:
    t = texto.replace("­", "")
    t = re.sub(r"(\w)-\n(\w)", r"\1\2", t)  # palavra hifenizada na quebra de linha
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _paragrafos(texto: str) -> list[str]:
    partes = re.split(r"\n\s*\n", texto)
    if len(partes) == 1:  # PDF sem linhas em branco: junta linhas e corta por frases
        partes = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", texto.replace("\n", " "))
    return [re.sub(r"\s+", " ", p).strip() for p in partes if p.strip()]


def dividir(livro: LivroExtraido, livro_id: str, tamanho: int = TAMANHO_PADRAO, sobreposicao: int = SOBREPOSICAO_PADRAO) -> list[Trecho]:
    """Agrupa parágrafos em trechos de ~`tamanho` caracteres, sem atravessar capítulos."""
    trechos: list[Trecho] = []
    buffer: list[str] = []
    pag_ini: int | None = None
    pag_fim: int | None = None
    capitulo_atual: str | None = None

    def fechar() -> None:
        nonlocal buffer, pag_ini
        texto = " ".join(buffer).strip()
        if len(texto) >= 80:
            trechos.append(
                Trecho(f"{livro_id}#{len(trechos):05d}", livro_id, livro.titulo, livro.autor, capitulo_atual, pag_ini, pag_fim, texto)
            )
        # sobreposição: carrega o fim do trecho anterior para manter contexto
        cauda = texto[-sobreposicao:] if sobreposicao and texto else ""
        cauda = cauda[cauda.find(" ") + 1 :] if " " in cauda else cauda
        buffer = [cauda] if cauda else []
        pag_ini = pag_fim if cauda else None

    for pagina in livro.paginas:
        if pagina.capitulo != capitulo_atual:
            if buffer and any(len(b) for b in buffer):
                fechar()
            buffer, pag_ini = [], None
            capitulo_atual = pagina.capitulo
        for par in _paragrafos(limpar_texto(pagina.texto)):
            while len(par) > tamanho * 1.5:  # parágrafo gigante: corta em pedaços
                corte = par.rfind(" ", 0, tamanho) or tamanho
                buffer.append(par[:corte])
                pag_ini = pag_ini or pagina.numero
                pag_fim = pagina.numero
                fechar()
                par = par[corte:].strip()
            if pag_ini is None:
                pag_ini = pagina.numero
            pag_fim = pagina.numero
            buffer.append(par)
            if sum(len(b) + 1 for b in buffer) >= tamanho:
                fechar()
    if buffer and len(" ".join(buffer).strip()) > sobreposicao:
        fechar()
    return trechos
