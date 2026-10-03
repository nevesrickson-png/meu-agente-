import shutil
from datetime import date

import pytest

from quiron.servicos.biblioteca import consultas
from quiron.servicos.biblioteca.blocos import Bloco, Guia
from quiron.servicos.biblioteca.embeddings import Lexico
from quiron.servicos.biblioteca.extracao import extrair, metadados_do_nome
from quiron.servicos.biblioteca.indice import Indice
from quiron.servicos.biblioteca.ingestao import ingerir_pasta, reclassificar_blocos
from testes import livros_teste

TEM_OCR = bool(shutil.which("tesseract") and shutil.which("gs"))

GUIA = Guia(
    [
        Bloco(1, "Renda fixa", "títulos, juros, duration, convexidade", ["duration", "convexidade", "tesouro"]),
        Bloco(2, "Renda variável", "ações, valuation, margem de segurança", ["ações", "valor intrínseco", "diversificação"]),
        Bloco(3, "Planejamento e sucessão", "aposentadoria, previdência, herança", ["aposentadoria", "sucessão", "ITCMD"]),
    ],
    limiar=0.05,
)


@pytest.fixture(scope="module")
def biblioteca(tmp_path_factory, monkeypatch_module):
    raiz = tmp_path_factory.mktemp("biblioteca")
    entrada = raiz / "entrada"
    entrada.mkdir()
    livros_teste.pdf_texto(entrada)
    livros_teste.epub(entrada)
    livros_teste.pdf_protegido(entrada)
    if TEM_OCR:
        livros_teste.pdf_escaneado(entrada)
    monkeypatch_module.setattr("quiron.servicos.biblioteca.consultas.carregar_guia", lambda: GUIA)
    indice = Indice(raiz, Lexico())
    relatorio = ingerir_pasta(indice, GUIA)
    return indice, relatorio


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_metadados_pelo_nome_do_arquivo(tmp_path):
    assert metadados_do_nome(tmp_path / "Howard Marks - O Mais Importante.pdf") == ("Howard Marks", "O Mais Importante")
    arq = tmp_path / "x.pdf"
    (tmp_path / "x.yaml").write_text("titulo: Título Certo\nautor: Autora Certa\n", encoding="utf-8")
    livros_teste._pdf(arq, {"A": ["texto " * 30]}, "Errado", "Errado")
    l = extrair(arq)
    assert (l.titulo, l.autor) == ("Título Certo", "Autora Certa")


def test_pdf_com_texto_tem_capitulos_e_paginas(tmp_path):
    l = extrair(livros_teste.pdf_texto(tmp_path))
    assert (l.titulo, l.autor, l.formato, l.ocr) == ("Fundamentos de Renda Fixa", "Ana Teste", "pdf", False)
    assert l.capitulos == ["Capítulo 1 — Duration", "Capítulo 2 — Convexidade"]
    assert [p.numero for p in l.paginas] == [1, 2]


def test_epub(tmp_path):
    l = extrair(livros_teste.epub(tmp_path))
    assert (l.titulo, l.autor, l.formato) == ("O Investidor de Valor", "Bruno Modelo", "epub")
    assert "Parte I — Margem de segurança" in l.capitulos
    assert any("margem de segurança" in p.texto for p in l.paginas)


@pytest.mark.skipif(not TEM_OCR, reason="Tesseract/Ghostscript não instalados")
def test_pdf_escaneado_passa_por_ocr(tmp_path):
    l = extrair(livros_teste.pdf_escaneado(tmp_path), tmp_path / "texto")
    assert l.ocr and (l.autor, l.titulo) == ("Carla Exemplo", "Planejamento Financeiro")
    texto = " ".join(p.texto for p in l.paginas).lower()
    assert "aposentadoria" in texto and "itcmd" in texto


def test_relatorio_de_ingestao(biblioteca):
    indice, rel = biblioteca
    situacoes = {l.arquivo: l.situacao for l in rel.livros}
    assert situacoes["renda_fixa.pdf"] == "ingerido"
    assert situacoes["investidor.epub"] == "ingerido"
    assert situacoes["protegido.pdf"] == "pulado (DRM)"
    if TEM_OCR:
        assert situacoes["Carla Exemplo - Planejamento Financeiro.pdf"] == "ingerido"
    relatorio = (indice.raiz / "relatorio_ingestao.md").read_text(encoding="utf-8")
    assert "pulado (DRM)" in relatorio and "Cobertura dos 22 blocos" in relatorio
    # segunda rodada não reprocessa
    assert {l.situacao for l in ingerir_pasta(indice, GUIA).livros} <= {"já estava", "pulado (DRM)"}


def test_busca_com_citacao(biblioteca):
    indice, _ = biblioteca
    texto = consultas.buscar("o que é duration e sensibilidade do preço aos juros", n=2, indice=indice)
    assert "📚 Fundamentos de Renda Fixa — Ana Teste" in texto
    assert 'cap. "Capítulo 1 — Duration"' in texto and "p. 1" in texto
    assert "Bloco 1 — Renda fixa" in texto


def test_filtros_por_autor_e_bloco(biblioteca):
    indice, _ = biblioteca
    so_bruno = indice.buscar("juros", 5, autor="bruno modelo")
    assert so_bruno and all(r.meta["autor"] == "Bruno Modelo" for r in so_bruno)
    bloco2 = indice.buscar("risco", 5, bloco=2)
    assert bloco2 and all(r.meta["bloco"] == 2 for r in bloco2)


def test_estudar_debate_mapa_ficha_conexao(biblioteca):
    indice, _ = biblioteca
    estudo = consultas.estudar_tema("margem de segurança e valor intrínseco", indice=indice)
    assert "## O Investidor de Valor — Bruno Modelo" in estudo and "Capítulos para ler" in estudo

    debate = consultas.debate_autores("taxa de juros", indice=indice)
    assert "## Ana Teste" in debate and "## Bruno Modelo" in debate

    mapa = consultas.mapa_autor("ana teste", indice=indice)
    assert "Fundamentos de Renda Fixa" in mapa and "Renda fixa" in mapa

    f = consultas.ficha("renda fixa", indice=indice)
    assert f.startswith("# Fundamentos de Renda Fixa") and "| 1. Renda fixa |" in f
    assert (indice.raiz / "fichas").glob("*.md")

    conexao = consultas.conectar_conceitos("duration", "convexidade", indice=indice)
    assert "Capítulo 2 — Convexidade" in conexao.split("## duration")[0]


def test_cobertura_pilula_e_lista(biblioteca):
    indice, _ = biblioteca
    cob = consultas.cobertura(indice=indice)
    assert "| 1. Renda fixa |" in cob and "Fundamentos de Renda Fixa" in cob
    p1 = consultas.pilula(dia=date(2026, 10, 3), indice=indice)
    assert p1 == consultas.pilula(dia=date(2026, 10, 3), indice=indice)  # mesma pílula no mesmo dia
    assert p1.startswith("# Pílula de 03/10/2026") and "📚" in p1
    assert "Bruno Modelo" in consultas.listar_livros(indice=indice)


def test_reclassificar_quando_o_guia_muda(biblioteca):
    indice, _ = biblioteca
    guia_novo = Guia([Bloco(7, "Tudo sobre juros", "juros taxa", ["juros"])], limiar=0.01)
    cont = reclassificar_blocos(indice, guia_novo)
    assert 7 in cont
    reclassificar_blocos(indice, GUIA)  # volta ao guia dos outros testes


def test_biblioteca_vazia(tmp_path):
    vazio = Indice(tmp_path, Lexico())
    assert consultas.buscar("duration", indice=vazio) == consultas.VAZIA


@pytest.mark.online
def test_embeddings_reais_entendem_sinonimos(tmp_path):
    """Baixa o modelo multilíngue (~220 MB). Rode no seu PC: `uv run pytest -m online`."""
    from quiron.servicos.biblioteca.embeddings import FastEmbed

    (tmp_path / "entrada").mkdir()
    livros_teste.pdf_texto(tmp_path / "entrada")
    livros_teste.epub(tmp_path / "entrada")
    indice = Indice(tmp_path, FastEmbed())
    ingerir_pasta(indice, GUIA)
    # sem usar a palavra "duration": o modelo precisa entender o sentido
    melhor = indice.buscar("quanto o preço de um título cai quando a Selic sobe", 1)[0]
    assert melhor.meta["titulo"] == "Fundamentos de Renda Fixa"
