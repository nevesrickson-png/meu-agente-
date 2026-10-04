"""Acervo: arquivos enviados pelo Terminal vão para a pasta da área, entram na fila e na biblioteca com a área."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from quiron.servicos import acervo as mod
from quiron.servicos.acervo import Acervo, AcervoErro, nome_seguro
from testes.livros_teste import _pdf as criar_pdf


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("QUIRON_BIBLIOTECA", str(tmp_path / "bib"))
    monkeypatch.setenv("QUIRON_EMBEDDINGS", "lexico")
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    monkeypatch.setattr(mod, "_ACERVO", None)
    return tmp_path


def _pdf(tmp_path, nome="livro.pdf"):
    caminho = tmp_path / nome
    criar_pdf(caminho, {"Capítulo 1 - VaR": ["Value at Risk mede a perda máxima esperada com um nível de confiança. " * 12],
                        "Capítulo 2 - Estresse": ["Testes de estresse avaliam cenários extremos de mercado. " * 12]},
              "Manual de Risco", "Autora Teste")
    return caminho.read_bytes()


def test_nome_seguro():
    assert nome_seguro("../../etc/passwd.PDF") == "passwd.pdf"
    assert nome_seguro("C:\\Users\\x\\Meu Livro (2ª ed.).pdf") == "Meu Livro (2ª ed.).pdf"
    assert nome_seguro("<script>.epub") == "script.epub"


def test_salvar_processar_mover_e_remover(ambiente):
    from quiron.servicos.biblioteca.indice import Indice

    a = Acervo()
    ident = a.salvar("risco", "Manual de Risco.pdf", _pdf(ambiente))
    r = a.obter(ident)
    assert r.area == "RISCO" and r.situacao == "na fila" and "/acervo/risco/" in r.caminho.replace("\\", "/")
    assert a.salvar("RISCO", "Manual de Risco.pdf", b"%PDF-1.4 x") != ident  # não sobrescreve
    assert a.obter(ident + 1).nome == "Manual de Risco (2).pdf"
    with pytest.raises(AcervoErro):
        a.salvar("RISCO", "planilha.xlsx", b"x")
    with pytest.raises(AcervoErro):
        a.salvar("ASTROLOGIA", "x.pdf", b"x")

    feito = a.processar_um()
    assert feito.situacao == "pronto" and feito.livro_id
    indice = Indice()
    assert indice.buscar("perda máxima esperada", 3, area="RISCO")
    assert not indice.buscar("perda máxima esperada", 3, area="ECONOMIA")
    assert indice.catalogo()[feito.livro_id]["area"] == "RISCO"
    assert a.processar_um().situacao == "erro"  # o PDF falso vira erro sem travar a fila
    assert a.processar_um() is None

    movido = a.mover(ident, "CARTEIRAS")
    assert movido.area == "CARTEIRAS" and "/acervo/carteiras/" in movido.caminho.replace("\\", "/")
    assert Indice().buscar("perda máxima esperada", 3, area="CARTEIRAS")
    resumo = {x["id"]: x for x in a.resumo_areas()}
    assert resumo["CARTEIRAS"]["prontos"] == 1

    a.remover(ident)
    assert not Indice().catalogo().get(feito.livro_id)
    assert all(x.id != ident for x in a.listar())


def test_conferir_pastas_pega_arquivo_colocado_a_mao(ambiente):
    a = Acervo()
    pasta = mod.pasta_acervo() / "economia"
    pasta.mkdir(parents=True)
    (pasta / "colocado.pdf").write_bytes(_pdf(ambiente, "c.pdf"))
    (pasta / "nota.txt").write_text("ignorar")
    assert a.conferir_pastas() == 1 and a.conferir_pastas() == 0
    assert a.listar()[0].area == "ECONOMIA"


def test_api_do_terminal_protegida_e_funcionando(ambiente):
    from quiron.terminal.backend import app as terminal

    monkey_pdf = _pdf(ambiente)
    c = TestClient(terminal.app)
    assert "Acervo" in c.get("/acervo").text
    dados = c.get("/api/acervo").json()
    assert len([x for x in dados["areas"] if x["tipo"] == "campo"]) == 20 and dados["formatos"] == [".epub", ".pdf"]
    # sem o cabeçalho da tela: recusado (outro site não consegue enviar)
    assert c.put("/api/acervo/arquivo", params={"area": "RISCO", "nome": "a.pdf"}, content=monkey_pdf).status_code == 403
    cab = {"X-Quiron": "acervo"}
    # endereço estranho sem senha: recusado (DNS rebinding)
    assert TestClient(terminal.app, base_url="http://malicioso.com").put(
        "/api/acervo/arquivo", params={"area": "RISCO", "nome": "a.pdf"}, content=monkey_pdf, headers=cab).status_code == 403
    r = c.put("/api/acervo/arquivo", params={"area": "RISCO", "nome": "a.pdf"}, content=monkey_pdf, headers=cab)
    assert r.status_code == 200 and r.json()["area"] == "RISCO"
    assert c.put("/api/acervo/arquivo", params={"area": "RISCO", "nome": "a.docx"}, content=b"x", headers=cab).status_code == 400
    nova = c.post("/api/acervo/area", json={"nome": "Agronegócio", "descricao": "CPR"}, headers=cab).json()
    assert nova["id"] == "AGRONEGOCIO"
    assert c.post("/api/acervo/mover", json={"id": r.json()["id"], "area": "AGRONEGOCIO"}, headers=cab).json()["area"] == "AGRONEGOCIO"
    assert c.delete(f"/api/acervo/arquivo/{r.json()['id']}", headers=cab).json() == {"ok": True}


def test_envio_em_partes_respeita_limite(ambiente, monkeypatch):
    monkeypatch.setattr(mod, "LIMITE_BYTES", 10)
    a = Acervo()

    async def partes():
        yield b"123456"
        yield b"789012"

    with pytest.raises(AcervoErro, match="grande demais"):
        asyncio.run(a.salvar_em_partes("RISCO", "x.pdf", partes()))
    assert not list((mod.pasta_acervo() / "risco").glob("*"))  # não sobra arquivo pela metade
