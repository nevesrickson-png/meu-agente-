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
DIAS_HISTORICO = 7            # as páginas antigas (paginação, arquivo por ano) são percorridas 1 vez por semana
MAX_PAGINAS_HIST = 12         # por gestora, em cada passada pelo histórico
_PAGINACAO = re.compile(r"(?:[?&](?:page|paged|pagina|pg|p)=\d+|/page/\d+/?$|/pagina/\d+/?$)", re.I)
_PROXIMA = re.compile(r"pr[oó]xim|anterior|older|next|mais antigas|ver mais|›|»|&raquo;", re.I)
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
                        r"proposta[\s_-]*da[\s_-]*administra|ata[\s_-]+d[ae]|one[\s_-]?page|l[aâ]mina|\blgpd\b|esclarecimento|"
                        r"pol[ií]tica[\s_-]*de[\s_-]*(privacidade|voto|investimento)", re.I)
_GENERICO = re.compile(r"^(baixar|download|pdf|leia mais|saiba mais|clique\b.*|visualizar.*|ver|acesse|acessar|abrir|read more|"
                       r"acessar documento|ver documento|baixar documento|baixar pdf|download pdf|documento|arquivo|"
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
    historico_em: str = ""   # última vez que as páginas antigas (paginação/arquivo) foram percorridas
    descoberta: str = ""     # página de cartas achada pelo Quíron no site da gestora (endereço mudou etc.)


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
        CREATE INDEX IF NOT EXISTS cartas_fonte ON cartas(fonte, data);
        CREATE TABLE IF NOT EXISTS resumos (link TEXT PRIMARY KEY, texto TEXT, modelo TEXT, feito_em TEXT);
        CREATE TABLE IF NOT EXISTS descobertas (fonte TEXT PRIMARY KEY, url TEXT, achada_em TEXT);
    """)
    colunas = {r[1] for r in con.execute("PRAGMA table_info(situacao)")}
    if "historico_em" not in colunas:  # bancos antigos: coluna nova sem perder nada
        con.execute("ALTER TABLE situacao ADD COLUMN historico_em TEXT DEFAULT ''")
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
_PASTA_UPLOAD = re.compile(r"/(?:wp-content/)?uploads?/20\d\d/\d\d/", re.I)


def extrair_data(texto: str, hoje: date | None = None) -> str:
    """Data no título/link: 2025-09, 09/2025, 15/09/2025, "setembro de 2025", "set/25", "carta-setembro-2025"…
    A pasta de upload do site (/uploads/2025/06/) é o dia em que o arquivo subiu, não o mês da carta: só vale se o
    título/nome do arquivo não trouxer data nenhuma (sites que mudaram de servidor resubiram tudo num mês só)."""
    if _PASTA_UPLOAD.search(texto or ""):
        sem_pasta = _extrair_data(_PASTA_UPLOAD.sub("/", texto), hoje)
        return sem_pasta or _extrair_data(texto, hoje)
    return _extrair_data(texto, hoje)


def _extrair_data(texto: str, hoje: date | None = None) -> str:
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
    # carta anual: "Carta Anual 2023", "Annual Letter 2025" → dezembro daquele ano
    for a in re.findall(r"(?:anual|annual)[\s_-]*(?:de[\s_-]+)?(20\d\d)(?!\d)|(20\d\d)[\s_-]*(?:anual|annual)", t):
        ano = next(x for x in a if x)
        candidatos.append((int(ano), 12, 1))
    # trimestre/semestre: "1º semestre 2026", "4o-trimestre-2025", "2T26", "1S26", "3Q2026" → último mês do período
    for n, tipo, a in re.findall(r"(?<![\d])([1-4])\s*[oº°ª]?[\s_-]*(semestre|trimestre)[\s_-]*(?:de[\s_-]+)?(20\d\d)(?!\d)", t):
        meses = 6 if tipo == "semestre" else 3
        if tipo == "trimestre" or int(n) <= 2:
            candidatos.append((int(a), int(n) * meses, 1))
    for n, tipo, a in re.findall(r"(?<![a-z\d])([1-4])([tqs])[\s_-]?(20\d\d|\d\d)(?![\d])", t):
        if tipo == "s" and int(n) > 2:
            continue
        ano = int(a) if len(a) == 4 else 2000 + int(a)
        candidatos.append((ano, int(n) * (6 if tipo == "s" else 3), 1))
    for d, m, a in re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b", t):
        candidatos.append((int(a), int(m), int(d)))
    for a, m in re.findall(r"(?<!\d)(20\d\d)[-/_.]?(0[1-9]|1[0-2])(?!\d)", t):
        candidatos.append((int(a), int(m), 1))
    for m, a in re.findall(r"(?<!\d)(0[1-9]|1[0-2])[-/_.](20\d\d)(?!\d)", t):
        candidatos.append((int(a), int(m), 1))
    # "(?<![a-zç])" em vez de "\b": "CartaMensal_Ago26.pdf" (mês logo depois de "_") também vale
    for nome, a in re.findall(r"(?<![a-zç])(?:" + _MES + r")"
                              r"[\s/._-]*(?:de[\s_-]+)?(20\d\d|\d\d)(?!\d)", t):
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


_LIXO_FIM = re.compile(r"[\s.…|–-]*(ler mais|leia mais|leia|saiba mais|read more|ver mais|acessar|download|baixar)[\s.…»›>]*$", re.I)
_DATA_INICIO = re.compile(r"^\s*(\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2} de [a-zç]+ de \d{4})\s*[–|:-]?\s+", re.I)


def _encurtar(titulo: str, limite: int = 140) -> str:
    """Link com o resumo junto no texto ("Título | By Fulano  Texto…"): fica só o título, sem "LER MAIS" no fim e sem
    a data repetida no começo (a data já aparece ao lado)."""
    titulo = re.split(r"\s+\|\s+by\s+|\s{2,}", titulo, maxsplit=1, flags=re.I)[0].strip()
    titulo = _LIXO_FIM.sub("", titulo).strip()
    titulo = re.sub(r"\s+\d{1,2}[/.]\d{1,2}[/.]\d{4}$", "", titulo)  # "Relatório de Setembro 2026 07.10.2026"
    sem_data = _DATA_INICIO.sub("", titulo).strip()
    titulo = sem_data if len(sem_data) >= 8 else titulo
    if len(titulo) > 90:  # "Carta Mensal Setembro 2026 Em setembro os dados…": título + começo do texto → só o título
        m = re.match(r"^(.{8,90}?\b20\d\d)\s+[A-ZÀ-Ú][a-zà-ú]", titulo)
        if m:
            titulo = m.group(1)
    return titulo if len(titulo) <= limite else titulo[: limite - 1].rsplit(" ", 1)[0] + "…"


def _paginas_seguintes(texto: str, url: str) -> list[str]:
    """Links de paginação da lista (rel=next, /page/2/, ?page=2, "Próxima", "Anteriores") no mesmo site."""
    host = urlsplit(url).netloc
    achados = []
    for m in re.finditer(r"<(?:a|link)\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)(?:</a>|$)", texto, re.I | re.S):
        tag = m.group(0)[:300]
        link = urljoin(url, _html.unescape(m.group(1)).strip())
        if urlsplit(link).netloc != host or link.rstrip("/") == url.rstrip("/"):
            continue
        rotulo = re.sub(r"<[^>]+>", " ", m.group(2) or "")
        if re.search(r"rel=[\"']?next", tag, re.I) or (_PAGINACAO.search(link) and (_PROXIMA.search(rotulo) or re.fullmatch(r"\s*\d{1,3}\s*", rotulo))):
            if link not in achados:
                achados.append(link)
    return achados


def _itens_api(cliente: httpx.Client, api: str, fonte: dict) -> list[Carta]:
    """Lista pública em JSON que a própria página da gestora usa (ex.: WordPress /wp-json/wp/v2/posts?categories=…).
    Aceita uma lista de objetos com título/data/link em nomes comuns (title.rendered, titulo, date, data, link, url…)."""
    r = cliente.get(api)
    if r.status_code >= 400:
        return []
    try:
        dados = r.json()
    except ValueError:
        return []
    def primeira_lista(v, nivel=0):
        """A lista de itens pode vir solta ou dentro de um objeto ({"data": [...]}, {"fundos": [...]})."""
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and nivel < 3:
            for filho in v.values():
                achada = primeira_lista(filho, nivel + 1)
                if achada and isinstance(achada[0], dict):
                    return achada
        return []

    dados = primeira_lista(dados)
    saida = []

    def valor(v):
        """Desembrulha formatos comuns: WordPress {"rendered": …}, Strapi {"data": {"attributes": {"url": …}}}."""
        for _ in range(4):
            if isinstance(v, list):
                v = v[0] if v else ""
            if not isinstance(v, dict):
                break
            v = v.get("rendered") or v.get("url") or v.get("data") or v.get("attributes") or ""
        return v if isinstance(v, (str, int, float)) else ""

    def campo(item: dict, *nomes: str) -> str:
        for n in nomes:
            v = valor(item.get(n))
            if v:
                return str(v)
        return ""

    for item in dados[:300] if isinstance(dados, list) else []:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("attributes"), dict):  # Strapi: os campos ficam dentro de "attributes"
            item = {**item, **item["attributes"]}
        titulo = _html.unescape(re.sub(r"<[^>]+>", "", campo(item, "title", "titulo", "nome", "name"))).strip()
        link = urljoin(api, campo(item, "source_url", "pdfUrl", "report_mes", "link", "url", "arquivo", "file", "pdf", "href",
                                  "document", "documento", "anexo"))
        if not titulo or not link.startswith("http") or _NAO_CARTA.search(f"{titulo} {link}"):
            continue
        bruto = campo(item, "date", "data", "published", "publishDate", "publicado_em", "dataPublicacao", "created_at",
                      "createdArticleTimeStamp", "timeInfo", "timestamp")
        if re.fullmatch(r"1\d{9}(\d{3})?", bruto.strip()):  # carimbo em segundos ou milissegundos
            seg = int(bruto.strip()[:10])
            data = datetime.fromtimestamp(seg, timezone.utc).date().isoformat()
        else:
            data = bruto[:10] if re.match(r"20\d\d-\d\d-\d\d", bruto) else extrair_data(f"{bruto} {titulo} {link}")
        saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida


def _itens_sitemap(cliente: httpx.Client, mapa: str, fonte: dict) -> list[Carta]:
    """sitemap.xml oficial do site (lista pública de páginas com data): só os endereços que casam com `link_inclui`."""
    if not fonte.get("link_inclui") or not permitido(mapa, cliente):
        return []
    r = cliente.get(mapa)
    if r.status_code >= 400:
        return []
    filtro = re.compile(fonte["link_inclui"], re.I)
    saida = []
    for bloco in re.findall(r"<url>(.*?)</url>", r.text, re.S | re.I)[:5000]:
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", bloco, re.S)
        if not loc or not filtro.search(loc.group(1)):
            continue
        link = _html.unescape(loc.group(1))
        mod = re.search(r"<lastmod>\s*(20\d\d-\d\d-\d\d)", bloco)
        lesma = urlsplit(link).path.rstrip("/").rsplit("/", 1)[-1]
        titulo = re.sub(r"[-_]+", " ", re.sub(r"\.\w+$", "", lesma)).strip().capitalize()
        if not titulo or _NAO_CARTA.search(f"{titulo} {link}"):
            continue
        data = extrair_data(f"{titulo} {link}") or (mod.group(1) if mod else "")
        saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    saida.sort(key=lambda c: c.data, reverse=True)
    return saida[:300]


def _itens_mziq(cliente: httpx.Client, cfg: dict, fonte: dict, anos: list[int]) -> list[Carta]:
    """Sites na plataforma MZ: a lista de documentos vem da API pública que a própria página chama (POST com o ano e as
    categorias de cartas, cadastrados em `mziq: {empresa, categorias}`)."""
    url = f"https://apicatalog.mziq.com/filemanager/company/{cfg['empresa']}/filter/categories/year/meta"
    if not permitido(url, cliente):
        return []
    saida = []
    for ano in anos:
        r = cliente.post(url, json={"year": str(ano), "categories": list(cfg.get("categorias") or []), "language": "pt_BR",
                                    "published": True})
        if r.status_code >= 400:
            continue
        try:
            metas = ((r.json() or {}).get("data") or {}).get("document_metas") or []
        except ValueError:
            continue
        for m in metas:
            titulo, link = str(m.get("file_title") or "").strip(), str(m.get("file_url") or "")
            if not titulo or not link.startswith("http") or _NAO_CARTA.search(titulo):
                continue
            pub = str(m.get("file_published_date") or "")
            data = extrair_data(titulo) or (pub[:10] if re.match(r"20\d\d-\d\d-\d\d", pub) else "")
            saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida


def _itens_lista_txt(cliente: httpx.Client, cfg: dict, fonte: dict) -> list[Carta]:
    """Lista pública em texto (uma carta por linha, ex.: "2026_09") + modelo do endereço do PDF ("…/{linha}.pdf")."""
    if not permitido(cfg["url"], cliente):
        return []
    r = cliente.get(cfg["url"])
    if r.status_code >= 400:
        return []
    saida = []
    for linha in r.text.splitlines():
        linha = linha.strip()
        if not re.fullmatch(r"[\w.-]{4,40}", linha):
            continue
        data = extrair_data(linha.replace("_", "-"))
        titulo = f"Carta do gestor {data[5:7]}/{data[:4]}" if data else linha
        saida.append(Carta(fonte["nome"], titulo, cfg["modelo_link"].replace("{linha}", linha), data, fonte.get("tipo", "")))
    return saida


def _itens_embutidos(texto: str, url: str, fonte: dict) -> list[Carta]:
    """Lista de cartas escrita dentro do HTML como dados de script (ex.: `const cartas=[{date, title, pdfUrl}]`)."""
    saida = []
    for obj in re.findall(r"\{[^{}]{10,800}\}", texto):
        def chave(*nomes: str) -> str:
            for n in nomes:
                m = re.search(r"[\"']?" + n + r"[\"']?\s*:\s*[\"']([^\"']+)[\"']", obj)
                if m:
                    return _html.unescape(m.group(1).replace("\\/", "/"))
            return ""
        link = chave("pdfUrl", "pdf", "url", "link", "arquivo", "file", "href")
        titulo = chave("title", "titulo", "nome", "name")
        if not link or not titulo or not re.search(r"\.pdf|/carta|/relat", link, re.I):
            continue
        link = urljoin(url, link)
        data = extrair_data(f"{chave('date', 'data', 'publicado')} {titulo} {link}")
        if not _NAO_CARTA.search(f"{titulo} {link}"):
            saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida


def _itens_pagina(texto: str, url: str, fonte: dict, limite: int = 200) -> list[Carta]:
    saida, vistos = [], set()
    filtro = re.compile(fonte["link_inclui"], re.I) if fonte.get("link_inclui") else None
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", texto, re.I | re.S):
        href = _html.unescape(m.group(1)).strip().replace("\\#", "#")
        rotulo = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        link = urljoin(url, href)
        if link.rstrip("/") == url.rstrip("/") or link in vistos or _NAO.search(link) or not link.startswith("http"):
            continue
        pdf = link.lower().split("?")[0].endswith(".pdf")
        alvo = f"{rotulo} {link}"
        if filtro is not None:  # a gestora tem um padrão de link de carta conhecido: só ele vale
            if not filtro.search(link) or _NAO_CARTA.search(alvo):
                continue
        elif not (pdf or _PALAVRAS.search(alvo)) or _NAO_CARTA.search(alvo):
            continue
        data = extrair_data(alvo)
        if not (pdf or data or filtro is not None):  # link comum de menu ("Relatórios") sem data e sem PDF: não é carta
            continue
        vistos.add(link)
        arquivo = re.sub(r"\.pdf$", "", urlsplit(link).path.rsplit("/", 1)[-1], flags=re.I)
        arquivo = re.sub(r"[\s_-]+", " ", _html.unescape(arquivo)).strip()[:120]
        titulo = rotulo if len(rotulo) >= 4 and not _GENERICO.fullmatch(rotulo) else (arquivo or rotulo)
        if (_GENERICO.fullmatch(titulo) or not re.search(r"[A-Za-zÀ-ÿ]{3}", titulo) or re.fullmatch(r"[\w-]{20,}", titulo)) and data:
            a, m, _ = data.split("-")
            titulo = f"Carta de {m}/{a}"  # "Acessar documento" ou arquivo com nome de código: diz pelo menos o mês
        saida.append(Carta(fonte["nome"], _encurtar(titulo), link, data, fonte.get("tipo", "")))
    return saida[:limite]


def _ler_lista(cliente: httpx.Client, url: str, fonte: dict, com_feed: bool) -> tuple[str, list[Carta], str, str]:
    """(situação provisória, cartas, método, texto da página) de UMA página de lista. Situação vazia = leu."""
    if not permitido(url, cliente):
        return "bloqueada", [], "", ""
    r = cliente.get(url)
    if r.status_code in (401, 403, 429):
        return f"bloqueada {r.status_code}", [], "", ""
    if r.status_code >= 400:
        return f"fora_do_ar {r.status_code}", [], "", ""
    final = str(r.url)
    if com_feed:
        feeds = [fonte["feed"]] if fonte.get("feed") else _feeds_da_pagina(r.text, final)
        for f in feeds[:2]:
            try:
                itens = _itens_feed(cliente, f, fonte)
            except httpx.HTTPError:
                itens = []
            if itens:
                return "", itens, "feed", r.text
    return "", _itens_pagina(r.text, final, fonte), "pagina", r.text


def _historico_feed(cliente: httpx.Client, feed: str, fonte: dict, conhecidos: set[str]) -> list[Carta]:
    """Feeds do WordPress aceitam ?paged=2, 3…: cada página traz cartas mais antigas."""
    saida = []
    for n in range(2, MAX_PAGINAS_HIST + 2):
        url = f"{feed}{'&' if '?' in feed else '?'}paged={n}"
        if not permitido(url, cliente):
            break
        try:
            itens = _itens_feed(cliente, url, fonte)
        except httpx.HTTPError:
            break
        novos = [c for c in itens if c.link not in conhecidos]
        if not novos:
            break
        conhecidos.update(c.link for c in novos)
        saida += novos
    return saida


_CAMINHOS_COMUNS = ("cartas", "cartas-mensais", "carta-do-gestor", "carta-mensal", "cartas-de-gestao", "cartas-do-gestor",
                    "relatorios", "relatorios-de-gestao", "conteudos", "conteudo", "publicacoes", "documentos", "insights")
_LINK_CARTAS = re.compile(r"cart|relat[oó]ri|coment[aá]ri|publica|conte[uú]d|insight|letter|report|document|gest[aã]o", re.I)


def _dominio_base(host: str) -> str:
    partes = host.lower().removeprefix("www.").split(".")
    return ".".join(partes[-3:]) if partes[-1] == "br" and len(partes) >= 3 else ".".join(partes[-2:])


def descobrir(fonte: dict, cliente: httpx.Client, atual: str = "") -> tuple[str, list[Carta]] | None:
    """Procura no próprio site da gestora a página de cartas que rende mais (página mudou de endereço, lista em outro
    lugar…). Lê a página inicial, os links do mesmo site com cara de "cartas/relatórios" e alguns caminhos comuns —
    no máximo 14 páginas, sempre respeitando robots.txt. Devolve (url, cartas) só se achar cartas datadas mais novas que
    `atual` (e pelo menos 2)."""
    p = urlsplit(fonte["url"])
    raiz = f"{p.scheme}://{p.netloc}/"
    base = _dominio_base(p.netloc)
    candidatos: list[str] = []
    try:
        if permitido(raiz, cliente):
            r = cliente.get(raiz)
            if r.status_code < 400:
                final = str(r.url)
                base = _dominio_base(urlsplit(final).netloc)  # site que mudou de domínio: segue o novo
                for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", r.text, re.I | re.S):
                    link = urljoin(final, _html.unescape(m.group(1)).strip())
                    rotulo = re.sub(r"<[^>]+>", " ", m.group(2))
                    if (_dominio_base(urlsplit(link).netloc) == base and link.startswith("http") and not _NAO.search(link)
                            and _LINK_CARTAS.search(f"{rotulo} {urlsplit(link).path}") and not link.lower().endswith(".pdf")):
                        if link not in candidatos:
                            candidatos.append(link)
                raiz = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}/"
    except httpx.HTTPError:
        pass
    candidatos = candidatos[:10] + [raiz + c + "/" for c in _CAMINHOS_COMUNS if raiz + c + "/" not in candidatos]
    melhor: tuple[str, list[Carta]] | None = None
    melhor_chave = (atual or "", 1)
    for url in candidatos[:14]:
        if url.rstrip("/") == fonte["url"].rstrip("/"):
            continue
        try:
            estado, itens, _, _ = _ler_lista(cliente, url, fonte, com_feed=True)
        except httpx.HTTPError:
            continue
        datas = [c.data for c in itens if c.data]
        if estado or len(datas) < 2:
            continue
        chave = (max(datas), len(datas))
        if chave > melhor_chave:
            melhor, melhor_chave = (url, itens), chave
    return melhor


def conferir(fonte: dict, cliente: httpx.Client | None = None, hoje: date | None = None,
             historico: bool = False) -> tuple[Situacao, list[Carta]]:
    """Lê as páginas de cartas da gestora (principal + `paginas` + `api` do cadastro). Com `historico`, segue também a
    paginação (e o `?paged=` do feed) para trás, até MAX_PAGINAS_HIST páginas."""
    hoje = hoje or date.today()
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    proprio = cliente is None
    cliente = cliente or _cliente()
    url = fonte["url"]
    sit = Situacao(fonte["nome"], fonte.get("tipo", ""), url, "fora_do_ar", conferido_em=agora)
    if fonte.get("encerrada") or fonte.get("sem_publicacao"):  # conferido à mão: nem vai ao site
        sit.situacao = "encerrada" if fonte.get("encerrada") else "sem_publicacao"
        sit.detalhe = str(fonte.get("motivo") or ("a gestora encerrou ou foi incorporada" if fonte.get("encerrada")
                                                  else "não publica mais cartas abertas ao público"))
        if proprio:
            cliente.close()
        return sit, []
    cartas: list[Carta] = []
    vistos: set[str] = set()

    def juntar(itens: list[Carta], confiavel: bool = False) -> None:
        """`confiavel`: data vinda de API/feed/sitemap (campo de data do próprio site) vale mais que a lida no texto."""
        for c in itens:
            if c.link not in vistos:
                vistos.add(c.link)
                cartas.append(c)
            elif confiavel and c.data:
                for i, antiga in enumerate(cartas):
                    if antiga.link == c.link:
                        cartas[i] = c
                        break

    try:
        estado, itens, metodo, texto = _ler_lista(cliente, url, fonte, com_feed=True)
        codigo = estado.partition(" ")[2]
        if estado == "bloqueada":
            sit.situacao, sit.detalhe = "bloqueada", "o site pede (robots.txt) que robôs não leiam esta página — abra no navegador"
        elif estado.startswith("bloqueada"):
            sit.situacao, sit.detalhe = "bloqueada", f"o site recusou a leitura automática (HTTP {codigo}) — abra no navegador"
        elif estado.startswith("fora_do_ar"):
            sit.detalhe = f"página não encontrada (HTTP {codigo}) — a gestora pode ter mudado o site ou encerrado"
        sit.metodo = metodo
        juntar(itens)
        if fonte.get("embutido") and texto:
            juntar(_itens_embutidos(texto, url, fonte), confiavel=True)
        fila_hist = _paginas_seguintes(texto, url) if historico and texto and metodo == "pagina" else []
        if historico and metodo == "feed":
            feed = fonte.get("feed") or (_feeds_da_pagina(texto, url) or [""])[0]
            if feed:
                juntar(_historico_feed(cliente, feed, fonte, set(vistos)))
        for api in ([fonte["api"]] if isinstance(fonte.get("api"), str) else fonte.get("api") or []):
            try:
                juntar(_itens_api(cliente, api, fonte), confiavel=True)
                sit.metodo = sit.metodo or "api"
            except httpx.HTTPError:
                pass
        if fonte.get("mziq"):
            try:
                ano = hoje.year
                juntar(_itens_mziq(cliente, fonte["mziq"], fonte, list(range(ano, ano - 6, -1)) if historico else [ano, ano - 1]),
                       confiavel=True)
                sit.metodo = sit.metodo or "api"
            except httpx.HTTPError:
                pass
        if fonte.get("lista_txt"):
            try:
                juntar(_itens_lista_txt(cliente, fonte["lista_txt"], fonte), confiavel=True)
                sit.metodo = sit.metodo or "api"
            except httpx.HTTPError:
                pass
        if fonte.get("sitemap"):
            try:
                juntar(_itens_sitemap(cliente, fonte["sitemap"], fonte), confiavel=True)
                sit.metodo = sit.metodo or "sitemap"
            except httpx.HTTPError:
                pass
        extras = list(fonte.get("paginas") or [])
        if fonte.get("descoberta") and fonte["descoberta"] not in extras:
            extras.append(fonte["descoberta"])
        for extra in extras:  # outras páginas da mesma gestora (outro fundo, arquivo por ano, a que o Quíron descobriu…)
            try:
                e_estado, e_itens, _, e_texto = _ler_lista(cliente, extra, fonte, com_feed=False)
            except httpx.HTTPError:
                continue
            if not e_estado:
                juntar(e_itens)
                if historico:
                    fila_hist += _paginas_seguintes(e_texto, extra)
        lidas = set()
        while fila_hist and len(lidas) < MAX_PAGINAS_HIST:  # histórico: segue a paginação para trás
            prox = fila_hist.pop(0)
            if prox in lidas:
                continue
            lidas.add(prox)
            try:
                h_estado, h_itens, _, h_texto = _ler_lista(cliente, prox, fonte, com_feed=False)
            except httpx.HTTPError:
                continue
            if h_estado:
                continue
            antes = len(cartas)
            juntar(h_itens)
            if len(cartas) > antes:  # página que não trouxe nada novo não abre mais paginação
                fila_hist += [p for p in _paginas_seguintes(h_texto, prox) if p not in lidas]
        if historico:
            sit.historico_em = agora
            datas_ate_aqui = [c.data for c in cartas if c.data]
            recente = max(datas_ate_aqui) if datas_ate_aqui else ""
            velha = not recente or (hoje - date.fromisoformat(recente)).days > DIAS_ATIVA
            if velha and sit.situacao != "bloqueada" and not fonte.get("descoberta_fixa"):
                achado = descobrir(fonte, cliente, recente)
                if achado:
                    sit.descoberta = achado[0]
                    juntar(achado[1])
    except httpx.HTTPError as e:
        if not cartas:
            sit.detalhe = f"não respondeu ({type(e).__name__})"
            return sit, []
    finally:
        if proprio:
            cliente.close()
    if sit.situacao == "bloqueada" and not cartas:
        return sit, []
    datas = sorted((c.data for c in cartas if c.data), reverse=True)
    sit.ultima_carta = datas[0] if datas else ""
    if not cartas:
        if sit.situacao != "fora_do_ar" or not sit.detalhe:
            sit.situacao = "sem_cartas"
            sit.detalhe = sit.detalhe or "página no ar, mas não reconheci cartas (pode carregar por script ou exigir clique)"
    elif not datas:
        sit.situacao, sit.detalhe = "sem_data", ""
    elif (hoje - date.fromisoformat(datas[0])).days <= DIAS_ATIVA:
        sit.situacao, sit.detalhe = "ativa", ""
    else:
        sit.situacao = "desatualizada"
        sit.detalhe = f"última carta encontrada em {date.fromisoformat(datas[0]):%m/%Y}"
    return sit, cartas


def _gravar(sit: Situacao, cartas: list[Carta]) -> int:
    novas = 0
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _TRAVA, conectar() as con:
        if not sit.historico_em:
            antiga = con.execute("SELECT historico_em FROM situacao WHERE fonte = ?", (sit.fonte,)).fetchone()
            sit.historico_em = (antiga[0] or "") if antiga else ""
        con.execute("INSERT OR REPLACE INTO situacao(fonte, tipo, url, situacao, detalhe, metodo, ultima_carta, conferido_em, "
                    "historico_em) VALUES (?,?,?,?,?,?,?,?,?)",
                    (sit.fonte, sit.tipo, sit.url, sit.situacao, sit.detalhe, sit.metodo, sit.ultima_carta, sit.conferido_em,
                     sit.historico_em))
        if sit.descoberta:
            con.execute("INSERT OR REPLACE INTO descobertas VALUES (?,?,?)", (sit.fonte, sit.descoberta, agora))
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
    with conectar() as con:
        hist = {r["fonte"]: r["historico_em"] or "" for r in con.execute("SELECT fonte, historico_em FROM situacao")}

    def precisa_historico(f: dict) -> bool:
        h = hist.get(f["nome"])
        return not h or (agora - datetime.fromisoformat(h)).days >= DIAS_HISTORICO

    with conectar() as con:
        achadas = {r["fonte"]: r["url"] for r in con.execute("SELECT fonte, url FROM descobertas")}
    lista = [{**f, "descoberta": achadas[f["nome"]]} if f["nome"] in achadas else f for f in lista]
    with _cliente() as cliente, ThreadPoolExecutor(max_workers=paralelo) as ex:
        for sit, cartas in ex.map(lambda f: conferir(f, cliente, historico=precisa_historico(f)), lista):
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


# ---------------------------------------------------------------- tela de Cartas (aba própria)
DIAS_ESPORADICA = 400  # publica pouco (trimestral/semestral/anual) mas segue viva


def categoria(sit: dict, ultima: str, hoje: date | None = None) -> str:
    """ativa (carta em até 120 dias) · esporadica (até ~13 meses: trimestrais/semestrais) · parada (mais que isso) ·
    encerrada (cadastro diz que fechou) · sem_leitura (site bloqueia, fora do ar ou cartas sem data)."""
    hoje = hoje or date.today()
    if sit.get("situacao") == "encerrada":
        return "encerrada"
    if sit.get("situacao") == "sem_publicacao":
        return "parada"
    if not ultima:
        return "sem_leitura"
    dias = (hoje - date.fromisoformat(ultima)).days
    return "ativa" if dias <= DIAS_ATIVA else "esporadica" if dias <= DIAS_ESPORADICA else "parada"


def gestoras() -> list[dict]:
    """Todas as gestoras do guia com situação, total de cartas guardadas, última carta e categoria."""
    with conectar() as con:
        cont = {r["fonte"]: (r["n"], r["ultima"] or "", r["sem_data"])
                for r in con.execute("SELECT fonte, COUNT(*) n, MAX(NULLIF(data, '')) ultima, "
                                     "SUM(CASE WHEN data = '' OR data IS NULL THEN 1 ELSE 0 END) sem_data FROM cartas GROUP BY fonte")}
    saida = []
    hoje = date.today()
    for s in situacoes():
        n, ultima, sem_data = cont.get(s["fonte"], (0, "", 0))
        ultima = min(ultima, (hoje + timedelta(days=5)).isoformat()) if ultima else ""
        saida.append({**s, "total": n, "sem_data": sem_data, "ultima_carta": ultima or s.get("ultima_carta") or "",
                      "categoria": categoria(s, ultima or s.get("ultima_carta") or "", hoje)})
    return saida


def feed(dias: int = 120, tipo: str | None = None, termo: str | None = None, antes: str | None = None,
         limite: int = 60, gestoras_nomes: list[str] | None = None) -> list[dict]:
    """Cartas de todas as gestoras, mais novas primeiro, em páginas (`antes` = data da última já mostrada)."""
    teto = (date.today() + timedelta(days=5)).isoformat()
    sql = "SELECT c.*, r.texto IS NOT NULL AS tem_resumo FROM cartas c LEFT JOIN resumos r ON r.link = c.link WHERE c.data != '' AND c.data <= ?"
    params: list = [teto]
    if dias:
        sql += " AND c.data >= ?"
        params.append((date.today() - timedelta(days=dias)).isoformat())
    if antes:
        sql += " AND c.data < ?"
        params.append(antes)
    if tipo:
        sql += " AND c.tipo = ?"
        params.append(tipo)
    if termo:
        sql += " AND (c.fonte LIKE ? OR c.titulo LIKE ?)"
        params += [f"%{termo}%", f"%{termo}%"]
    if gestoras_nomes is not None:
        if not gestoras_nomes:
            return []
        sql += f" AND c.fonte IN ({','.join('?' * len(gestoras_nomes))})"
        params += gestoras_nomes
    with conectar() as con:
        linhas = con.execute(sql + " ORDER BY c.data DESC, c.descoberta_em DESC LIMIT ?", (*params, limite)).fetchall()
    return [dict(l) for l in linhas]


def historico(nome: str) -> dict | None:
    """Todas as cartas guardadas de uma gestora (nome exato do guia), da mais nova à mais antiga; sem data no fim."""
    sit = next((g for g in gestoras() if g["fonte"] == nome), None)
    if not sit:
        return None
    with conectar() as con:
        cartas = [dict(l) for l in con.execute(
            "SELECT c.*, r.texto IS NOT NULL AS tem_resumo FROM cartas c LEFT JOIN resumos r ON r.link = c.link WHERE c.fonte = ? "
            "ORDER BY c.data = '', c.data DESC, c.descoberta_em DESC", (nome,))]
    return {"gestora": sit, "cartas": cartas}


SISTEMA_RESUMO = (
    "Você resume cartas de gestores de investimento para um assessor de investimentos brasileiro. Escreva em português, "
    "em tópicos curtos: 1) Cenário (macro Brasil e mundo) na visão do gestor; 2) Como a carteira está posicionada e o que "
    "mudou; 3) Principais teses e ativos/setores citados; 4) Riscos e o que o gestor vigia; 5) Uma frase-chave da carta, "
    "entre aspas. Use só o que está no texto: não invente números nem opiniões; se o texto não trouxer algo, omita o "
    "tópico. No máximo 250 palavras.")


def resumo_guardado(link: str) -> str | None:
    with conectar() as con:
        r = con.execute("SELECT texto FROM resumos WHERE link = ?", (link,)).fetchone()
    return r[0] if r else None


def resumir(link: str) -> dict:
    """Resumo da carta pela IA (guardado: a mesma carta nunca é resumida duas vezes)."""
    if guardado := resumo_guardado(link):
        return {"resumo": guardado, "guardado": True}
    texto = ler_carta(link)
    if len(texto) < 400 or texto.startswith(("Só leio", "O site pede", "Não consegui", "Arquivo grande", "A carta redireciona")):
        return {"erro": texto if len(texto) < 400 else "texto curto demais para resumir"}
    from quiron.nucleo import cerebro

    r = cerebro.perguntar(f"Carta (texto extraído do site da gestora):\n\n{texto}", sistema=SISTEMA_RESUMO, max_tokens=4000)
    resumo = (r.texto or "").strip()
    if not resumo:
        return {"erro": "a IA não devolveu o resumo; tente de novo"}
    with _TRAVA, conectar() as con:
        con.execute("INSERT OR REPLACE INTO resumos VALUES (?,?,?,?)",
                    (link, resumo, getattr(r, "modelo", ""), datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return {"resumo": resumo, "guardado": False}
