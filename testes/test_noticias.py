from datetime import datetime, timezone

import httpx
import pytest

from quiron.servicos.mercado import http
from quiron.servicos.noticias import classificacao, coleta, consultas, redes, sentimento
from testes import gravacoes_noticias as g


class Agora(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 3, 20, 0, tzinfo=timezone.utc).astimezone(tz) if tz else datetime(2026, 10, 3, 17, 0)


@pytest.fixture(autouse=True)
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    for v in ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "YOUTUBE_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    http.definir_cliente(httpx.Client(transport=httpx.MockTransport(g.roteador)))
    monkeypatch.setattr(coleta, "ler_fontes", lambda: g.FONTES)
    monkeypatch.setattr(coleta, "datetime", Agora)
    monkeypatch.setattr(consultas, "datetime", Agora)
    monkeypatch.setattr(consultas, "_ultima_coleta", None)
    redes._token_bsky.clear()
    redes._token_reddit.clear()
    yield
    http.definir_cliente(None)


def test_classificacao():
    t = "Itaú e Vale sobem; Magazine Luiza cai após fato relevante. Copom corta a Selic e PETR4 dispara. Vale a pena?"
    assert classificacao.ativos(t) == ["ITUB4", "MGLU3", "PETR4", "VALE3"]
    assert {"copom", "juros", "empresas"} <= set(classificacao.temas(t))
    assert classificacao.alertas(t) == ["fato relevante", "Copom"]
    assert classificacao.ativos("Vale a pena investir na Margem Equatorial") == []


def test_sentimento():
    assert sentimento.tom("Ibovespa dispara com corte de juros").rotulo == "positivo"
    assert sentimento.tom("Ações despencam e risco fiscal pressiona").rotulo == "negativo"
    assert sentimento.tom("Petrobras não sobe").rotulo == "negativo"  # negação inverte
    assert sentimento.tom("Copom reduz a taxa Selic").rotulo == "positivo"
    assert sentimento.tom("Reunião marcada para terça").rotulo == "neutro"


def test_coleta_deduplica_e_isola_fonte_quebrada():
    res = {r.nome: r for r in coleta.coletar()}
    assert res["Portal"].ok and res["Portal"].itens == 3
    assert not res["Quebrado"].ok and "500" in res["Quebrado"].detalhe
    lista = coleta.listar(24 * 30)
    titulos = [n.titulo for n in lista]
    assert titulos.count("Ibovespa dispara com corte de juros e Petrobras sobe") == 1  # mesma manchete em 2 portais
    igual = next(n for n in lista if n.titulo.startswith("Ibovespa"))
    assert igual.outras_fontes == ["Outro"] and igual.ativos == ["PETR4", "VALE3"]
    assert "?utm_source" not in coleta.link_canonico(igual.link)
    # coletar de novo não duplica
    coleta.coletar()
    assert len(coleta.listar(24 * 30)) == len(lista)


def test_consultas_noticias_top_alertas():
    texto = consultas.noticias("PETR4", horas=48)
    assert "Ibovespa dispara" in texto and "+1 veículo (Outro)" in texto and "📊 Portal, 03/10 12:00" in texto
    copom = consultas.noticias("copom", horas=24)  # nada em 24h: amplia para 30 dias
    assert "mostrando os últimos 30 dias" in copom and "Copom reduz a taxa Selic" in copom
    top = consultas.top(24)
    assert "Candidatos a governador" not in top  # sem tema de mercado
    assert top.index("Ibovespa dispara") < top.index("recuperação judicial")  # repetida em 2 portais vem antes
    assert "⚠️ fato relevante, recuperação judicial" in consultas.alertas(24)


def test_redes_sem_chave_ensinam_a_configurar():
    texto = consultas.redes_sociais("copom")
    assert "Senhas de app" in texto and "reddit.com/prefs/apps" in texto and "YouTube Data API v3" in texto


def test_redes_com_chave(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "rickson.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "senha-app")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "segredo")
    monkeypatch.setenv("YOUTUBE_API_KEY", "chave")
    b = redes.bluesky("copom")[0]
    assert b.link == "https://bsky.app/profile/economista.bsky.social/post/3kxyz" and b.engajamento == 48
    r = redes.reddit("copom")[0]
    assert r.detalhe == "r/investimentos" and r.link.startswith("https://www.reddit.com/r/investimentos/")
    y = redes.youtube("copom")[0]
    assert y.engajamento == 15000 and y.link == "https://www.youtube.com/watch?v=abc123"
    texto = consultas.redes_sociais("copom")
    assert "Tom geral nas redes" in texto and "### Bluesky — 1 posts" in texto and "### YouTube" in texto


def test_bluesky_senha_errada(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "rickson.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "errada")
    assert "recusou o login" in consultas.redes_sociais("copom", ["bluesky"])


def test_status_fontes():
    s = consultas.status_fontes()
    assert "| Portal | ✅ | 3 |" in s and "| Quebrado | ❌ |" in s and "⚙️ sem chave" in s
