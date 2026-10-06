"""Cartas de gestores: confere a página de cada gestora (config/cartas_gestores.yaml) e lista as cartas recentes.

Regras (CLAUDE.md, coleta web): feed RSS/Atom sempre que existir; senão uma leitura da página pública de cartas por dia,
respeitando robots.txt, sem login, sem contornar bloqueio. Guardamos só título, data e link (o conteúdo fica no site
da gestora); `ler_carta` baixa uma carta pública quando o Rickson pede para resumir.

Situação de cada fonte: ativa (carta nos últimos 120 dias) · desatualizada (última carta antiga — pode ter encerrado,
mudado de site ou parado de publicar) · sem_data (achou cartas, mas sem data) · sem_cartas (página no ar, nada
reconhecido) · bloqueada (robots.txt, 401/403) · fora_do_ar (domínio/página não responde ou 404/410).
"""

from __future__ import annotations

import hashlib
import html as _html
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from quiron.nucleo.config import ler_yaml, pasta_dados

UA = "Mozilla/5.0 (compatible; Quiron/1.0; leitor pessoal de cartas de gestores)"
INTERVALO_S = 20 * 3600       # cada fonte é conferida no máximo ~1 vez por dia
DIAS_ATIVA = 120
MESES = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
         "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}
_PALAVRAS = re.compile(r"carta|letter|relat[oó]rio|report|coment[aá]rio|mensal|monthly|gestor|gest[aã]o|insight|outlook|"
                       r"perspectiva|cen[aá]rio|macro|estrat[eé]gi|commentary|research|publica", re.I)
_NAO = re.compile(r"politica|privacidade|cookie|termos|contato|login|cadastr|trabalhe|ouvidoria|whatsapp|linkedin|instagram|"
                  r"facebook|twitter|youtube|mailto:|tel:|javascript:|#$|/tag/|/author/|/page/\d|wp-login|lamina|regulamento|"
                  r"formulario|fato-relevante|comunicado-ao-mercado", re.I)
# documentos que não são carta de gestão (avisos de FII, assembleias, editais…)
_NAO_CARTA = re.compile(r"carta[\s_-]*consulta|emiss[aã]o[\s_-]*de[\s_-]*cotas|assembleia|edital|convoca[cç][aã]o|fato[\s_-]*relevante|"
                        r"comunicado[\s_-]*ao[\s_-]*mercado|aviso[\s_-]*aos[\s_-]*cotistas|informe[\s_-]*de[\s_-]*rendimentos|"
                        r"proposta[\s_-]*da[\s_-]*administra|ata[\s_-]+d[ae]|one[\s_-]?page|l[aâ]mina", re.I)
_GENERICO = re.compile(r"^(baixar|download|pdf|leia mais|saiba mais|clique\b.*|visualizar.*|ver|acesse|acessar|abrir|read more|"
                       r"carta do gestor|carta mensal|carta|relat[oó]rio( mensal)?|coment[aá]rio( mensal)?)$", re.I)
# mês por extenso ou abreviado, nunca dentro de outra palavra ("novidades" não é novembro, "setor" não é setembro)
_MES = (r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|january|february|"
        r"march|april|may|june|july|august|september|october|november|december|jan|fev|feb|mar|abr|apr|mai|jun|jul|ago|"
        r"aug|set|sep|sept|out|oct|nov|dez|dec)(?![a-zçã])")
_TRAVA = threading.Lock()


@dataclass
class Carta:
    fonte: str
    titulo: str
    link: str
    data: str = ""          # AAAA-MM-DD (dia 01 quando só há mês)
    tipo: str = ""


@dataclass
class Situacao:
    fonte: str
    tipo: str
    url: str
    situacao: str
    detalhe: str = ""
    metodo: str = ""         # feed · pagina
    ultima_carta: str = ""
    conferido_em: str = ""


def conectar() -> sqlite3.Connection:
    caminho = pasta_dados() / "cartas.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS cartas (id TEXT PRIMARY KEY, fonte TEXT, tipo TEXT, titulo TEXT, link TEXT, data TEXT,
                                           descoberta_em TEXT);
        CREATE INDEX IF NOT EXISTS cartas_data ON cartas(data);
        CREATE TABLE IF NOT EXISTS situacao (fonte TEXT PRIMARY KEY, tipo TEXT, url TEXT, situacao TEXT, detalhe TEXT,
                                             metodo TEXT, ultima_carta TEXT, conferido_em TEXT);
    """)
    return con


def fontes() -> list[dict]:
    return [f for f in (ler_yaml("cartas_gestores") or {}).get("fontes", []) if f.get("ativo", True)]


def _sem_acento(t: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").lower().strip()


def casar_gestoras(nome: str) -> list[str]:
    """Nomes cadastrados que contêm o termo, sem ligar para acento/maiúscula ("itau" acha "Itaú Asset")."""
    alvo = _sem_acento(nome)
    if len(alvo) < 2:
        return []
    return [f["nome"] for f in fontes() if alvo in _sem_acento(f["nome"])]


# ---------------------------------------------------------------- datas
def extrair_data(texto: str, hoje: date | None = None) -> str:
    """Data no título/link: 2025-09, 09/2025, 15/09/2025, "setembro de 2025", "set/25", "carta-setembro-2025"…"""
    hoje = hoje or date.today()
    t = _html.unescape(texto or "").lower()
    candidatos: list[date] = []
    # "Nov 26, 2025" / "26 de novembro de 2025": mês + dia + ano (tira do texto para "nov 26" não virar novembro/2026)
    for nome, d, a in re.findall(r"\b(?:" + _MES + r")\.?\s+"
                                 r"(\d{1,2}),?\s+(20\d\d)\b", t):
        candidatos.append((int(a), MESES[nome[:3]], int(d)))
    for d, nome, a in re.findall(r"\b(\d{1,2})\s+(?:de\s+)?" + _MES + r"\.?,?\s+(?:de\s+)?(20\d\d)\b", t):
        candidatos.append((int(a), MESES[nome[:3]], int(d)))
    t = re.sub(r"\b(?:" + _MES + r")\.?\s+\d{1,2},?\s+20\d\d\b", " ", t)
    t = re.sub(r"\b\d{1,2}\s+(?:de\s+)?(?:" + _MES + r")\.?,?\s+(?:de\s+)?20\d\d\b", " ", t)
    for d, m, a in re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b", t):
        candidatos.append((int(a), int(m), int(d)))
    for a, m in re.findall(r"(?<!\d)(20\d\d)[-/_.]?(0[1-9]|1[0-2])(?!\d)", t):
        candidatos.append((int(a), int(m), 1))
    for m, a in re.findall(r"(?<!\d)(0[1-9]|1[0-2])[-/_.](20\d\d)(?!\d)", t):
        candidatos.append((int(a), int(m), 1))
    for nome, a in re.findall(r"\b(?:" + _MES + r")"
                              r"[\s/._-]*(?:de[\s_-]+)?(20\d\d|\d\d)\b", t):
        ano = int(a) if len(a) == 4 else 2000 + int(a)
        candidatos.append((ano, MESES[nome[:3]], 1))
    validas = []
    for a, m, d in candidatos:
        try:
            dt = date(a, m, d)
        except ValueError:
            continue
        if date(2010, 1, 1) <= dt <= hoje + timedelta(days=5):  # carta "de outubro" sai no fim do mês; mais que isso é vencimento/agenda
            validas.append(dt)
    return max(validas).isoformat() if validas else ""


# ---------------------------------------------------------------- rede
_ROBOTS: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}


def permitido(url: str, cliente: httpx.Client) -> bool:
    p = urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    ag = time.time()
    if base not in _ROBOTS or ag - _ROBOTS[base][0] > 86400:
        rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
        try:
            r = cliente.get(base + "/robots.txt", timeout=10)
            if r.is_redirect:  # robots.txt que redireciona (site.com → www.site.com): segue, senão leria regra vazia
                with _cliente() as seguidor:
                    r = seguidor.get(base + "/robots.txt", timeout=10)
            if r.status_code >= 400:
                rp = None  # sem robots.txt: permitido
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp = None
        _ROBOTS[base] = (ag, rp)
    rp = _ROBOTS[base][1]
    return True if rp is None else rp.can_fetch(UA, url) and rp.can_fetch("*", url)


def _cliente() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}, follow_redirects=True,
                        timeout=httpx.Timeout(20, connect=10))


# ---------------------------------------------------------------- leitura
def _feeds_da_pagina(texto: str, url: str) -> list[str]:
    feeds = []
    for m in re.finditer(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", texto, re.I):
        h = re.search(r"href=[\"']([^\"']+)", m.group(0))
        if h and "comments" not in h.group(1):
            feeds.append(urljoin(url, _html.unescape(h.group(1))))
    caminho = urlsplit(url).path
    if re.search(r"/(category|categoria)/", caminho):
        feeds.insert(0, url.split("?")[0].rstrip("/") + "/feed/")
    vistos, saida = set(), []
    for f in feeds:
        if f not in vistos:
            vistos.add(f)
            saida.append(f)
    # o feed geral do site ("/feed/") só serve se for o da categoria de cartas: os gerais trazem notícias de tudo
    return [f for f in saida if not re.fullmatch(r"https?://[^/]+/(feed|rss)/?", f)] or []


def _itens_feed(cliente: httpx.Client, feed: str, fonte: dict) -> list[Carta]:
    import feedparser

    r = cliente.get(feed)
    if r.status_code >= 400:
        return []
    f = feedparser.parse(r.content)
    saida = []
    for e in f.entries[:30]:
        titulo = _html.unescape(re.sub(r"<[^>]+>", "", e.get("title", ""))).strip()
        link = e.get("link", "")
        if not titulo or not link or _NAO_CARTA.search(f"{titulo} {link}"):
            continue
        st = e.get("published_parsed") or e.get("updated_parsed")
        data = date(*st[:3]).isoformat() if st else extrair_data(f"{titulo} {link}")
        saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida


def _encurtar(titulo: str, limite: int = 140) -> str:
    """Link com o resumo junto no texto ("Título | By Fulano  Texto…"): fica só o título."""
    titulo = re.split(r"\s+\|\s+by\s+|\s{2,}", titulo, maxsplit=1, flags=re.I)[0].strip()
    return titulo if len(titulo) <= limite else titulo[: limite - 1].rsplit(" ", 1)[0] + "…"


def _itens_pagina(texto: str, url: str, fonte: dict) -> list[Carta]:
    saida, vistos = [], set()
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", texto, re.I | re.S):
        href = _html.unescape(m.group(1)).strip().replace("\\#", "#")
        rotulo = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        link = urljoin(url, href)
        if link.rstrip("/") == url.rstrip("/") or link in vistos or _NAO.search(link) or not link.startswith("http"):
            continue
        pdf = link.lower().split("?")[0].endswith(".pdf")
        alvo = f"{rotulo} {link}"
        if not (pdf or _PALAVRAS.search(alvo)) or _NAO_CARTA.search(alvo):
            continue
        data = extrair_data(alvo)
        if not (pdf or data):  # link comum de menu ("Relatórios") sem data e sem PDF: não é carta
            continue
        vistos.add(link)
        arquivo = re.sub(r"\.pdf$", "", urlsplit(link).path.rsplit("/", 1)[-1], flags=re.I)
        arquivo = re.sub(r"[\s_-]+", " ", _html.unescape(arquivo)).strip()[:120]
        titulo = rotulo if len(rotulo) >= 4 and not _GENERICO.fullmatch(rotulo) else (arquivo or rotulo)
        saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida[:60]


def conferir(fonte: dict, cliente: httpx.Client | None = None, hoje: date | None = None) -> tuple[Situacao, list[Carta]]:
    hoje = hoje or date.today()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    proprio = cliente is None
    cliente = cliente or _cliente()
    url = fonte["url"]
    sit = Situacao(fonte["nome"], fonte.get("tipo", ""), url, "fora_do_ar", conferido_em=agora)
    cartas: list[Carta] = []
    try:
        if not permitido(url, cliente):
            sit.situacao, sit.detalhe = "bloqueada", "o site pede (robots.txt) que robôs não leiam esta página"
            return sit, []
        r = cliente.get(url)
        if r.status_code in (401, 403, 429):
            sit.situacao, sit.detalhe = "bloqueada", f"o site recusou a leitura automática (HTTP {r.status_code}) — abra no navegador"
            return sit, []
        if r.status_code >= 400:
            sit.detalhe = f"página não encontrada (HTTP {r.status_code}) — a gestora pode ter mudado o site ou encerrado"
            return sit, []
        final = str(r.url)
        if urlsplit(final).netloc.replace("www.", "") != urlsplit(url).netloc.replace("www.", ""):
            sit.detalhe = f"redireciona para {urlsplit(final).netloc}"
        feeds = [fonte["feed"]] if fonte.get("feed") else _feeds_da_pagina(r.text, final)
        for f in feeds[:2]:
            try:
                cartas = _itens_feed(cliente, f, fonte)
            except httpx.HTTPError:
                cartas = []
            if cartas:
                sit.metodo = "feed"
                break
        if not cartas:
            cartas = _itens_pagina(r.text, final, fonte)
            sit.metodo = "pagina"
    except httpx.HTTPError as e:
        sit.detalhe = f"não respondeu ({type(e).__name__})"
        return sit, []
    finally:
        if proprio:
            cliente.close()
    datas = sorted((c.data for c in cartas if c.data), reverse=True)
    sit.ultima_carta = datas[0] if datas else ""
    if not cartas:
        sit.situacao = "sem_cartas"
        sit.detalhe = sit.detalhe or "página no ar, mas não reconheci cartas (pode carregar por script ou exigir clique)"
    elif not datas:
        sit.situacao = "sem_data"
    elif (hoje - date.fromisoformat(datas[0])).days <= DIAS_ATIVA:
        sit.situacao = "ativa"
    else:
        sit.situacao = "desatualizada"
        sit.detalhe = sit.detalhe or f"última carta encontrada em {date.fromisoformat(datas[0]):%m/%Y}"
    return sit, cartas


def _gravar(sit: Situacao, cartas: list[Carta]) -> int:
    novas = 0
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _TRAVA, conectar() as con:
        con.execute("INSERT OR REPLACE INTO situacao VALUES (?,?,?,?,?,?,?,?)",
                    (sit.fonte, sit.tipo, sit.url, sit.situacao, sit.detalhe, sit.metodo, sit.ultima_carta, sit.conferido_em))
        for c in cartas:
            ident = hashlib.sha1(c.link.encode()).hexdigest()[:16]
            if con.execute("SELECT 1 FROM cartas WHERE id = ?", (ident,)).fetchone():
                # já conhecida: só corrige título/data (melhorias da leitura valem para as antigas também)
                # leitura sem data (ex.: feed fora do ar, caiu na página) não apaga a data que já se sabia
                con.execute("UPDATE cartas SET titulo = ?, data = COALESCE(NULLIF(?, ''), data) WHERE id = ?",
                            (c.titulo, c.data, ident))
                continue
            con.execute("INSERT INTO cartas VALUES (?,?,?,?,?,?,?)", (ident, c.fonte, c.tipo, c.titulo, c.link, c.data, agora))
            novas += 1
    return novas


def vencidas() -> list[dict]:
    """Fontes nunca conferidas ou conferidas há mais de ~20 h."""
    with conectar() as con:
        quando = {r["fonte"]: r["conferido_em"] for r in con.execute("SELECT fonte, conferido_em FROM situacao")}
    agora = datetime.now(timezone.utc)
    return [f for f in fontes() if not quando.get(f["nome"])
            or (agora - datetime.fromisoformat(quando[f["nome"]])).total_seconds() > INTERVALO_S]


def atualizar(forcar: bool = False, nomes: list[str] | None = None, paralelo: int = 8) -> dict:
    """Confere as fontes vencidas (ou todas, com `forcar`). Devolve o resumo da rodada."""
    from concurrent.futures import ThreadPoolExecutor

    lista = [f for f in fontes() if nomes is None or f["nome"] in nomes]  # [] = nenhuma (não "todas")
    with conectar() as con:
        quando = {r["fonte"]: r["conferido_em"] for r in con.execute("SELECT fonte, conferido_em FROM situacao")}
    agora = datetime.now(timezone.utc)
    if not forcar:
        lista = [f for f in lista if not quando.get(f["nome"])
                 or (agora - datetime.fromisoformat(quando[f["nome"]])).total_seconds() > INTERVALO_S]
    resumo = {"conferidas": 0, "novas": 0}
    if not lista:
        return resumo
    with _cliente() as cliente, ThreadPoolExecutor(max_workers=paralelo) as ex:
        for sit, cartas in ex.map(lambda f: conferir(f, cliente), lista):
            resumo["novas"] += _gravar(sit, cartas)
            resumo["conferidas"] += 1
    return resumo


_EM_ANDAMENTO = threading.Event()
_INICIO = threading.Lock()


def atualizar_em_segundo_plano(forcar: bool = False) -> bool:
    """Para telas: dispara a rodada sem esperar (uma de cada vez). True se começou agora."""
    if not forcar and not vencidas():  # nada vencido: nem abre a thread (a tela pede de novo a cada poucos segundos)
        return False
    with _INICIO:  # dois cliques ao mesmo tempo não disparam duas rodadas
        if _EM_ANDAMENTO.is_set():
            return False
        _EM_ANDAMENTO.set()

    def rodar():
        try:
            atualizar(forcar=forcar)
        except Exception:  # noqa: BLE001 — rede/disco: a próxima abertura tenta de novo
            pass
        finally:
            _EM_ANDAMENTO.clear()

    threading.Thread(target=rodar, daemon=True, name="cartas").start()
    return True


def em_andamento() -> bool:
    return _EM_ANDAMENTO.is_set()


# ---------------------------------------------------------------- consultas
def recentes(dias: int = 60, tipo: str | None = None, termo: str | None = None, limite: int = 80,
             por_fonte: int | None = 4) -> list[dict]:
    """Cartas do período, mais novas primeiro; `por_fonte` evita que uma casa com muitos fundos tome a lista toda."""
    desde = (date.today() - timedelta(days=dias)).isoformat()
    sql = "SELECT * FROM cartas WHERE data >= ? AND data <= ?"
    params: list = [desde, (date.today() + timedelta(days=5)).isoformat()]
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)
    if termo:
        sql += " AND (fonte LIKE ? OR titulo LIKE ?)"
        params += [f"%{termo}%", f"%{termo}%"]
    with conectar() as con:
        linhas = con.execute(sql + " ORDER BY data DESC, descoberta_em DESC LIMIT ?", (*params, limite * 6)).fetchall()
    saida, conta = [], {}
    for l in linhas:
        if por_fonte and not termo and conta.get(l["fonte"], 0) >= por_fonte:
            continue
        conta[l["fonte"]] = conta.get(l["fonte"], 0) + 1
        saida.append(dict(l))
    return saida[:limite]


def da_fonte(nome: str, limite: int = 12) -> list[dict]:
    alvo = _sem_acento(nome)
    with conectar() as con:
        nomes = [r[0] for r in con.execute("SELECT DISTINCT fonte FROM cartas") if alvo and alvo in _sem_acento(r[0])]
        if not nomes:
            return []
        marcas = ",".join("?" * len(nomes))
        return [dict(l) for l in con.execute(f"SELECT * FROM cartas WHERE fonte IN ({marcas}) ORDER BY data DESC LIMIT ?",
                                             (*nomes, limite))]


def situacoes() -> list[dict]:
    with conectar() as con:
        feitas = {r["fonte"]: dict(r) for r in con.execute("SELECT * FROM situacao")}
    saida = []
    for f in fontes():
        s = feitas.get(f["nome"]) or {"fonte": f["nome"], "tipo": f.get("tipo", ""), "url": f["url"], "situacao": "nao_conferida",
                                       "detalhe": "", "metodo": "", "ultima_carta": "", "conferido_em": ""}
        saida.append(s)
    return saida


def _dominio(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def link_conhecido(link: str) -> bool:
    """Só lemos cartas das gestoras cadastradas (ou já listadas): a ferramenta não vira um "baixa qualquer endereço"."""
    if urlsplit(link).scheme not in {"http", "https"}:
        return False
    dom = _dominio(link)
    if any(dom == _dominio(f["url"]) or dom.endswith("." + _dominio(f["url"])) for f in fontes()):
        return True
    with conectar() as con:
        return con.execute("SELECT 1 FROM cartas WHERE link = ?", (link,)).fetchone() is not None


def _endereco_publico(url: str) -> bool:
    """Bloqueia endereços internos (127.0.0.1, rede local…) mesmo vindos de um redirecionamento."""
    import ipaddress
    import socket

    host = urlsplit(url).hostname or ""
    if host in {"localhost"} or host.endswith((".local", ".internal", ".ts.net")):
        return False
    try:
        enderecos = {i[4][0] for i in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return all(ipaddress.ip_address(e.split("%")[0]).is_global for e in enderecos)


def ler_carta(link: str, max_caracteres: int = 14000) -> str:
    """Baixa uma carta pública (PDF ou página) e devolve o texto, para o Quíron resumir. Respeita robots.txt.
    Redirecionamentos são seguidos à mão, um a um, e cada destino passa de novo pelas conferências."""
    url = link
    dados = bytearray()
    tipo = ""
    try:
        with httpx.Client(headers={"User-Agent": UA}, follow_redirects=False, timeout=httpx.Timeout(30, connect=10)) as cliente:
            for salto in range(5):
                # o 1º endereço tem de ser de gestora cadastrada; destinos de redirecionamento (CDN, S3…) só precisam ser
                # públicos — nunca 127.0.0.1/rede local
                if (salto == 0 and not link_conhecido(url)) or urlsplit(url).scheme not in {"http", "https"} \
                        or not _endereco_publico(url):
                    return "Só leio cartas dos sites das gestoras cadastradas em config/cartas_gestores.yaml."
                if not permitido(url, cliente):
                    return "O site pede que robôs não leiam este endereço (robots.txt). Abra a carta no navegador."
                with cliente.stream("GET", url) as r:
                    if r.is_redirect and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        return f"Não consegui abrir a carta (HTTP {r.status_code})."
                    tipo = r.headers.get("content-type", "")
                    for parte in r.iter_bytes():
                        dados.extend(parte)
                        if len(dados) > 15_000_000:
                            return "Arquivo grande demais (mais de 15 MB) para ler aqui."
                break
            else:
                return "A carta redireciona demais; abra no navegador."
    except httpx.HTTPError as e:
        return f"Não consegui abrir a carta agora ({type(e).__name__}). Tente de novo ou abra no navegador."
    dados = bytes(dados)
    link = url
    if "pdf" in tipo or link.lower().split("?")[0].endswith(".pdf") or dados[:4] == b"%PDF":
        import pymupdf

        try:
            with pymupdf.open(stream=dados, filetype="pdf") as doc:
                texto = "\n".join(p.get_text() for p in doc)
        except Exception:  # noqa: BLE001 — PDF corrompido ou protegido
            return "Não consegui ler esse PDF (corrompido ou protegido). Abra no navegador."
    else:
        bruto = dados.decode("utf-8", "replace")
        bruto = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", bruto, flags=re.I | re.S)
        texto = _html.unescape(re.sub(r"<[^>]+>", " ", bruto))
    texto = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", texto)).strip()
    return texto[:max_caracteres] + ("\n\n[… texto cortado]" if len(texto) > max_caracteres else "")
