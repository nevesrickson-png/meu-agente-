"""Consultas de notícias e redes, formatadas em Markdown (usadas pelo MCP e, depois, pelo Terminal).

As ferramentas entregam manchetes, links, contagens e tom calculados aqui; o resumo em texto é do agente,
seguindo `agente/skills/noticias.md`.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from quiron.servicos.biblioteca.trechos import chave
from quiron.servicos.noticias import classificacao, coleta, redes, relevancia, sentimento
from quiron.servicos.mercado.http import FonteIndisponivel

BRT = ZoneInfo("America/Sao_Paulo")
MAX_IDADE_COLETA = timedelta(minutes=15)
_ultima_coleta: datetime | None = None


def _garantir_coleta(forcar: bool = False) -> list[coleta.ResultadoFonte]:
    """Coleta se a última rodada tiver mais de 15 min (os feeds têm cache próprio de 10 min)."""
    global _ultima_coleta
    agora = datetime.now(timezone.utc)
    if forcar or _ultima_coleta is None or agora - _ultima_coleta > MAX_IDADE_COLETA:
        resultados = coleta.coletar()
        _ultima_coleta = agora
        return resultados
    return []


def _hora(d: datetime) -> str:
    return d.astimezone(BRT).strftime("%d/%m %H:%M")


def _linha(n: coleta.Noticia) -> str:
    extras = []
    if n.ativos:
        extras.append(" ".join(n.ativos))
    if n.alertas:
        extras.append("⚠️ " + ", ".join(n.alertas))
    if n.outras_fontes:
        extras.append("também em: " + ", ".join(n.outras_fontes))
    sufixo = f" · {' · '.join(extras)}" if extras else ""
    return f"- [{n.titulo}]({n.link}) — 📊 {n.fonte}, {_hora(n.publicado_em)}{sufixo}"


def linha_historia(h: relevancia.Historia, com_link: bool = True) -> str:
    """Uma linha por história: manchete (link), fonte e hora, quem mais cobriu e os ativos citados."""
    extras = []
    if h.cobertura > 1:
        outros = h.fontes[1:]
        extras.append(f"+{len(outros)} veículo{'s' if len(outros) > 1 else ''} ({', '.join(outros[:3])}{'…' if len(outros) > 3 else ''})")
    if h.ativos:
        extras.append(" ".join(h.ativos[:4]))
    if h.alertas:
        extras.append("⚠️ " + ", ".join(h.alertas))
    titulo = f"[{h.titulo}]({h.link})" if com_link else h.titulo
    return f"- {titulo} — 📊 {h.fonte}, {_hora(h.publicado_em)}" + (f" · {' · '.join(extras)}" if extras else "")


def historias(horas: int = 12, termo: str | None = None) -> list[relevancia.Historia]:
    _garantir_coleta()
    return relevancia.agrupar(_filtrar(coleta.listar(horas, limite=None if termo else 500), termo))


def _filtrar(noticias: list[coleta.Noticia], termo: str | None) -> list[coleta.Noticia]:
    if not termo:
        return noticias
    k = chave(termo)
    alvo = k.replace(" ", "_")
    # "copom" também pega o tema copom_fed; "juros" o tema juros; ticker pelo campo ativos
    temas = {t for t in classificacao.regras().temas if t == alvo or t.startswith(alvo + "_") or t.endswith("_" + alvo)}
    ticker = termo.strip().upper()
    return [n for n in noticias if temas & set(n.temas) or ticker in n.ativos or k in chave(f"{n.titulo} {n.resumo}")]


def noticias(termo: str | None = None, horas: int = 24, limite: int = 15, grupo: str | None = None) -> str:
    """Notícias recentes; `termo` pode ser um tema (juros, inflacao…), um ticker (PETR4) ou uma palavra."""
    _garantir_coleta()
    lista = _filtrar(coleta.listar(horas, limite=None if termo else 500), termo)
    if grupo:
        lista = [n for n in lista if n.grupo == grupo]
    ampliado = ""
    if not lista and termo and horas < 720:  # nada no período: amplia até 30 dias e avisa
        lista = _filtrar(coleta.listar(720, limite=None if termo else 500), termo)
        if lista:
            ampliado = f"_Nada nas últimas {horas}h; mostrando os últimos 30 dias._"
            horas = 720
    titulo = f"## Notícias{' sobre ' + termo if termo else ''} — últimas {horas}h"
    if not lista:
        return f"{titulo}\nNada encontrado. Temas disponíveis: {', '.join(classificacao.regras().temas)}."
    tom = sentimento.tom_medio([n.titulo for n in lista])
    temas = Counter(t for n in lista for t in n.temas).most_common(5)
    agrupadas = relevancia.agrupar(lista) or []
    # com termo: relevância e recência pesam juntas (a mais nova importa); sem termo: relevância
    if termo:
        agrupadas.sort(key=lambda h: -(h.nota + 3 * 0.5 ** ((datetime.now(timezone.utc) - h.publicado_em).total_seconds() / 21600)))
    cab = [
        titulo,
        *([ampliado] if ampliado else []),
        f"{len(lista)} notícias em {len(agrupadas)} histórias · tom das manchetes: **{tom.rotulo}** ({tom.nota:+.2f})",
    ]
    if temas and not termo:
        cab.append("Temas mais citados: " + ", ".join(f"{t} ({q})" for t, q in temas))
    if not agrupadas:  # só ruído no período: mostra as manchetes cruas mesmo assim
        return "\n".join(cab + [_linha(n) for n in lista[:limite]])
    return "\n".join(cab + [linha_historia(h) for h in agrupadas[:limite]])


def top(horas: int = 6, limite: int = 12) -> str:
    """Principais notícias: as mais repetidas entre portais, depois alertas, depois as mais recentes."""
    lista = relevancia.diversificar(historias(horas), limite, max_por_tema=3)
    if not lista:
        return f"## Principais notícias — últimas {horas}h\nNenhuma notícia de mercado coletada."
    return "\n".join([f"## Principais notícias — últimas {horas}h (por relevância: tema, fonte, quantos veículos cobriram e hora)"]
                     + [linha_historia(h) for h in lista])


def alertas(horas: int = 24) -> str:
    _garantir_coleta()
    lista = [n for n in coleta.listar(horas, limite=None) if n.alertas]
    if not lista:
        return f"Nenhuma palavra-alerta nas últimas {horas}h (lista em config/temas_noticias.yaml)."
    return "\n".join([f"## ⚠️ Alertas — últimas {horas}h"] + [_linha(n) for n in lista])


def redes_sociais(termo: str, redes_pedidas: list[str] | None = None, limite: int = 8) -> str:
    """O que Bluesky, Reddit e YouTube estão dizendo, com tom médio por rede."""
    partes = [f"## Redes sociais: {termo}"]
    textos_todos: list[str] = []
    for nome in redes_pedidas or list(redes.REDES):
        try:
            posts = redes.REDES[nome](termo)
        except redes.RedeNaoConfigurada as e:
            partes.append(f"### {nome.capitalize()}\n_{e}_")
            continue
        except FonteIndisponivel as e:
            partes.append(f"### {nome.capitalize()}\n_indisponível: {str(e)[:150]}_")
            continue
        if not posts:
            partes.append(f"### {nome.capitalize()}\nNenhum post recente.")
            continue
        textos = [p.texto for p in posts]
        textos_todos += textos
        tom = sentimento.tom_medio(textos)
        posts.sort(key=lambda p: p.engajamento, reverse=True)
        linhas = [f"### {posts[0].rede} — {len(posts)} posts · tom **{tom.rotulo}** ({tom.nota:+.2f})"]
        for p in posts[:limite]:
            texto = p.texto.replace("\n", " ")
            texto = texto if len(texto) <= 220 else texto[:220].rsplit(" ", 1)[0] + "…"
            detalhe = f" {p.detalhe}" if p.detalhe else ""
            linhas.append(f"- {p.autor}{detalhe} ({_hora(p.publicado_em)}, engajamento {p.engajamento}): {texto} [link]({p.link})")
        partes.append("\n".join(linhas))
    if textos_todos:
        tom = sentimento.tom_medio(textos_todos)
        partes.insert(1, f"Tom geral nas redes: **{tom.rotulo}** ({tom.nota:+.2f}) em {len(textos_todos)} posts.")
    return "\n\n".join(partes)


def sentimento_tema(termo: str, horas: int = 48) -> str:
    """Tom das manchetes sobre o tema/ativo, por fonte, e das redes configuradas."""
    _garantir_coleta()
    lista = _filtrar(coleta.listar(horas, limite=None if termo else 500), termo)
    linhas = [f"## Sentimento: {termo} — últimas {horas}h"]
    if lista:
        geral = sentimento.tom_medio([n.titulo for n in lista])
        linhas.append(f"Manchetes: **{geral.rotulo}** ({geral.nota:+.2f}) em {len(lista)} notícias")
        por_fonte: dict[str, list[str]] = {}
        for n in lista:
            por_fonte.setdefault(n.fonte, []).append(n.titulo)
        for fonte, titulos in sorted(por_fonte.items(), key=lambda x: -len(x[1])):
            t = sentimento.tom_medio(titulos)
            linhas.append(f"- {fonte}: {t.rotulo} ({t.nota:+.2f}, {len(titulos)} notícias)")
    else:
        linhas.append("Nenhuma notícia sobre o tema no período.")
    for nome, func in redes.REDES.items():
        try:
            posts = func(termo)
            if posts:
                t = sentimento.tom_medio([p.texto for p in posts])
                linhas.append(f"- {nome.capitalize()}: {t.rotulo} ({t.nota:+.2f}, {len(posts)} posts)")
        except (redes.RedeNaoConfigurada, FonteIndisponivel):
            linhas.append(f"- {nome.capitalize()}: não configurado/indisponível")
    linhas.append("_Tom por léxico de mercado (conta palavras positivas/negativas): indica direção, não substitui leitura._")
    return "\n".join(linhas)


def status_fontes() -> str:
    resultados = _garantir_coleta(forcar=True)
    linhas = ["| Fonte | Situação | Itens | Detalhe |", "|---|---|---:|---|"]
    linhas += [f"| {r.nome} | {'✅' if r.ok else '❌'} | {r.itens} | {r.detalhe} |" for r in resultados]
    for nome in redes.REDES:
        configurada = {"bluesky": "BLUESKY_APP_PASSWORD", "reddit": "REDDIT_CLIENT_ID", "youtube": "YOUTUBE_API_KEY"}[nome]
        linhas.append(f"| {nome.capitalize()} | {'chave no .env' if redes._env(configurada) else '⚙️ sem chave'} | — | |")
    return "\n".join(linhas)
