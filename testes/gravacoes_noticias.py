"""Feeds e respostas de redes no formato real das fontes (conteúdo inventado para teste)."""

import json

import httpx

RSS_PORTAL = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Portal</title>
<item><title>Ibovespa dispara com corte de juros e Petrobras sobe</title><link>https://portal.example/a?utm_source=rss</link>
<pubDate>Sat, 03 Oct 2026 12:00:00 -0300</pubDate><description><![CDATA[<p>A <b>Vale</b> também avança. Vale a pena olhar o PETR4.</p>]]></description></item>
<item><title>Empresa X entra em recuperação judicial</title><link>https://portal.example/b</link>
<pubDate>Sat, 03 Oct 2026 11:00:00 -0300</pubDate><description>Ações despencam após fato relevante.</description></item>
<item><title>Candidatos a governador: veja lista</title><link>https://portal.example/c</link>
<pubDate>Sat, 03 Oct 2026 10:00:00 -0300</pubDate><description>Eleições</description></item>
</channel></rss>"""

RSS_OUTRO = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Outro</title>
<item><title>Ibovespa dispara com corte de juros e Petrobras sobe</title><link>https://outro.example/x</link>
<pubDate>Sat, 03 Oct 2026 12:05:00 -0300</pubDate></item></channel></rss>"""

ATOM_BC = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>BC</title>
<entry><id>1</id><title>Copom reduz a taxa Selic para 13,75% a.a.</title><updated>2026-09-16T18:32:02-03:00</updated>
<link rel="alternate" href="https://www.bcb.gov.br/controleinflacao/comunicadoscopom/1"/><content type="html">Comunicado</content></entry></feed>"""

IBGE = {"items": [{"id": 1, "titulo": "IPCA de setembro sobe 0,40%", "introducao": "Inflação acelera.", "data_publicacao": "02/10/2026 09:00:00",
                   "link": "https://agenciadenoticias.ibge.gov.br/1"}]}

BSKY_POSTS = {"posts": [
    {"uri": "at://did:plc:abc/app.bsky.feed.post/3kxyz", "author": {"handle": "economista.bsky.social"},
     "record": {"text": "Copom acertou: corte de juros com inflação sob controle, otimista com a bolsa", "createdAt": "2026-10-03T12:00:00Z"},
     "likeCount": 40, "repostCount": 5, "replyCount": 3, "indexedAt": "2026-10-03T12:00:01Z"}]}

REDDIT = {"data": {"children": [{"data": {"title": "Copom vai cortar de novo?", "selftext": "Medo de inflação alta voltar",
          "author": "fulano", "permalink": "/r/investimentos/comments/1/copom/", "created_utc": 1791043200, "score": 12,
          "num_comments": 8, "subreddit": "investimentos"}}]}}

YT_BUSCA = {"items": [{"id": {"videoId": "abc123"}, "snippet": {"title": "Copom: o que muda na renda fixa", "description": "Análise",
            "channelTitle": "Canal Finanças", "publishedAt": "2026-10-02T15:00:00Z"}}]}
YT_VIDEOS = {"items": [{"id": "abc123", "statistics": {"viewCount": "15000"}}]}


def roteador(req: httpx.Request) -> httpx.Response:
    h, url = req.url.host, str(req.url)
    if h == "portal.example":
        return httpx.Response(200, text=RSS_PORTAL)
    if h == "outro.example":
        return httpx.Response(200, text=RSS_OUTRO)
    if h == "bc.example":
        return httpx.Response(200, text=ATOM_BC)
    if h == "ibge.example":
        return httpx.Response(200, json=IBGE)
    if h == "quebrado.example":
        return httpx.Response(500)
    if h == "bsky.social" and "createSession" in url:
        corpo = json.loads(req.content)
        return httpx.Response(200 if corpo["password"] == "senha-app" else 401, json={"accessJwt": "tok"})
    if h == "bsky.social" and "searchPosts" in url:
        assert req.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json=BSKY_POSTS)
    if h == "www.reddit.com" and "access_token" in url:
        return httpx.Response(200, json={"access_token": "rt", "token_type": "bearer"})
    if h == "oauth.reddit.com":
        assert req.headers["Authorization"] == "Bearer rt" and "quiron" in req.headers["User-Agent"]
        return httpx.Response(200, json=REDDIT)
    if h == "www.googleapis.com" and "/search" in url:
        return httpx.Response(200, json=YT_BUSCA)
    if h == "www.googleapis.com" and "/videos" in url:
        return httpx.Response(200, json=YT_VIDEOS)
    return httpx.Response(404)


FONTES = [
    {"nome": "Portal", "grupo": "brasil", "url": "https://portal.example/feed"},
    {"nome": "Outro", "grupo": "brasil", "url": "https://outro.example/feed"},
    {"nome": "BC", "grupo": "oficiais", "url": "https://bc.example/feed"},
    {"nome": "IBGE", "grupo": "oficiais", "tipo": "ibge_api", "url": "https://ibge.example/api"},
    {"nome": "Quebrado", "grupo": "global", "url": "https://quebrado.example/feed"},
]
