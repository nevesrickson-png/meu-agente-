"""Redes sociais pelas APIs oficiais: Bluesky (senha de app), Reddit (app "script", OAuth) e YouTube (Data API v3).

Sem a chave no `.env`, a rede responde com o passo a passo para criar a chave gratuita — nunca quebra.
Respeita os limites gratuitos com cache de 15 min por busca.
"""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from quiron.nucleo.config import ler_yaml
from quiron.servicos.mercado import http
from quiron.servicos.mercado.http import FonteIndisponivel, obter

TTL_BUSCA = 15 * 60

COMO_CONFIGURAR = {
    "bluesky": (
        "Bluesky não configurado. No app do Bluesky: Configurações → Privacidade e segurança → Senhas de app → "
        "Adicionar. Ponha no .env: BLUESKY_HANDLE=seu.usuario.bsky.social e BLUESKY_APP_PASSWORD=a-senha-gerada."
    ),
    "reddit": (
        "Reddit não configurado. Entre em https://www.reddit.com/prefs/apps → 'create another app' → tipo 'script', "
        "redirect uri http://localhost:8080. Ponha no .env: REDDIT_CLIENT_ID (o código abaixo do nome do app) e "
        "REDDIT_CLIENT_SECRET (o 'secret'). Se o Reddit pedir aprovação do app, uso pessoal/não comercial costuma ser aceito."
    ),
    "youtube": (
        "YouTube não configurado. Em https://console.cloud.google.com: crie um projeto → 'APIs e serviços' → ative "
        "'YouTube Data API v3' → Credenciais → Criar credencial → Chave de API. Ponha no .env: YOUTUBE_API_KEY=a-chave. "
        "Cota gratuita: ~100 buscas por dia."
    ),
}


class RedeNaoConfigurada(Exception):
    pass


@dataclass
class Post:
    rede: str
    autor: str
    texto: str
    link: str
    publicado_em: datetime
    engajamento: int  # curtidas+reposts+respostas / pontos+comentários / visualizações
    detalhe: str = ""  # subreddit, canal…


def _env(nome: str) -> str:
    return os.environ.get(nome, "").split(" #")[0].strip()


def _dt(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------- Bluesky

_token_bsky: dict[str, tuple[str, float]] = {}  # usuário → (token, vale até)


def _login(nome: str, url: str, chave: str, **kw) -> tuple[str, int | None]:
    """POST de login com os mesmos cuidados do resto da coleta: nunca no offline; rede fora vira FonteIndisponivel."""
    from quiron.nucleo import offline

    if offline.ativo():
        raise FonteIndisponivel(f"{nome}: versão offline (sem internet)")
    try:
        r = http.cliente().post(url, **kw)
        dados = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as e:
        raise FonteIndisponivel(f"{nome}: não consegui fazer login ({type(e).__name__})") from e
    if not dados.get(chave):
        raise FonteIndisponivel(f"{nome} recusou o login ({r.status_code}): confira as credenciais")
    return dados[chave], dados.get("expires_in")


def _sessao_bluesky() -> str:
    usuario, senha = _env("BLUESKY_HANDLE"), _env("BLUESKY_APP_PASSWORD")
    if not usuario or not senha:
        raise RedeNaoConfigurada(COMO_CONFIGURAR["bluesky"])
    token, vale = _token_bsky.get(usuario, ("", 0.0))
    if time.time() >= vale:  # o token do Bluesky dura ~2 h: renova antes
        token, _ = _login("Bluesky", "https://bsky.social/xrpc/com.atproto.server.createSession", "accessJwt",
                          json={"identifier": usuario, "password": senha})
        _token_bsky[usuario] = (token, time.time() + 90 * 60)
    return token


def bluesky(termo: str, limite: int = 25) -> list[Post]:
    token = _sessao_bluesky()
    idioma = ((ler_yaml("redes") or {}).get("bluesky") or {}).get("idioma")
    params = {"q": termo, "limit": str(limite), "sort": "latest", **({"lang": idioma} if idioma else {})}
    r = obter("https://bsky.social/xrpc/app.bsky.feed.searchPosts", params=params, fonte="Bluesky", ttl=TTL_BUSCA,
              cabecalhos={"Authorization": f"Bearer {token}"})
    posts = []
    for p in r.conteudo.get("posts", []):
        autor = p["author"]
        rkey = p["uri"].rsplit("/", 1)[-1]
        posts.append(
            Post("Bluesky", f"@{autor['handle']}", p["record"].get("text", ""), f"https://bsky.app/profile/{autor['handle']}/post/{rkey}",
                 _dt(p["record"].get("createdAt") or p["indexedAt"]),
                 int(p.get("likeCount", 0)) + int(p.get("repostCount", 0)) + int(p.get("replyCount", 0)))
        )
    return posts


# ---------------------------------------------------------------- Reddit

_token_reddit: dict[str, tuple[str, float]] = {}  # app → (token, vale até)
_UA_REDDIT = "python:quiron:0.1 (uso pessoal)"


def _token_do_reddit() -> str:
    cid, segredo = _env("REDDIT_CLIENT_ID"), _env("REDDIT_CLIENT_SECRET")
    if not cid or not segredo:
        raise RedeNaoConfigurada(COMO_CONFIGURAR["reddit"])
    token, vale = _token_reddit.get(cid, ("", 0.0))
    if time.time() >= vale:  # ~24 h; renova 10 min antes
        basico = base64.b64encode(f"{cid}:{segredo}".encode()).decode()
        token, dura = _login("Reddit", "https://www.reddit.com/api/v1/access_token", "access_token",
                             data={"grant_type": "client_credentials"},
                             headers={"Authorization": f"Basic {basico}", "User-Agent": _UA_REDDIT})
        _token_reddit[cid] = (token, time.time() + max(60, int(dura or 3600) - 600))
    return token


def reddit(termo: str, limite: int = 25, subreddits: list[str] | None = None) -> list[Post]:
    token = _token_do_reddit()
    subs = subreddits or ((ler_yaml("redes") or {}).get("reddit") or {}).get("subreddits") or ["investimentos"]
    url = f"https://oauth.reddit.com/r/{'+'.join(subs)}/search"
    params = {"q": termo, "restrict_sr": "1", "sort": "new", "t": "week", "limit": str(limite)}
    r = obter(url, params=params, fonte="Reddit", ttl=TTL_BUSCA, cabecalhos={"Authorization": f"Bearer {token}", "User-Agent": _UA_REDDIT})
    posts = []
    for filho in r.conteudo.get("data", {}).get("children", []):
        d = filho["data"]
        texto = d.get("title", "") + (f" — {d['selftext'][:300]}" if d.get("selftext") else "")
        posts.append(
            Post("Reddit", f"u/{d.get('author')}", texto, f"https://www.reddit.com{d.get('permalink', '')}",
                 datetime.fromtimestamp(d.get("created_utc", 0), timezone.utc),
                 int(d.get("score", 0)) + int(d.get("num_comments", 0)), f"r/{d.get('subreddit')}")
        )
    return posts


# ---------------------------------------------------------------- YouTube


def youtube(termo: str, limite: int = 15) -> list[Post]:
    chave = _env("YOUTUBE_API_KEY")
    if not chave:
        raise RedeNaoConfigurada(COMO_CONFIGURAR["youtube"])
    cfg = (ler_yaml("redes") or {}).get("youtube") or {}
    # arredondado à hora: com segundos a chave do cache mudava a cada chamada (100 unidades de cota por busca)
    desde = (datetime.now(timezone.utc) - timedelta(days=int(cfg.get("dias", 7)))).strftime("%Y-%m-%dT%H:00:00Z")
    params = {"part": "snippet", "q": termo, "type": "video", "order": "relevance", "maxResults": str(limite),
              "publishedAfter": desde, "regionCode": cfg.get("regiao", "BR"), "relevanceLanguage": cfg.get("idioma", "pt"), "key": chave}
    r = obter("https://www.googleapis.com/youtube/v3/search", params=params, fonte="YouTube", ttl=TTL_BUSCA)
    itens = [i for i in r.conteudo.get("items", []) if i.get("id", {}).get("videoId")]
    views: dict[str, int] = {}
    if itens:  # estatísticas custam 1 unidade de cota para até 50 vídeos
        ids = ",".join(i["id"]["videoId"] for i in itens)
        est = obter("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics", "id": ids, "key": chave},
                    fonte="YouTube", ttl=TTL_BUSCA)
        views = {v["id"]: int(v.get("statistics", {}).get("viewCount", 0)) for v in est.conteudo.get("items", [])}
    return [
        Post("YouTube", i["snippet"].get("channelTitle", ""), f"{i['snippet'].get('title', '')} — {i['snippet'].get('description', '')[:200]}",
             f"https://www.youtube.com/watch?v={quote(i['id']['videoId'])}", _dt(i["snippet"]["publishedAt"]),
             views.get(i["id"]["videoId"], 0), "visualizações")
        for i in itens
    ]


REDES = {"bluesky": bluesky, "reddit": reddit, "youtube": youtube}
