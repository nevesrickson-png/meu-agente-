"""Briefing do dia montado em Python: formato fixo, números conferidos, pronto para ler no celular.

A IA só escreve as 2–3 linhas de "Para os clientes" (opinião de colega sênior a partir destes dados); qualquer número
que ela citar e que não esteja no briefing faz a linha ser descartada. Sem IA (cota esgotada, offline), o briefing sai
igual, só sem essas linhas. Usado pelo /briefing do Telegram, pela rotina das 7h30, pelo MCP e pelo Terminal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from quiron.servicos.mercado import abertos, bcb, cotacoes, painel, tesouro
from quiron.servicos.mercado.http import FonteIndisponivel

BRT = ZoneInfo("America/Sao_Paulo")
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# Divulgações do IBGE que mexem com mercado (as outras ficam de fora do briefing)
IBGE_IMPORTANTES = (r"Preços ao Consumidor Amplo(?! -? ?15)", r"Preços ao Consumidor Amplo 15", r"Produto Interno Bruto|Contas Nacionais",
                    r"Produção Física - Brasil|Industrial Mensal: Produção Física(?! - Regional)",
                    r"Pesquisa Mensal de Comércio", r"Pesquisa Mensal de Serviços", r"Amostra de Domicílios Contínua.*(?:Mensal|Trimestral)")
NOMES_IBGE = {"Amplo 15": "IPCA-15", "Amplo": "IPCA", "Produto Interno": "PIB", "Contas Nacionais": "PIB", "Produção Física": "Produção industrial",
              "Comércio": "Vendas no varejo", "Serviços": "Serviços (PMS)", "Domicílios": "Desemprego (PNAD)"}
ERROS = (FonteIndisponivel, ValueError, KeyError, IndexError, OSError)


@dataclass
class Briefing:
    texto: str
    contexto: str  # o que a IA pode usar para o comentário
    fontes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _var(v: float | None, casas: int = 2, sufixo: str = "%") -> str:
    """▲ alta, ▼ queda, = estável (convenção do Quíron)."""
    if v is None:
        return ""
    if abs(v) < 0.5 * 10 ** -casas:
        return "= estável"
    return f"{'▲' if v > 0 else '▼'}{_br(abs(v), casas)}{sufixo}"


def _bps(v: float | None) -> str:
    if v is None:
        return ""
    bps = round(v * 100)
    return "=" if bps == 0 else f"{'▲' if bps > 0 else '▼'}{abs(bps)} bps"


def _mes(d: date) -> str:
    return f"{MESES[d.month - 1]}/{d:%y}"


def _tentar(func: Callable[[], str | None], avisos: list[str], rotulo: str) -> str | None:
    try:
        return func()
    except ERROS as e:
        avisos.append(f"{rotulo} indisponível ({type(e).__name__})")
        return None


# ---------------------------------------------------------------- blocos


def _juros(fontes: list[str], avisos: list[str]) -> list[str]:
    linhas = []
    partes = []
    for chave, rotulo in (("selic_meta", "Selic"), ("cdi", "CDI")):
        s = _tentar(lambda c=chave: bcb.sgs(c, 2), avisos, rotulo)
        if s:
            partes.append(f"{rotulo} {painel._pct(s.ultimo.valor)}")
            if s.desatualizado:
                avisos.append(f"{rotulo}: ⚠️ desatualizado (Banco Central fora do ar)")
            fonte_bc = f"Banco Central {s.obtido_em.astimezone(BRT):%H:%M}"
    if partes:
        linhas.append(" · ".join(partes))
        fontes.append(fonte_bc)
    tab = _tentar(tesouro.titulos_atuais, avisos, "Tesouro Direto")
    if tab:
        anterior = _taxas_anteriores(tab.data_base, avisos)
        alvo = {"prefixado": (3, 6), "ipca_mais": (3, 9, 19)}  # anos à frente: curto, médio e longo
        for chave, prazos in alvo.items():
            titulos = tesouro.por_tipo(tab, chave)
            escolhidos = []
            for anos in prazos:
                if not titulos:
                    break
                t = min(titulos, key=lambda x: abs((x.vencimento - tab.data_base).days / 365.25 - anos))
                if t not in escolhidos:
                    escolhidos.append(t)
            itens = []
            for t in escolhidos:
                taxa = t.taxa_compra or t.taxa_venda
                if taxa is None:
                    continue
                antes = anterior.get((t.tipo, t.vencimento))
                rotulo = f"{'Pré' if chave == 'prefixado' else 'IPCA+'} {t.vencimento.year}"
                # variação só taxa de compra × taxa de compra (o histórico guarda só a de compra; 0,00 = sem oferta)
                delta = f" ({_bps(t.taxa_compra - antes)})" if t.taxa_compra and antes else ""
                itens.append(f"{rotulo} {painel._pct(taxa)}{delta}")
            if itens:
                linhas.append(" · ".join(itens))
        fontes.append(f"Tesouro (base {tab.data_base:%d/%m})")
        if tab.desatualizado:
            avisos.append("Tesouro: ⚠️ desatualizado")
    return linhas


def _taxas_anteriores(base: date, avisos: list[str]) -> dict[tuple[str, date], float]:
    """Taxas do pregão anterior à data-base, para a variação em bps."""
    saida: dict[tuple[str, date], float] = {}
    for chave in ("prefixado", "ipca_mais"):
        try:
            hist, _ = tesouro.historico_taxas(chave)
        except ERROS:
            return {}
        datas = sorted({d for d, _, _ in hist if d < base})
        if not datas:
            continue
        ontem = datas[-1]
        nome = tesouro.TIPOS[chave][0]
        saida.update({(nome, venc): taxa for d, venc, taxa in hist if d == ontem})
    return saida


def _inflacao(fontes: list[str], avisos: list[str], ano: int) -> list[str]:
    partes = []
    s = _tentar(lambda: bcb.sgs("ipca_12m", 2), avisos, "IPCA 12m")
    if s:
        partes.append(f"IPCA 12m {painel._pct(s.ultimo.valor)} ({_mes(s.ultimo.data)})")
    focus_partes = []
    for ind, a, rot in (("ipca", ano, f"IPCA {ano}"), ("ipca", ano + 1, f"{ano + 1}"), ("selic", ano + 1, f"Selic fim de {ano + 1}")):
        e = _tentar(lambda i=ind, y=a: bcb.focus(i, y), avisos, f"Focus {rot}")
        if not e:
            continue
        d = e.mediana - e.mediana_semana_anterior if e.mediana_semana_anterior is not None else None
        semana = f" ({_var(d, sufixo=' p.p.')} na semana)" if d is not None and abs(d) >= 0.005 else ""
        focus_partes.append(f"{rot} {painel._pct(e.mediana)}{semana}")
        coleta = e.data
    if focus_partes:
        partes.append("Focus: " + " · ".join(focus_partes))
        fontes.append(f"Focus ({coleta:%d/%m})")
    return [" · ".join(partes[:1]), *partes[1:]] if partes else []


def _mercados(fontes: list[str], avisos: list[str]) -> tuple[list[str], str]:
    itens, contexto = [], []
    referencia = ""
    for ativo, rotulo in (("USDBRL", "Dólar"), ("IBOV", "Ibovespa"), ("^GSPC", "S&P 500"), ("petroleo_brent", "Brent")):
        c = _tentar(lambda a=ativo: cotacoes.cotacao(a), avisos, rotulo)
        if not c:
            continue
        if ativo == "USDBRL":
            preco = f"R$ {_br(c.preco)}"
        elif ativo == "IBOV":
            preco = f"{_br(c.preco, 0)} pts"
        elif ativo == "petroleo_brent":
            preco = f"US$ {_br(c.preco)}"
        else:
            preco = _br(c.preco, 0)
        itens.append(f"{rotulo} {preco} {_var(c.variacao_pct)}".strip())
        contexto.append(f"{rotulo} {preco} ({_var(c.variacao_pct)})")
        if c.horario and not referencia and ativo == "IBOV":  # referência = pregão da B3 (câmbio é contínuo, 24 h)
            if (c.horario.hour, c.horario.minute) == (0, 0):  # barra diária (meia-noite na fonte): é o fechamento do dia
                referencia = f"fech. {c.horario:%d/%m}"
            else:
                h = c.horario.astimezone(BRT) if c.horario.tzinfo else c.horario
                referencia = f"{h:%d/%m %H:%M}"
        if c.fonte not in " ".join(fontes):
            fontes.append(f"{c.fonte}{' (pode ter atraso)' if c.atraso else ''}")
    linhas = [" · ".join(itens[:2]), " · ".join(itens[2:])] if itens else []
    return [l for l in linhas if l], referencia


def eventos_agenda(hoje: date, dias: int = 6) -> list[tuple[datetime, str]]:
    """Hoje + próximos dias: Copom/eventos fixos e as divulgações do IBGE que mexem com mercado."""
    fim = datetime.combine(hoje + timedelta(days=dias + 1), datetime.min.time())
    inicio = datetime.combine(hoje, datetime.min.time())
    eventos = [(e.quando, e.titulo) for e in painel.eventos_fixos() if inicio <= e.quando < fim]
    try:
        for d in abertos.calendario_ibge(dias):
            if any(re.search(p, d.titulo) for p in IBGE_IMPORTANTES):
                nome = next((v for k, v in NOMES_IBGE.items() if k in d.titulo), d.titulo)
                ref = re.search(r"\(ref\. (\d{2})/(\d{4})\)", d.titulo)
                if ref:
                    nome += f" ({MESES[int(ref[1]) - 1]})"
                eventos.append((d.quando, nome))
    except ERROS:
        pass
    vistos, saida = set(), []
    for quando, titulo in sorted(eventos):
        if (quando.date(), titulo) not in vistos:
            vistos.add((quando.date(), titulo))
            saida.append((quando, titulo))
    return saida


def _agenda(hoje: date) -> list[str]:
    eventos = eventos_agenda(hoje)
    hoje_ev = [f"{t}{f' {q:%H:%M}' if (q.hour, q.minute) != (0, 0) else ''}" for q, t in eventos if q.date() == hoje]
    proximos = [f"{DIAS_CURTOS[q.weekday()]} {q:%d/%m} {t}" for q, t in eventos if q.date() > hoje][:4]
    linhas = [f"Hoje: {', '.join(hoje_ev) if hoje_ev else 'sem divulgações relevantes'}"]
    if proximos:
        linhas.append("Próximos dias: " + " · ".join(proximos))
    return linhas


def _historias(fontes: list[str]) -> tuple[list[str], list[str]]:
    try:
        from quiron.servicos.noticias import consultas, relevancia

        hist = relevancia.diversificar(consultas.historias(18), 5, max_por_tema=2)
    except Exception as e:  # noqa: BLE001 — notícias nunca derrubam o briefing
        logging.info("briefing sem notícias (%s)", type(e).__name__)
        return [], []
    linhas, contexto = [], []
    veiculos = set()
    for h in hist:
        veiculos.update(h.fontes)
        mais = f" (+{h.cobertura - 1})" if h.cobertura > 1 else ""
        linhas.append(f"• [{h.titulo}]({h.link}) — {h.fonte}{mais}")
        contexto.append(f"- {h.titulo} ({', '.join(h.fontes[:4])})")
    if veiculos:
        fontes.append(f"notícias de {len(veiculos)} veículos")
    return linhas, contexto


# ---------------------------------------------------------------- montagem


def montar(agora: datetime | None = None, noticias: bool = True) -> Briefing:
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    from concurrent.futures import ThreadPoolExecutor

    # cada bloco busca suas fontes ao mesmo tempo (cada um com a própria lista de fontes/avisos, juntadas na ordem fixa)
    partes: dict[str, tuple[list[str], list[str]]] = {k: ([], []) for k in ("noticias", "juros", "inflacao", "mercados")}
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_not = ex.submit(_historias, partes["noticias"][0]) if noticias else None
        f_jur = ex.submit(_juros, *partes["juros"])
        f_inf = ex.submit(_inflacao, *partes["inflacao"], agora.year)
        f_mer = ex.submit(_mercados, *partes["mercados"])
        f_age = ex.submit(_agenda, agora.date())
    noticias_l, noticias_ctx = f_not.result() if f_not else ([], [])
    juros, inflacao, (mercados, ref), agenda = f_jur.result(), f_inf.result(), f_mer.result(), f_age.result()
    fontes = [f for k in ("noticias", "juros", "inflacao", "mercados") for f in partes[k][0]]
    avisos = [a for k in ("noticias", "juros", "inflacao", "mercados") for a in partes[k][1]]
    blocos = [f"☀️ **Briefing — {DIAS[agora.weekday()]}, {agora:%d/%m}** · {agora:%H:%M}"]
    if noticias_l:
        blocos.append("**O que está mexendo com o mercado**\n" + "\n".join(noticias_l))
    if juros:
        base = next((f for f in fontes if f.startswith("Tesouro (base")), "")
        titulo = f"**Juros** (Tesouro: taxas de {base[14:-1]}, variação no dia)" if base else "**Juros**"
        blocos.append(titulo + "\n" + "\n".join(juros))
    if inflacao:
        blocos.append("**Inflação e expectativas**\n" + "\n".join(inflacao))
    if mercados:
        blocos.append(f"**Mercados**{f' ({ref})' if ref else ''}\n" + "\n".join(mercados))
    blocos.append("**Agenda**\n" + "\n".join(agenda))
    if avisos:
        blocos.append("⚠️ " + " · ".join(avisos))
    rodape = f"_Fontes: {' · '.join(dict.fromkeys(fontes))}_" if fontes else ""
    texto = "\n\n".join(blocos + ([rodape] if rodape else []))
    contexto = "\n".join(["Números do briefing:", *juros, *inflacao, *mercados, "Manchetes mais relevantes:", *noticias_ctx])
    return Briefing(texto, contexto, fontes, avisos)


SISTEMA_COMENTARIO = (
    "Você é o Quíron, colega sênior de um assessor de investimentos brasileiro. Clientes dele: aposentados e "
    "conservadores, empresários, profissionais liberais. A partir dos números e manchetes de hoje, escreva de 2 a 3 "
    "bullets do que isso MUDA para esses clientes: o que observar, que conversa puxar, que risco ou oportunidade "
    "explicar (ex.: travar juro real, prazo de renda fixa, exposição a dólar, volatilidade na bolsa). Não repita os "
    "números (eles já estão no briefing); não invente dado; não recomende ativo específico. Até 25 palavras cada, "
    "sem introdução. Uma linha por bullet, começando com '• '.")


def _numeros(texto: str) -> set[str]:
    return {re.sub(r"[^\d,]", "", m) for m in re.findall(r"\d+(?:[.,]\d+)*", texto) if len(re.sub(r"\D", "", m)) >= 2}


def comentario(b: Briefing, config=None) -> list[str]:
    """2–3 bullets da IA; linha com número que não está no briefing é descartada (nada inventado)."""
    from quiron.nucleo import cerebro

    try:
        r = cerebro.perguntar(b.contexto, sistema=SISTEMA_COMENTARIO, config=config, temperatura=0.3, max_tokens=400)
    except Exception as e:  # noqa: BLE001 — sem IA, o briefing sai sem comentário
        logging.info("briefing sem comentário (%s)", type(e).__name__)
        return []
    permitidos = _numeros(b.texto)
    saida = []
    for linha in (r.texto or "").splitlines():
        linha = linha.strip().lstrip("•-* ").strip()
        if len(linha) < 15:
            continue
        if _numeros(linha) - permitidos:
            logging.info("comentário descartado (número fora do briefing): %s", linha)
            continue
        saida.append("• " + linha)
    return saida[:3]


def completo(agora: datetime | None = None, com_comentario: bool = True, config=None) -> str:
    b = montar(agora)
    linhas = comentario(b, config) if com_comentario else []
    if not linhas:
        return b.texto
    partes = b.texto.rsplit("\n\n_Fontes:", 1)
    meio = "**Para os clientes**\n" + "\n".join(linhas)
    return f"{partes[0]}\n\n{meio}" + (f"\n\n_Fontes:{partes[1]}" if len(partes) == 2 else "")
