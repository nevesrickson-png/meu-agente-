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


# ---------------------------------------------------------------- auditoria de 09/10/2026
def test_nao_cartas_ficam_de_fora():
    pagina = "".join(f'<a href="/docs/{n}.pdf">{t}</a>' for n, t in [
        ("a", "Carta Mensal Setembro 2026"), ("b", "Aviso ao Mercado 09/2026"), ("c", "Regulamento 2026-09"),
        ("d", "ASA | Demonstrações Financeiras | Jun-2026"), ("e", "Prospecto definitivo 2026-08"),
        ("f", "Podcast | Sep 23, 2026")])
    cartas = coleta._itens_pagina(pagina, "https://g.com.br/cartas", {"nome": "G"})
    assert [c.titulo for c in cartas] == ["Carta Mensal Setembro 2026"]


def test_titulos_da_auditoria():
    cli = _cliente({"https://a.com.br/cartas": (
        '<a href="/cartas/carta-do-gestor-08-2026-artesanal-cp-fidc/">Continue Lendo</a>'
        '<a href="/up/carta-1788873890239-2026-07.pdf">carta 1788873890239</a>'
        '<a href="/up/x.pdf">Janeiro</a><span>15/01/2026</span>')})
    _, cartas = coleta.conferir({"nome": "A", "url": "https://a.com.br/cartas"}, cli, HOJE)
    titulos = {c.titulo for c in cartas}
    assert "Carta do gestor 08 2026 artesanal cp fidc" in titulos  # "Continue lendo" → nome do endereço
    assert "Carta de 07/2026" in titulos and "Carta de 01/2026" in titulos  # código e só o mês → mês/ano
    assert coleta._encurtar("18:42 Talks about markets Video | Sep 21, 2026") == "Talks about markets"
    assert coleta._encurtar("d0f697c5 115c 4dab 952e b53646acb107 carta junho 2022") == "carta junho 2022"


def test_data_ao_lado_do_link_nao_pega_a_da_vizinha():
    pagina = ('<div><a href="https://j.com/i/a">Market Thoughts: A</a> <time>Oct 9, 2026</time></div>'
              '<div><a href="https://j.com/i/b">Market Thoughts: B</a></div>')
    cartas = coleta._itens_pagina(pagina, "https://j.com/i", {"nome": "J", "link_inclui": r"/i/"})
    assert [(c.link[-1], c.data) for c in cartas] == [("a", "2026-10-09"), ("b", "")]


def test_repetidas_e_faxina(monkeypatch):
    s = coleta.Situacao("G", "gestora", "https://g.com.br", "ativa", conferido_em="2026-10-09T10:00:00+00:00")
    c1 = coleta.Carta("G", "Carta Mensal Setembro 2026", "https://www.g.com.br/c/set.pdf", "2026-09-01")
    assert coleta._gravar(s, [c1]) == 1
    mesmo_pdf = coleta.Carta("G", "Carta Mensal Setembro 2026", "http://g.com.br/c/set.pdf?ver=2", "2026-09-01")
    mesmo_titulo = coleta.Carta("G", "Carta Mensal Setembro 2026", "https://g.com.br/outro/set-2026", "2026-09-01")
    assert coleta._gravar(s, [mesmo_pdf, mesmo_titulo]) == 0
    with coleta.conectar() as con:  # sujeira de antes da correção: repetida + aviso
        con.execute("INSERT INTO cartas VALUES ('x1','G','gestora','Carta Mensal Setembro 2026','https://g.com.br/c/set.pdf?utm_source=a','2026-09-01','2026-10-09')")
        con.execute("INSERT INTO cartas VALUES ('x2','G','gestora','Aviso ao Mercado','https://g.com.br/aviso.pdf','2026-09-02','2026-10-09')")
    r = coleta.limpar_banco()
    assert r["repetidas"] == 1 and r["nao_cartas"] == 1
    with coleta.conectar() as con:
        assert con.execute("SELECT COUNT(*) FROM cartas").fetchone()[0] == 1


def test_paginacao_com_muitas_cartas_na_mesma_data():
    s = coleta.Situacao("G", "gestora", "https://g.com.br", "ativa", conferido_em="2026-10-09T10:00:00+00:00")
    d = date.today().isoformat()
    coleta._gravar(s, [coleta.Carta("G", f"Carta do fundo número {i:02d}", f"https://g.com.br/{i}.pdf", d) for i in range(7)])
    vistos, antes = [], ""
    while True:
        pagina = coleta.feed(dias=0, limite=3, antes=antes)
        if not pagina:
            break
        vistos += [c["id"] for c in pagina]
        antes = f"{pagina[-1]['data']}|{pagina[-1]['id']}"
    assert len(vistos) == 7 == len(set(vistos))  # nenhuma pulada nem repetida


def test_favoritas_novas_rota_e_telegram(monkeypatch):
    from quiron.runtime.carreira_bot import CarreiraBot
    from quiron.servicos.cartas import consultas
    from quiron.terminal.backend.app import app

    monkeypatch.setattr(coleta, "fontes", lambda: [{"nome": n, "url": f"https://{n.lower()}.com.br", "tipo": "gestora"} for n in ("Alfa", "Beta")])
    monkeypatch.setattr(coleta, "atualizar_em_segundo_plano", lambda *a, **k: False)
    with pytest.raises(ValueError):
        coleta.marcar_favorita("Fora do guia")
    assert coleta.marcar_favorita("Beta") == ["Beta"] and coleta.favoritas() == ["Beta"]
    hoje = date.today()
    for nome in ("Alfa", "Beta"):
        s = coleta.Situacao(nome, "gestora", f"https://{nome.lower()}.com.br", "ativa", conferido_em="2026-10-09T10:00:00+00:00")
        coleta._gravar(s, [coleta.Carta(nome, f"Carta mensal de {nome}", f"https://{nome.lower()}.com.br/c.pdf", hoje.isoformat()),
                           coleta.Carta(nome, f"Carta antiga de {nome} achada no histórico", f"https://{nome.lower()}.com.br/v.pdf", "2019-03-01")])
    assert {c["fonte"] for c in coleta.novas()} == {"Alfa", "Beta"}  # só as recentes, não as do histórico
    assert [c["fonte"] for c in coleta.novas(so_favoritas=True)] == ["Beta"]
    texto = consultas.novidades()
    assert texto.index("Beta") < texto.index("Alfa") and "⭐" in texto
    assert CarreiraBot()._comando("cartas", "novas")[0].texto == texto

    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.post("/api/cartas/favorita", json={"nome": "Alfa"}).status_code == 403  # sem o cabeçalho da tela
    h = {"X-Quiron": "terminal"}
    assert c.post("/api/cartas/favorita", json={"nome": "Alfa", "favorita": True}, headers=h).json()["favoritas"] == ["Alfa", "Beta"]
    assert c.post("/api/cartas/favorita", json={"nome": "Beta", "favorita": False}, headers=h).json()["favoritas"] == ["Alfa"]
    assert c.post("/api/cartas/favorita", json={"nome": "Zeta"}, headers=h).status_code == 400
    d = c.get("/api/cartas", params={"categoria": "favoritas", "dias": 30}).json()
    assert {i["fonte"] for i in d["itens"]} == {"Alfa"}
    assert c.get("/api/cartas", params={"antes": f"{hoje.isoformat()}|abc123"}).status_code == 200
    from quiron.runtime.roteamento import rotear

    assert rotear("tem carta nova?", None) == ("cartas", "novas")
