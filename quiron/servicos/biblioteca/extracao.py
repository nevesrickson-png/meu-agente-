"""Extração de texto de livros: PDF com texto, PDF escaneado (OCR por+eng) e EPUB.

Arquivos com DRM/senha não são processados (regra do projeto).
Título e autor vêm, nesta ordem: arquivo `<livro>.yaml` ao lado do livro → metadados do arquivo →
nome do arquivo no formato "Autor - Título.pdf".
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FORMATOS = {".pdf", ".epub"}
MIN_CARACTERES_PAGINA = 40  # abaixo disso a página é considerada sem texto (escaneada)


class ArquivoProtegido(Exception):
    """Livro com DRM ou senha: não é processado."""


class OCRIndisponivel(Exception):
    """PDF escaneado, mas o OCR (ocrmypdf + tesseract) não está instalado."""


@dataclass
class Pagina:
    numero: int | None  # None em EPUB (não tem página fixa)
    texto: str
    capitulo: str | None


@dataclass
class LivroExtraido:
    arquivo: Path
    formato: str
    titulo: str
    autor: str
    paginas: list[Pagina] = field(default_factory=list)
    ocr: bool = False

    @property
    def capitulos(self) -> list[str]:
        vistos: list[str] = []
        for p in self.paginas:
            if p.capitulo and p.capitulo not in vistos:
                vistos.append(p.capitulo)
        return vistos


# ---------------------------------------------------------------- metadados


def _limpar(texto: str | None) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def metadados_do_nome(arquivo: Path) -> tuple[str | None, str]:
    """"Autor - Título.pdf" → (autor, título); senão (None, nome do arquivo)."""
    nome = arquivo.stem.replace("_", " ")
    if " - " in nome:
        autor, titulo = nome.split(" - ", 1)
        return _limpar(autor), _limpar(titulo)
    return None, _limpar(nome)


def metadados_extras(arquivo: Path) -> dict:
    """Lê `<livro>.yaml` ao lado do arquivo (titulo, autor), se existir."""
    for lado in (arquivo.with_suffix(".yaml"), arquivo.with_name(arquivo.name + ".yaml")):
        if lado.exists():
            return yaml.safe_load(lado.read_text(encoding="utf-8")) or {}
    return {}


def _resolver_titulo_autor(arquivo: Path, titulo_arquivo: str | None, autor_arquivo: str | None) -> tuple[str, str]:
    extras = metadados_extras(arquivo)
    autor_nome, titulo_nome = metadados_do_nome(arquivo)
    titulo = _limpar(extras.get("titulo")) or _limpar(titulo_arquivo) or titulo_nome
    autor = _limpar(extras.get("autor")) or _limpar(autor_arquivo) or autor_nome or "Autor desconhecido"
    return titulo, autor


# ---------------------------------------------------------------- PDF


def _capitulo_por_pagina(toc: list[list], total: int) -> dict[int, str]:
    """Mapa página → capítulo, a partir do sumário (níveis 1 e 2)."""
    entradas = sorted(((pag, _limpar(tit)) for nivel, tit, pag, *_ in toc if nivel <= 2 and pag >= 1), key=lambda e: e[0])
    mapa: dict[int, str] = {}
    atual = None
    j = 0
    for p in range(1, total + 1):
        while j < len(entradas) and entradas[j][0] <= p:
            atual = entradas[j][1]
            j += 1
        if atual:
            mapa[p] = atual
    return mapa


def _paginas_pdf(caminho: Path) -> tuple[list[Pagina], dict]:
    import pymupdf

    with pymupdf.open(caminho) as doc:
        if doc.needs_pass or doc.is_encrypted:
            raise ArquivoProtegido(f"{caminho.name}: PDF protegido por senha/DRM")
        capitulos = _capitulo_por_pagina(doc.get_toc(simple=True), doc.page_count)
        paginas = [
            Pagina(i + 1, pagina.get_text("text"), capitulos.get(i + 1)) for i, pagina in enumerate(doc)
        ]
        return paginas, dict(doc.metadata or {})


def _precisa_ocr(paginas: list[Pagina]) -> bool:
    if not paginas:
        return False
    vazias = sum(1 for p in paginas if len(p.texto.strip()) < MIN_CARACTERES_PAGINA)
    return vazias / len(paginas) > 0.3


def _rodar_ocr(origem: Path, destino: Path) -> None:
    try:
        import ocrmypdf
    except ImportError as e:  # pragma: no cover
        raise OCRIndisponivel("Instale o ocrmypdf") from e
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        ocrmypdf.ocr(
            origem, destino, language=["por", "eng"], skip_text=True, progress_bar=False, optimize=0, output_type="pdf"
        )
    except (ocrmypdf.exceptions.MissingDependencyError, FileNotFoundError) as e:
        raise OCRIndisponivel(
            "PDF escaneado precisa de OCR: instale o Tesseract (com português) e o Ghostscript. "
            "No Windows: https://github.com/UB-Mannheim/tesseract/wiki e https://ghostscript.com"
        ) from e


def extrair_pdf(caminho: Path, pasta_texto: Path | None = None) -> LivroExtraido:
    paginas, meta = _paginas_pdf(caminho)
    ocr = False
    if _precisa_ocr(paginas):
        import hashlib

        with caminho.open("rb") as f:  # pelo conteúdo: dois livros "apostila.pdf" de áreas diferentes não trocam de texto
            sha = hashlib.file_digest(f, "sha256").hexdigest()[:16]
        destino = (pasta_texto or caminho.parent) / f"{caminho.stem}-{sha}.ocr.pdf"
        if not destino.exists():
            _rodar_ocr(caminho, destino)
        paginas, _ = _paginas_pdf(destino)
        ocr = True
    titulo, autor = _resolver_titulo_autor(caminho, meta.get("title"), meta.get("author"))
    return LivroExtraido(caminho, "pdf", titulo, autor, paginas, ocr)


# ---------------------------------------------------------------- EPUB

_FONTES_OFUSCADAS = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")


def _epub_tem_drm(caminho: Path) -> bool:
    with zipfile.ZipFile(caminho) as z:
        if "META-INF/rights.xml" in z.namelist():
            return True
        if "META-INF/encryption.xml" not in z.namelist():
            return False
        xml = z.read("META-INF/encryption.xml").decode("utf-8", "ignore")
    algoritmos = re.findall(r'Algorithm="([^"]+)"', xml)
    return any(a not in _FONTES_OFUSCADAS for a in algoritmos)


def _html_para_texto(conteudo: bytes) -> tuple[str, str | None]:
    import lxml.html

    raiz = lxml.html.fromstring(conteudo)
    for ruim in raiz.xpath("//script|//style"):
        ruim.drop_tree()
    titulo = None
    for tag in ("h1", "h2", "h3", "title"):
        achado = raiz.xpath(f"//{tag}")
        if achado and _limpar(achado[0].text_content()):
            titulo = _limpar(achado[0].text_content())
            break
    blocos = []
    for el in raiz.iter("p", "li", "h1", "h2", "h3", "h4", "blockquote", "td"):
        t = _limpar(el.text_content())
        if t:
            blocos.append(t)
    texto = "\n\n".join(blocos) if blocos else _limpar(raiz.text_content())
    return texto, titulo


def _titulos_do_sumario(toc, mapa: dict[str, str] | None = None) -> dict[str, str]:
    mapa = {} if mapa is None else mapa
    for item in toc:
        if isinstance(item, tuple):  # (Section, [filhos])
            secao, filhos = item
            href = getattr(secao, "href", None)
            if href:
                mapa.setdefault(href.split("#")[0], _limpar(secao.title))
            _titulos_do_sumario(filhos, mapa)
        else:
            href = getattr(item, "href", "")
            if href:
                mapa.setdefault(href.split("#")[0], _limpar(item.title))
    return mapa


def extrair_epub(caminho: Path) -> LivroExtraido:
    import ebooklib
    from ebooklib import epub

    if _epub_tem_drm(caminho):
        raise ArquivoProtegido(f"{caminho.name}: EPUB com DRM")
    livro = epub.read_epub(str(caminho), options={"ignore_ncx": False})
    titulos = _titulos_do_sumario(livro.toc)
    paginas: list[Pagina] = []
    for idref, *_ in livro.spine:
        item = livro.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        texto, titulo_html = _html_para_texto(item.get_content())
        if len(texto) < 20:
            continue
        capitulo = titulos.get(item.get_name()) or titulo_html
        paginas.append(Pagina(None, texto, capitulo))

    def _meta(campo: str) -> str | None:
        valores = livro.get_metadata("DC", campo)
        return valores[0][0] if valores else None

    titulo, autor = _resolver_titulo_autor(caminho, _meta("title"), _meta("creator"))
    return LivroExtraido(caminho, "epub", titulo, autor, paginas, False)


def extrair(caminho: Path, pasta_texto: Path | None = None) -> LivroExtraido:
    sufixo = caminho.suffix.lower()
    if sufixo == ".pdf":
        return extrair_pdf(caminho, pasta_texto)
    if sufixo == ".epub":
        return extrair_epub(caminho)
    raise ValueError(f"Formato não suportado: {caminho.name} (use PDF ou EPUB)")
