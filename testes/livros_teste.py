"""Gera livros de teste (conteúdo inventado) em PDF com texto, PDF escaneado, EPUB e PDF com senha."""

from pathlib import Path

RENDA_FIXA = {
    "Capítulo 1 — Duration": [
        "A duration de Macaulay mede o prazo médio ponderado dos fluxos de caixa de um título. "
        "Quanto maior a duration, maior a sensibilidade do preço do título a mudanças na taxa de juros. "
        "A duration modificada estima a variação percentual do preço para cada ponto de variação na taxa.",
        "Um título prefixado longo, como o Tesouro Prefixado com vencimento distante, tem duration alta e "
        "sofre mais marcação a mercado quando os juros sobem. Títulos pós-fixados atrelados à Selic têm duration quase nula.",
    ],
    "Capítulo 2 — Convexidade": [
        "A convexidade corrige a aproximação linear da duration. Para grandes variações de juros, "
        "a relação entre preço e taxa é curva, e a convexidade positiva beneficia o investidor.",
        "Combinar duration e convexidade permite estimar melhor o risco de taxa de juros de uma carteira de renda fixa.",
    ],
}

ACOES = {
    "Parte I — Margem de segurança": [
        "O investidor inteligente compra uma ação apenas quando o preço está bem abaixo do valor intrínseco. "
        "Essa diferença é a margem de segurança, que protege contra erros de avaliação e azar.",
        "O senhor Mercado oferece preços todos os dias; o investidor disciplinado ignora o humor dele e foca no valor da empresa.",
    ],
    "Parte II — Diversificação": [
        "A diversificação reduz o risco específico de cada empresa. Uma carteira com ações de setores diferentes "
        "sofre menos com o tropeço de um único negócio. A taxa de juros alta reduz o valor presente dos lucros futuros das empresas.",
    ],
}

PLANEJAMENTO = {
    "Aposentadoria": [
        "O planejamento da aposentadoria começa pela definição da renda desejada e do prazo de acumulação. "
        "A previdência privada PGBL permite deduzir contribuições até doze por cento da renda bruta tributável.",
    ],
    "Sucessão": [
        "A sucessão patrimonial envolve testamento, doação em vida e previdência, que não entra em inventário. "
        "O ITCMD incide sobre heranças e doações, com alíquotas definidas por cada estado.",
    ],
}


def _pdf(caminho: Path, capitulos: dict, titulo: str, autor: str, senha: str | None = None) -> Path:
    import pymupdf

    doc = pymupdf.open()
    toc = []
    for cap, paragrafos in capitulos.items():
        pagina = doc.new_page()
        toc.append([1, cap, doc.page_count])
        texto = cap + "\n\n" + "\n\n".join(paragrafos)
        pagina.insert_textbox(pymupdf.Rect(50, 50, 545, 800), texto, fontsize=11, fontname="helv")
    doc.set_toc(toc)
    doc.set_metadata({"title": titulo, "author": autor})
    kw = {}
    if senha:
        kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=senha, owner_pw=senha)
    doc.save(caminho, **kw)
    return caminho


def pdf_texto(pasta: Path) -> Path:
    return _pdf(pasta / "renda_fixa.pdf", RENDA_FIXA, "Fundamentos de Renda Fixa", "Ana Teste")


def pdf_protegido(pasta: Path) -> Path:
    return _pdf(pasta / "protegido.pdf", RENDA_FIXA, "Livro Protegido", "Fulano", senha="segredo")


def pdf_escaneado(pasta: Path) -> Path:
    """Renderiza as páginas como imagem (sem camada de texto), como um livro escaneado."""
    import pymupdf

    origem = _pdf(pasta / "_tmp_origem.pdf", PLANEJAMENTO, "x", "y")
    destino = pasta / "Carla Exemplo - Planejamento Financeiro.pdf"
    src = pymupdf.open(origem)
    out = pymupdf.open()
    for p in src:
        pix = p.get_pixmap(dpi=200)
        nova = out.new_page(width=p.rect.width, height=p.rect.height)
        nova.insert_image(nova.rect, pixmap=pix)
    out.save(destino)
    src.close()
    origem.unlink()
    return destino


def epub(pasta: Path) -> Path:
    from ebooklib import epub as e

    livro = e.EpubBook()
    livro.set_identifier("teste-acoes")
    livro.set_title("O Investidor de Valor")
    livro.add_author("Bruno Modelo")
    livro.set_language("pt")
    caps = []
    for i, (cap, paragrafos) in enumerate(ACOES.items(), 1):
        c = e.EpubHtml(title=cap, file_name=f"cap{i}.xhtml", lang="pt")
        c.content = f"<html><body><h1>{cap}</h1>" + "".join(f"<p>{p}</p>" for p in paragrafos) + "</body></html>"
        livro.add_item(c)
        caps.append(c)
    livro.toc = caps
    livro.add_item(e.EpubNcx())
    livro.add_item(e.EpubNav())
    livro.spine = ["nav", *caps]
    destino = pasta / "investidor.epub"
    e.write_epub(str(destino), livro)
    return destino
