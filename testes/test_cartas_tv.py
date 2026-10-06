"""Cartas de gestores, novas fontes de notícias e a TV do Terminal — tudo sem internet (respostas simuladas)."""

from datetime import date

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos import tv
from quiron.servicos.cartas import coleta
from quiron.servicos.cartas import consultas as cartas_txt

HOJE = date(2026, 10, 6)


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("TERMINAL_SENHA", raising=False)
    coleta._ROBOTS.clear()
    tv._MEMO.clear()
    return tmp_path


# ---------------------------------------------------------------- cartas
def test_extrair_data_formatos_e_futuro():
    assert coleta.extrair_data("Carta Mensal - Setembro de 2026", HOJE) == "2026-09-01"
    assert coleta.extrair_data("https://x.com/wp-content/uploads/2026/08/carta-2026-08.pdf", HOJE) == "2026-08-01"
    assert coleta.extrair_data("Relatório 15/07/2026", HOJE) == "2026-07-15"
    assert coleta.extrair_data("comentario-set-26", HOJE) == "2026-09-01"
    assert coleta.extrair_data("Outlook 2027", HOJE) == ""          # só ano: sem data
    assert coleta.extrair_data("Carta dez/2026", HOJE) == ""         # mês futuro não vale (vencimento, agenda…)
    assert coleta.extrair_data("Carta 2009-05", HOJE) == ""          # antigo demais


PAGINA = """<html><head><title>Cartas</title></head><body>
<a href="/politica-de-privacidade">Política de privacidade</a>
<a href="/cartas">Cartas</a>
<a href="/wp-content/uploads/2026/09/Carta-Mensal-Setembro-2026.pdf">Carta Mensal — Setembro 2026</a>
<a href="/wp-content/uploads/2026/08/Carta-Mensal-Agosto-2026.pdf">Carta Mensal — Agosto 2026</a>
<a href="/relatorio-de-gestao-2t26">Relatório de gestão 2T26</a>
</body></html>"""


def _transporte(rotas: dict):
    def roteador(req: httpx.Request) -> httpx.Response:
        for prefixo, resp in rotas.items():
            if str(req.url).startswith(prefixo):
                return resp() if callable(resp) else resp
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(roteador), follow_redirects=True)


def test_conferir_pagina_ativa_e_grava():
    cli = _transporte({"https://gestora.com.br/cartas": httpx.Response(200, text=PAGINA)})
    sit, cartas = coleta.conferir({"nome": "Gestora X", "url": "https://gestora.com.br/cartas", "tipo": "gestora"}, cli, hoje=HOJE)
    assert sit.situacao == "ativa" and sit.metodo == "pagina" and sit.ultima_carta == "2026-09-01"
    assert [c.data for c in cartas] == ["2026-09-01", "2026-08-01"]  # privacidade e o menu "Cartas" ficam de fora
    assert coleta._gravar(sit, cartas) == 2 and coleta._gravar(sit, cartas) == 0  # sem repetir
    assert coleta.da_fonte("gestora x")[0]["titulo"].startswith("Carta Mensal — Setembro")


def test_conferir_situacoes_de_falha():
    fonte = {"nome": "G", "url": "https://g.com/cartas"}
    robots = _transporte({"https://g.com/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /cartas")})
    assert coleta.conferir(fonte, robots, HOJE)[0].situacao == "bloqueada"
    coleta._ROBOTS.clear()
    assert coleta.conferir(fonte, _transporte({"https://g.com/cartas": httpx.Response(403)}), HOJE)[0].situacao == "bloqueada"
    coleta._ROBOTS.clear()
    sit = coleta.conferir(fonte, _transporte({}), HOJE)[0]
    assert sit.situacao == "fora_do_ar" and "404" in sit.detalhe
    coleta._ROBOTS.clear()
    antiga = PAGINA.replace("2026", "2024")
    sit = coleta.conferir(fonte, _transporte({"https://g.com/cartas": httpx.Response(200, text=antiga)}), HOJE)[0]
    assert sit.situacao == "desatualizada" and "09/2024" in sit.detalhe


FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Cartas</title>
<item><title>Carta do Gestor: setembro</title><link>https://h.com/carta-setembro</link><pubDate>Fri, 02 Oct 2026 10:00:00 +0000</pubDate></item>
</channel></rss>"""


def test_conferir_prefere_o_feed_da_categoria():
    pag = '<link rel="alternate" type="application/rss+xml" href="https://h.com/feed/"><a href="/x">nada</a>'
    cli = _transporte({"https://h.com/category/cartas/feed/": httpx.Response(200, text=FEED),
                       "https://h.com/category/cartas": httpx.Response(200, text=pag)})
    sit, cartas = coleta.conferir({"nome": "H", "url": "https://h.com/category/cartas/"}, cli, HOJE)
    assert sit.metodo == "feed" and cartas[0].data == "2026-10-02" and sit.situacao == "ativa"


def test_lista_e_textos(monkeypatch):
    monkeypatch.setattr(coleta, "fontes", lambda: [{"nome": "Gestora X", "url": "https://gestora.com.br/cartas", "tipo": "gestora"}])
    monkeypatch.setattr(coleta, "atualizar", lambda **k: {"conferidas": 0, "novas": 0})
    hoje = date.today().isoformat()
    sit = coleta.Situacao("Gestora X", "gestora", "https://gestora.com.br/cartas", "ativa", ultima_carta=hoje, conferido_em="2026-10-06T10:00:00+00:00")
    coleta._gravar(sit, [coleta.Carta("Gestora X", "Carta de outubro", "https://gestora.com.br/c.pdf", hoje, "gestora")])
    texto = cartas_txt.listar()
    assert "Gestora X: Carta de outubro" in texto and "https://gestora.com.br/c.pdf" in texto
    assert "Gestora X" in cartas_txt.listar("gestora x") and "Não tenho a gestora" in cartas_txt.listar("Inexistente")
    assert "1 ativas" in cartas_txt.situacao()
    assert coleta.link_conhecido("https://gestora.com.br/qualquer.pdf")
    assert not coleta.link_conhecido("https://outro-site.com/a.pdf") and not coleta.link_conhecido("file:///etc/passwd")
    assert "Só leio cartas" in coleta.ler_carta("http://127.0.0.1:8765/api/sistema")


def test_config_das_cartas_e_das_fontes():
    cfg = yaml.safe_load((PASTA_CONFIG / "cartas_gestores.yaml").read_text(encoding="utf-8"))
    nomes = [f["nome"] for f in cfg["fontes"]]
    assert len(nomes) >= 100 and len(set(nomes)) == len(nomes)
    assert all(f["url"].startswith("http") and f.get("tipo") in {"gestora", "global", "family_office"} for f in cfg["fontes"])
    fontes = yaml.safe_load((PASTA_CONFIG / "fontes_noticias.yaml").read_text(encoding="utf-8"))["fontes"]
    assert len({f["nome"] for f in fontes}) == len(fontes) >= 70
    html = (PASTA_CONFIG.parent / "quiron/terminal/frontend/config.html").read_text(encoding="utf-8")
    for g in {f["grupo"] for f in fontes}:
        assert f"{g}:" in html.split("const GRUPOS_FONTE")[1].split(";")[0]  # todo grupo tem rótulo na tela


def test_rotas_do_bot_para_cartas():
    from quiron.runtime.roteamento import rotear, skills_provaveis

    assert rotear("cartas recentes") == ("cartas", "")
    assert rotear("Quais as últimas cartas de gestores?") == ("cartas", "")
    assert rotear("carta da Dynamo") == ("cartas", "dynamo")
    assert rotear("resuma a carta da Verde") is None  # resumir vai para a IA (lê a carta)
    assert skills_provaveis("resuma a carta da Verde") == ["noticias"]


# ---------------------------------------------------------------- TV
def test_tv_grupos_adicionar_remover_restaurar(monkeypatch):
    padrao = tv.grupos()
    assert padrao[0]["id"] == "meus" and not padrao[0]["canais"]
    ids = [c["id"] for g in padrao for c in g["canais"]]
    assert len(ids) == len(set(ids)) >= 60 and all(tv.ID_CANAL.fullmatch(i) for i in ids)
    monkeypatch.setattr(tv, "resolver", lambda e, cliente=None: {"id": "UCT4nDeU5pv1XIGySbSK-GgA", "nome": "O Primo Rico", "handle": "primorico"})
    tv.adicionar("youtube.com/@primorico")
    assert tv.grupos()[0]["canais"][0]["nome"] == "O Primo Rico"
    cnn = "UCvdwhh_fDyWccR42-rReZLw"
    tv.remover(cnn)
    assert cnn not in tv.todos()
    tv.remover("UCT4nDeU5pv1XIGySbSK-GgA")
    assert not tv.grupos()[0]["canais"]
    assert tv.restaurar() == 1 and cnn in tv.todos()
    with pytest.raises(tv.CanalInvalido):
        tv.remover("../../etc")


def test_tv_resolver_pela_pagina_do_canal():
    pagina = ('<meta property="og:title" content="InfoMoney"><link rel="canonical" '
              'href="https://www.youtube.com/channel/UCxm0tptjIc76-i26EKQ9NpA">')
    cli = _transporte({"https://www.youtube.com/@infomoney": httpx.Response(200, text=pagina)})
    assert tv.resolver("https://www.youtube.com/@infomoney", cli) == {"id": "UCxm0tptjIc76-i26EKQ9NpA", "nome": "InfoMoney", "handle": "infomoney"}
    assert tv.resolver("youtube.com/channel/UCxm0tptjIc76-i26EKQ9NpA", _transporte(
        {"https://www.youtube.com/channel/": httpx.Response(200, text=pagina)}))["id"] == "UCxm0tptjIc76-i26EKQ9NpA"
    for ruim in ["", "https://evil.com/<script>", "javascript:alert(1)"]:
        with pytest.raises(tv.CanalInvalido):
            tv.resolver(ruim, _transporte({}))


FEED_YT = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<entry><yt:videoId>abcdefghijk</yt:videoId><title>Fechamento de mercado</title><published>2026-10-05T21:00:00+00:00</published></entry>
</feed>"""


def test_tv_videos_feed_e_plano_b(monkeypatch):
    canal = "UCxm0tptjIc76-i26EKQ9NpA"
    monkeypatch.setattr(tv, "_cliente", lambda: _transporte({"https://www.youtube.com/feeds/videos.xml": httpx.Response(200, text=FEED_YT)}))
    v = tv.videos(canal)
    assert v["fonte"] == "rss" and v["itens"][0]["id"] == "abcdefghijk" and v["uploads"] == "UU" + canal[2:]
    tv._MEMO.clear()
    monkeypatch.setattr(tv, "_cliente", lambda: _transporte({}))  # feed fora (como na nuvem): a tela toca a playlist de uploads
    assert tv.videos(canal) == {"canal": canal, "itens": [], "fonte": "nenhuma", "uploads": "UU" + canal[2:]}
    with pytest.raises(tv.CanalInvalido):
        tv.videos("x")


# ---------------------------------------------------------------- Terminal
def test_api_tv_e_cartas(monkeypatch):
    from quiron.terminal.backend import app as terminal

    c = TestClient(terminal.app)
    assert c.get("/tv").status_code == 200 and "Quíron — TV" in c.get("/tv").text
    assert c.get("/api/tv/canais").json()["grupos"][1]["canais"]
    assert c.post("/api/tv/canal", json={"entrada": "@x"}).status_code == 403  # sem o cabeçalho da tela
    monkeypatch.setattr(tv, "resolver", lambda e, cliente=None: {"id": "UCT4nDeU5pv1XIGySbSK-GgA", "nome": "O Primo Rico", "handle": ""})
    r = c.post("/api/tv/canal", json={"entrada": "@primorico"}, headers={"X-Quiron": "terminal"})
    assert r.status_code == 200 and r.json()["grupos"][0]["canais"][0]["id"] == "UCT4nDeU5pv1XIGySbSK-GgA"
    assert c.delete("/api/tv/canal/UCT4nDeU5pv1XIGySbSK-GgA").status_code == 403
    assert c.delete("/api/tv/canal/UCT4nDeU5pv1XIGySbSK-GgA", headers={"X-Quiron": "terminal"}).status_code == 200
    assert c.get("/api/tv/videos/nao-e-canal").status_code == 400

    monkeypatch.setattr(coleta, "atualizar_em_segundo_plano", lambda forcar=False: False)
    d = c.get("/api/topico/cartas", params={"aba": "gestoras"}).json()
    assert d["total_fontes"] >= 100 and d["gestoras"][0]["situacao"] == "nao_conferida" and d["itens"] == []
    assert c.post("/api/cartas/atualizar").status_code == 403
    assert c.post("/api/cartas/atualizar", headers={"X-Quiron": "terminal"}).json()["atualizando"] is True
