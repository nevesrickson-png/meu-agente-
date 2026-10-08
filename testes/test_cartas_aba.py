"""Aba Cartas (08/10/2026): histórico pela paginação e pelo feed, páginas extras e API pública, gestora encerrada,
autodescoberta da página de cartas, títulos limpos, categorias, feed em páginas, resumo guardado e as rotas do Terminal.
Tudo sem internet (respostas simuladas)."""

from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from quiron.servicos.cartas import coleta

HOJE = date(2026, 10, 8)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    coleta._ROBOTS.clear()
    return tmp_path


def _cliente(paginas: dict[str, str | httpx.Response]):
    """Respostas por endereço EXATO (sem a barra final); o resto é 404. robots.txt ausente = permitido."""
    def roteador(req: httpx.Request) -> httpx.Response:
        url = str(req.url).rstrip("/")
        r = paginas.get(url)
        if r is None:
            return httpx.Response(404)
        return r if isinstance(r, httpx.Response) else httpx.Response(200, text=r)
    return httpx.Client(transport=httpx.MockTransport(roteador), follow_redirects=True)


def _lista(meses: list[tuple[int, int]], proxima: str = "") -> str:
    links = "".join(f'<a href="/uploads/carta-{a}-{m:02d}.pdf">Carta mensal {m:02d}/{a}</a>' for a, m in meses)
    nav = f'<a href="{proxima}">Próxima »</a>' if proxima else ""
    return f"<html><body>{links}{nav}</body></html>"


def test_historico_segue_a_paginacao_so_quando_pedido():
    cli = _cliente({"https://g.com.br/cartas": _lista([(2026, 9), (2026, 8)], "/cartas/page/2/"),
                    "https://g.com.br/cartas/page/2": _lista([(2026, 7), (2026, 6)], "/cartas/page/3/"),
                    "https://g.com.br/cartas/page/3": _lista([(2025, 12)])})
    fonte = {"nome": "G", "url": "https://g.com.br/cartas", "tipo": "gestora"}
    _, so_hoje = coleta.conferir(fonte, cli, HOJE)
    sit, tudo = coleta.conferir(fonte, cli, HOJE, historico=True)
    assert len(so_hoje) == 2 and len(tudo) == 5 and sit.historico_em
    assert min(c.data for c in tudo) == "2025-12-01" and sit.situacao == "ativa"


def test_feed_do_wordpress_traz_paginas_antigas():
    def feed(itens):
        corpo = "".join(f"<item><title>Carta {t}</title><link>https://g.com.br/{t}</link><pubDate>{d}</pubDate></item>" for t, d in itens)
        return httpx.Response(200, text=f'<?xml version="1.0"?><rss version="2.0"><channel>{corpo}</channel></rss>',
                              headers={"content-type": "application/rss+xml"})
    pagina = '<html><head><link rel="alternate" type="application/rss+xml" href="https://g.com.br/category/cartas/feed/"></head></html>'
    cli = _cliente({"https://g.com.br/category/cartas": pagina,
                    "https://g.com.br/category/cartas/feed": feed([("set", "Mon, 05 Oct 2026 10:00:00 GMT")]),
                    "https://g.com.br/category/cartas/feed/?paged=2": feed([("ago", "Mon, 07 Sep 2026 10:00:00 GMT")]),
                    "https://g.com.br/category/cartas/feed/?paged=3": feed([("jul", "Mon, 03 Aug 2026 10:00:00 GMT")])})
    sit, cartas = coleta.conferir({"nome": "G", "url": "https://g.com.br/category/cartas"}, cli, HOJE, historico=True)
    assert sit.metodo == "feed" and [c.data for c in cartas] == ["2026-10-05", "2026-09-07", "2026-08-03"]


def test_paginas_extras_api_publica_e_padrao_de_link():
    api = httpx.Response(200, json=[{"title": {"rendered": "Carta Macro &#8211; Setembro"}, "date": "2026-09-30T10:00:00",
                                     "link": "https://g.com.br/carta-macro-setembro"},
                                    {"title": {"rendered": "Assembleia geral"}, "date": "2026-09-29", "link": "https://g.com.br/ag"}])
    cli = _cliente({"https://g.com.br/cartas": "<html><a href='/menu-2026-09'>Menu 2026-09</a>"
                                               "<a href='/docs/carta-fia-2026-08.pdf'>FIA 08/2026</a></html>",
                    "https://g.com.br/cartas-previdencia": _lista([(2026, 7)]),
                    "https://g.com.br/wp-json/wp/v2/posts?categories=7": api})
    fonte = {"nome": "G", "url": "https://g.com.br/cartas", "paginas": ["https://g.com.br/cartas-previdencia"],
             "api": "https://g.com.br/wp-json/wp/v2/posts?categories=7", "link_inclui": r"/docs/|/uploads/|carta-macro"}
    _, cartas = coleta.conferir(fonte, cli, HOJE)
    titulos = {c.titulo for c in cartas}
    assert "Carta Macro – Setembro" in titulos and "Assembleia geral" not in titulos  # assembleia não é carta
    assert {c.data for c in cartas} == {"2026-09-30", "2026-08-01", "2026-07-01"}
    assert not any("menu" in c.link for c in cartas)  # fora do padrão de link da gestora


def test_gestora_encerrada_nem_e_consultada():
    def proibido(req):
        raise AssertionError("não devia ir à rede")
    cli = httpx.Client(transport=httpx.MockTransport(proibido))
    sit, cartas = coleta.conferir({"nome": "Velha", "url": "https://velha.com.br", "encerrada": True,
                                   "motivo": "incorporada pela Nova em 2024"}, cli, HOJE, historico=True)
    assert sit.situacao == "encerrada" and "Nova" in sit.detalhe and cartas == []


def test_autodescoberta_acha_a_pagina_que_mudou_de_endereco():
    inicio = ('<html><a href="/sobre">Sobre</a><a href="/conteudos/cartas-mensais">Cartas mensais</a>'
              '<a href="https://linkedin.com/x">LinkedIn</a></html>')
    cli = _cliente({"https://g.com.br/cartas": httpx.Response(404),
                    "https://g.com.br": inicio,
                    "https://g.com.br/conteudos/cartas-mensais": _lista([(2026, 9), (2026, 8), (2026, 7)])})
    fonte = {"nome": "G", "url": "https://g.com.br/cartas"}
    sit, cartas = coleta.conferir(fonte, cli, HOJE, historico=True)
    assert sit.descoberta == "https://g.com.br/conteudos/cartas-mensais" and sit.situacao == "ativa" and len(cartas) == 3
    coleta._gravar(sit, cartas)
    with coleta.conectar() as con:
        assert con.execute("SELECT url FROM descobertas WHERE fonte = 'G'").fetchone()[0] == sit.descoberta
    _, sem_hist = coleta.conferir(fonte, cli, HOJE)  # dia comum: sem histórico, não procura de novo
    assert sem_hist == []


def test_titulos_limpos():
    assert coleta._encurtar("Multimercado Relatório de Setembro 2026 07.10.2026 LER MAIS") == "Multimercado Relatório de Setembro 2026"
    assert coleta._encurtar("06 de outubro de 2026 Outubro: eleições chegam ao fim") == "Outubro: eleições chegam ao fim"
    cartas = coleta._itens_pagina('<a href="/x/a8f9c7d6e5b4a3f2e1d0c9b8a7f6e5d4-2026-09.pdf">Acessar documento</a>',
                                  "https://g.com.br/cartas", {"nome": "G"})
    assert cartas[0].titulo == "Carta de 09/2026"


def _gravar_cartas(nome: str, datas: list[str], tipo: str = "gestora", sit: str = "ativa") -> None:
    s = coleta.Situacao(nome, tipo, f"https://{nome.lower()}.com.br", sit, conferido_em="2026-10-08T10:00:00+00:00")
    coleta._gravar(s, [coleta.Carta(nome, f"Carta {d}", f"https://{nome.lower()}.com.br/{d}.pdf", d, tipo) for d in datas])


def test_categorias_feed_em_paginas_e_historico(monkeypatch):
    hoje = date.today()
    d = lambda dias: (hoje - timedelta(days=dias)).isoformat()  # noqa: E731
    monkeypatch.setattr(coleta, "fontes", lambda: [{"nome": n, "url": f"https://{n.lower()}.com.br", "tipo": "gestora"}
                                                   for n in ("Ativa", "Trimestral", "Parada", "Muda")])
    _gravar_cartas("Ativa", [d(5), d(35), d(65), d(400)])
    _gravar_cartas("Trimestral", [d(200)])
    _gravar_cartas("Parada", [d(800)], sit="desatualizada")
    cats = {g["fonte"]: g["categoria"] for g in coleta.gestoras()}
    assert cats == {"Ativa": "ativa", "Trimestral": "esporadica", "Parada": "parada", "Muda": "sem_leitura"}
    pagina1 = coleta.feed(dias=0, limite=2)
    pagina2 = coleta.feed(dias=0, limite=2, antes=pagina1[-1]["data"])
    assert [c["data"] for c in pagina1 + pagina2] == [d(5), d(35), d(65), d(200)]
    assert [c["fonte"] for c in coleta.feed(dias=0, gestoras_nomes=["Parada"])] == ["Parada"]
    h = coleta.historico("Ativa")
    assert len(h["cartas"]) == 4 and h["gestora"]["total"] == 4 and coleta.historico("Não existe") is None


def test_resumo_guardado_nao_gasta_ia_duas_vezes(monkeypatch):
    from types import SimpleNamespace

    from quiron.nucleo import cerebro

    chamadas = []
    monkeypatch.setattr(coleta, "ler_carta", lambda link: "Cenário: juros altos por mais tempo. " * 30)
    monkeypatch.setattr(cerebro, "perguntar", lambda *a, **k: chamadas.append(1) or SimpleNamespace(texto="1) Cenário: juros altos.", modelo="m"))
    assert coleta.resumir("https://g.com.br/x.pdf") == {"resumo": "1) Cenário: juros altos.", "guardado": False}
    assert coleta.resumir("https://g.com.br/x.pdf")["guardado"] and len(chamadas) == 1
    monkeypatch.setattr(coleta, "ler_carta", lambda link: "Só leio cartas dos sites das gestoras cadastradas.")
    assert "erro" in coleta.resumir("https://outro.com/y.pdf")


def test_rotas_da_aba_cartas(monkeypatch):
    from quiron.terminal.backend.app import app

    hoje = date.today()
    monkeypatch.setattr(coleta, "fontes", lambda: [{"nome": "Ativa", "url": "https://ativa.com.br", "tipo": "gestora"}])
    monkeypatch.setattr(coleta, "atualizar_em_segundo_plano", lambda *a, **k: False)
    _gravar_cartas("Ativa", [(hoje - timedelta(days=3)).isoformat()])
    c = TestClient(app, base_url="http://127.0.0.1")
    assert "Cartas" in c.get("/cartas").text
    d = c.get("/api/cartas", params={"categoria": "ativa"}).json()
    assert d["categorias"] == {"ativa": 1} and len(d["itens"]) == 1
    assert c.get("/api/cartas/gestoras").json()["gestoras"][0]["total"] == 1
    assert c.get("/api/cartas/gestora", params={"nome": "Ativa"}).json()["cartas"][0]["fonte"] == "Ativa"
    assert c.get("/api/cartas/gestora", params={"nome": "X"}).status_code == 404
    assert c.get("/api/cartas", params={"antes": "lixo"}).status_code == 400
    assert c.post("/api/cartas/resumo", json={"link": "https://ativa.com.br/a.pdf"}).status_code == 403  # sem o cabeçalho da tela
    r = c.post("/api/cartas/resumo", json={"link": "https://estranho.com/a.pdf"}, headers={"X-Quiron": "terminal"})
    assert r.status_code == 400  # só cartas das gestoras cadastradas


# ---------------------------------------------------------------- leitores novos (investigação das fontes, 08/10/2026)
def test_datas_do_nome_do_arquivo_vencem_a_pasta_de_upload():
    assert coleta.extrair_data("/docs/CartaMensalGenoaCapital_Ago26.pdf", HOJE) == "2026-08-01"
    assert coleta.extrair_data("https://v.com/wp-content/uploads/2025/06/Carta-Abril-2024.pdf", HOJE) == "2024-04-01"
    assert coleta.extrair_data("https://v.com/wp-content/uploads/2026/08/carta.pdf", HOJE) == "2026-08-01"
    assert coleta.extrair_data("junior-2026 setor 2026", HOJE) == ""


def test_api_strapi_e_carimbo_em_milissegundos():
    strapi = httpx.Response(200, json={"data": [{"id": 1, "attributes": {"title": "Carta 2T26", "date": "2026-07-10",
                                                  "document": {"data": {"attributes": {"url": "https://cdn.x.com/2t26.pdf"}}}}}]})
    hsbc = httpx.Response(200, json=[{"title": "Monthly View", "link": "https://h.com/mv",
                                      "createdArticleTimeStamp": "1790000000000"}])
    cli = _cliente({"https://api.g.com/letters": strapi, "https://h.com/lista.json": hsbc})
    c = coleta._itens_api(cli, "https://api.g.com/letters", {"nome": "G"})[0]
    assert (c.titulo, c.link, c.data) == ("Carta 2T26", "https://cdn.x.com/2t26.pdf", "2026-07-10")
    assert coleta._itens_api(cli, "https://h.com/lista.json", {"nome": "H"})[0].data == "2026-09-21"


def test_sitemap_lista_txt_e_mziq():
    mapa = ("<urlset><url><loc>https://blog.x.com/asset/cenario-macro-setembro</loc><lastmod>2026-09-25</lastmod></url>"
            "<url><loc>https://blog.x.com/outro/receita</loc><lastmod>2026-09-26</lastmod></url></urlset>")
    def roteador(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if u == "https://blog.x.com/sitemap.xml":
            return httpx.Response(200, text=mapa)
        if u.endswith("/cartas.txt"):
            return httpx.Response(200, text="2026_08\n2026_09\n")
        if "apicatalog.mziq.com" in u and req.method == "POST":
            ano = __import__("json").loads(req.content)["year"]
            metas = [{"file_title": f"Carta mensal - SET/{ano[2:]}", "file_url": f"https://api.mziq.com/d/{ano}.pdf",
                      "file_published_date": f"{ano}-10-02T10:00:00"}] if ano == "2026" else []
            return httpx.Response(200, json={"data": {"document_metas": metas}})
        return httpx.Response(404)
    cli = httpx.Client(transport=httpx.MockTransport(roteador))
    s = coleta._itens_sitemap(cli, "https://blog.x.com/sitemap.xml", {"nome": "I", "link_inclui": r"/asset/"})
    assert [(c.titulo, c.data) for c in s] == [("Cenario macro setembro", "2026-09-25")]
    t = coleta._itens_lista_txt(cli, {"url": "https://b.x/cartas.txt", "modelo_link": "https://b.x/{linha}.pdf"}, {"nome": "V"})
    assert [(c.titulo, c.link) for c in t] == [("Carta do gestor 08/2026", "https://b.x/2026_08.pdf"),
                                               ("Carta do gestor 09/2026", "https://b.x/2026_09.pdf")]
    m = coleta._itens_mziq(cli, {"empresa": "abc", "categorias": ["cartas"]}, {"nome": "Q"}, [2026, 2025])
    assert [(c.titulo, c.data) for c in m] == [("Carta mensal - SET/26", "2026-09-01")]


def test_data_da_api_vence_a_lida_na_pagina():
    pagina = '<html><a href="https://g.com.br/cartas/historia-2026-01">Carta 01/2026</a></html>'
    api = httpx.Response(200, json=[{"title": "História", "date": "2026-10-05T10:00:00", "link": "https://g.com.br/cartas/historia-2026-01"}])
    cli = _cliente({"https://g.com.br/cartas": pagina, "https://g.com.br/wp-json/wp/v2/cartas": api})
    _, cartas = coleta.conferir({"nome": "G", "url": "https://g.com.br/cartas", "api": "https://g.com.br/wp-json/wp/v2/cartas"}, cli, HOJE)
    assert [(c.link.rsplit("/", 1)[-1], c.data) for c in cartas] == [("historia-2026-01", "2026-10-05")]


def test_gestora_que_parou_de_publicar_vira_parada():
    sit, _ = coleta.conferir({"nome": "V", "url": "https://v.com.br", "sem_publicacao": True, "motivo": "última carta em 2024"},
                             _cliente({}), HOJE)
    assert sit.situacao == "sem_publicacao" and coleta.categoria({"situacao": "sem_publicacao"}, "2024-04-01") == "parada"


def test_trimestre_semestre_e_carta_anual():
    e = lambda t: coleta.extrair_data(t, HOJE)  # noqa: E731
    assert e("carta-de-gestao-sfa-1o-semestre-2026.pdf") == "2026-06-01" and e("4o-trimestre-2025") == "2025-12-01"
    assert e("Carta 2T26") == "2026-06-01" and e("3Q2026") == "2026-09-01" and e("4T26") == ""  # futuro não vale
    assert e("Carta Anual 2023") == "2023-12-01" and e("Outlook 2027") == ""


def test_lista_embutida_na_pagina_e_json_aninhado():
    pagina = ('<script>const cartas=[{date:"2026-09-30",title:"Setembro 2026",pdfUrl:"/wp-content/uploads/2026/10/CARTAMENSAL_26_SETEMBRO.pdf"},'
              '{date:"2026-08-31",title:"Agosto 2026",pdfUrl:"/wp-content/uploads/2026/09/CARTAMENSAL_26_AGOSTO.pdf"}]</script>')
    c = coleta._itens_embutidos(pagina, "https://s.com.br/carta-do-gestor/", {"nome": "S"})
    assert [(x.titulo, x.data) for x in c] == [("Setembro 2026", "2026-09-30"), ("Agosto 2026", "2026-08-31")]
    verde = httpx.Response(200, json={"fundos": [{"nome": "Verde FIC", "report_mes": "/public/files/rel/1/Verde-REL-2026_08.pdf"}]})
    v = coleta._itens_api(_cliente({"https://v.com.br/lista.json": verde}), "https://v.com.br/lista.json", {"nome": "V"})
    assert [(x.titulo, x.link, x.data) for x in v] == [("Verde FIC", "https://v.com.br/public/files/rel/1/Verde-REL-2026_08.pdf", "2026-08-01")]


def test_titulo_com_comeco_do_texto_fica_so_o_titulo():
    t = "Carta Mensal Setembro 2026 Em setembro os dados da economia americana aceleraram de forma brusca. O PMI… Leia mais »"
    assert coleta._encurtar(t) == "Carta Mensal Setembro 2026"
