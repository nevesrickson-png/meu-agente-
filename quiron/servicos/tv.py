"""TV do Terminal (/tv): canais do YouTube em grupos, com os vídeos mais recentes de cada um.

- Lista padrão em `config/tv_canais.yaml`; o que o Rickson muda pela tela vai para `dados/ajustes/tv_canais.yaml`
  (`meus`: canais adicionados; `ocultos`: ids escondidos) — o padrão continua recebendo melhorias.
- Vídeos recentes: YouTube Data API (se houver YOUTUBE_API_KEY) → sem lista (a tela toca a playlist de uploads do
  próprio canal pelo player oficial, que sempre funciona). O feed RSS (/feeds/videos.xml) NÃO é usado: o robots.txt do
  YouTube o proíbe para programas.
- Ao vivo primeiro: `ao_vivo` lê a página pública /channel/<id>/live (permitida no robots.txt) e diz se o canal está
  transmitindo agora, com o vídeo, o título e quantos assistem; a tela toca a transmissão antes dos vídeos gravados.
- O player é o embed oficial do YouTube (youtube-nocookie.com); nada é baixado nem regravado.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx

from quiron.nucleo.config import escrever_ajuste, ler_ajuste, ler_yaml

ID_CANAL = re.compile(r"^UC[\w-]{22}$")
_HANDLE = re.compile(r"^@?([\w.\-]{3,60})$")
_MEMO: dict[str, tuple[float, dict]] = {}
VALIDADE_S = 15 * 60
UA = "Mozilla/5.0 (compatible; Quiron/1.0; TV pessoal)"


class CanalInvalido(ValueError):
    pass


def _env(nome: str) -> str:
    return os.environ.get(nome, "").split(" #")[0].strip()


def grupos() -> list[dict[str, Any]]:
    """Grupos com os canais visíveis (padrão − ocultos + os seus em "Meus canais")."""
    base = (ler_yaml("tv_canais", com_ajustes=False) or {}).get("grupos") or []
    ajuste = ler_ajuste("tv_canais")
    ocultos = set(ajuste.get("ocultos") or [])
    saida = []
    for g in base:
        canais = [dict(c, grupo=g["id"]) for c in g.get("canais") or [] if c["id"] not in ocultos]
        if canais:
            saida.append({"id": g["id"], "nome": g["nome"], "canais": canais})
    meus = [dict(c, grupo="meus", meu=True) for c in ajuste.get("meus") or [] if c.get("id") not in ocultos]
    saida.insert(0, {"id": "meus", "nome": "Meus canais", "canais": meus})
    return saida


def todos() -> dict[str, dict]:
    return {c["id"]: c for g in grupos() for c in g["canais"]}


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})


def resolver(entrada: str, cliente: httpx.Client | None = None) -> dict:
    """Link do canal, @handle ou id UC… → {"id", "nome", "handle"}. Lê só a página pública do canal (ou a Data API)."""
    t = (entrada or "").strip()
    if not t:
        raise CanalInvalido("Cole o link do canal (youtube.com/@nome) ou o @ do canal.")
    if m := re.search(r"youtube\.com/channel/(UC[\w-]{22})", t):
        t = m.group(1)
    handle = ""
    if ID_CANAL.fullmatch(t):
        url = f"https://www.youtube.com/channel/{t}"
    else:
        m = re.search(r"youtube\.com/@([\w.\-]{3,60})", t) or _HANDLE.fullmatch(t)
        if not m:
            raise CanalInvalido("Não reconheci. Use o link do canal (youtube.com/@nome ou youtube.com/channel/UC…) ou @nome.")
        handle = m.group(1)
        url = f"https://www.youtube.com/@{handle}"
    chave = _env("YOUTUBE_API_KEY")
    if chave:  # caminho oficial, quando existir a chave
        params = {"part": "snippet", "key": chave, **({"id": t} if ID_CANAL.fullmatch(t) else {"forHandle": "@" + handle})}
        try:
            r = httpx.get("https://www.googleapis.com/youtube/v3/channels", params=params, timeout=15)
            itens = r.json().get("items") or []
            if itens:
                return {"id": itens[0]["id"], "nome": itens[0]["snippet"]["title"], "handle": handle}
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    proprio = cliente is None
    cliente = cliente or _cliente()
    try:
        r = cliente.get(url, headers={"Cookie": "CONSENT=YES+"})  # evita a página de consentimento
    except httpx.HTTPError as e:
        raise CanalInvalido(f"O YouTube não respondeu ({type(e).__name__}). Tente de novo.") from e
    finally:
        if proprio:
            cliente.close()
    if r.status_code >= 400:
        raise CanalInvalido("Canal não encontrado no YouTube. Confira o link.")
    html = r.text
    ident = (re.search(r'<meta itemprop="identifier" content="(UC[\w-]{22})"', html)
             or re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
             or re.search(r'"externalId":"(UC[\w-]{22})"', html) or re.search(r'"channelId":"(UC[\w-]{22})"', html))
    if not ident:
        raise CanalInvalido("Não consegui ler o canal. Cole o link no formato youtube.com/channel/UC… (aparece em Sobre → Compartilhar canal).")
    nome = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    from html import unescape

    return {"id": ident.group(1), "nome": unescape(nome.group(1)) if nome else (handle or ident.group(1)), "handle": handle}


def adicionar(entrada: str, nome: str = "") -> dict:
    canal = resolver(entrada)
    if nome.strip():
        canal["nome"] = nome.strip()[:60]
    ajuste = ler_ajuste("tv_canais")
    ocultos = [i for i in ajuste.get("ocultos") or [] if i != canal["id"]]
    meus = [c for c in ajuste.get("meus") or [] if c.get("id") != canal["id"]]
    ja_no_padrao = any(c["id"] == canal["id"] for g in (ler_yaml("tv_canais", com_ajustes=False) or {}).get("grupos", [])
                       for c in g.get("canais") or [])
    if not ja_no_padrao:
        if len(meus) >= 200:
            raise CanalInvalido("Limite de 200 canais seus.")
        meus.append({"nome": canal["nome"][:60], "id": canal["id"], "handle": canal.get("handle", "")})
    ajuste["meus"], ajuste["ocultos"] = meus, ocultos
    _gravar(ajuste)
    return canal


def remover(ident: str) -> bool:
    """Canal seu: sai da lista. Canal do padrão: fica escondido (volta com `restaurar`)."""
    if not ID_CANAL.fullmatch(ident or ""):
        raise CanalInvalido("Canal inválido.")
    ajuste = ler_ajuste("tv_canais")
    meus = [c for c in ajuste.get("meus") or [] if c.get("id") != ident]
    mudou = len(meus) != len(ajuste.get("meus") or [])
    padrao = {c["id"] for g in (ler_yaml("tv_canais", com_ajustes=False) or {}).get("grupos", []) for c in g.get("canais") or []}
    ocultos = list(ajuste.get("ocultos") or [])
    if ident in padrao and ident not in ocultos:
        ocultos.append(ident)
        mudou = True
    ajuste["meus"], ajuste["ocultos"] = meus, ocultos
    _gravar(ajuste)
    return mudou


def restaurar() -> int:
    """Mostra de novo os canais do padrão que foram escondidos."""
    ajuste = ler_ajuste("tv_canais")
    n = len(ajuste.pop("ocultos", None) or [])
    _gravar(ajuste)
    return n


def _gravar(ajuste: dict) -> None:
    limpo = {k: v for k, v in ajuste.items() if v}
    escrever_ajuste("tv_canais", limpo)


# ---------------------------------------------------------------- vídeos recentes
def _da_api(canal: str, chave: str) -> list[dict]:
    r = httpx.get("https://www.googleapis.com/youtube/v3/playlistItems", timeout=15,
                  params={"part": "snippet", "playlistId": "UU" + canal[2:], "maxResults": "15", "key": chave})
    r.raise_for_status()
    saida = []
    for i in r.json().get("items") or []:
        sn = i.get("snippet") or {}
        vid = (sn.get("resourceId") or {}).get("videoId")
        if vid:
            saida.append({"id": vid, "titulo": sn.get("title", ""), "publicado": sn.get("publishedAt", ""),
                          "miniatura": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
    return saida


def videos(canal: str) -> dict:
    """Últimos vídeos do canal. `fonte`: api · nenhuma (a tela usa a playlist de uploads no player)."""
    if not ID_CANAL.fullmatch(canal or ""):
        raise CanalInvalido("Canal inválido.")
    agora = time.time()
    if canal in _MEMO and agora - _MEMO[canal][0] < VALIDADE_S:
        return _MEMO[canal][1]
    itens, fonte = [], "nenhuma"
    chave = _env("YOUTUBE_API_KEY")
    if chave:
        try:
            itens, fonte = _da_api(canal, chave), "api"
        except (httpx.HTTPError, ValueError):
            pass
    res = {"canal": canal, "itens": itens[:15], "fonte": fonte, "uploads": "UU" + canal[2:]}
    _MEMO[canal] = (agora, res)
    return res


_VIVO: dict[str, tuple[float, dict]] = {}
VALIDADE_VIVO_S = 180


def ao_vivo(canal: str, cliente: httpx.Client | None = None) -> dict:
    """{"ao_vivo", "video", "titulo", "assistindo"} pela página pública /live do canal (3 min de cache)."""
    if not ID_CANAL.fullmatch(canal or ""):
        raise CanalInvalido("Canal inválido.")
    agora = time.time()
    if canal in _VIVO and agora - _VIVO[canal][0] < VALIDADE_VIVO_S:
        return _VIVO[canal][1]
    res = {"canal": canal, "ao_vivo": False, "video": "", "titulo": "", "assistindo": None}
    proprio = cliente is None
    cliente = cliente or _cliente()
    try:
        html = cliente.get(f"https://www.youtube.com/channel/{canal}/live", headers={"Cookie": "CONSENT=YES+"}).text
    except httpx.HTTPError:
        return res  # sem resposta: não guarda, tenta na próxima
    finally:
        if proprio:
            cliente.close()
    principal = re.search(r'"videoPrimaryInfoRenderer":\{"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"\}.{0,600}?"isLive":true'
                          r'(?:,"originalViewCount":"(\d+)")?', html, re.S)
    video = re.search(r'"currentVideoEndpoint":\{.{0,400}?"videoId":"([\w-]{11})"', html, re.S) \
        or re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', html) \
        or re.search(r'"watchEndpoint":\{"videoId":"([\w-]{11})"', html)
    # live AGENDADA (às vezes há anos, nunca começou) também aparece em /live com "isLive": não conta como no ar —
    # aí a tela toca os vídeos mais recentes do canal
    agendada = re.search(r'"isUpcoming":true|"status":"LIVE_STREAM_OFFLINE"|"scheduledStartTime":"\d+"', html)
    if principal and video and not agendada:
        titulo = json.loads(f'"{principal.group(1)}"') if principal.group(1) else ""
        res.update(ao_vivo=True, video=video.group(1), titulo=titulo[:140],
                   assistindo=int(principal.group(2)) if principal.group(2) else None)
    _VIVO[canal] = (agora, res)
    return res


def ao_vivo_varios(canais: list[str], paralelo: int = 6) -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor

    validos = [c for c in dict.fromkeys(canais) if ID_CANAL.fullmatch(c or "")][:40]
    with _cliente() as cli, ThreadPoolExecutor(max_workers=paralelo) as ex:
        return {r["canal"]: r for r in ex.map(lambda c: ao_vivo(c, cli), validos)}
