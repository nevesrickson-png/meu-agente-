"""Resumo de Mercado escrito (complemento do briefing): resumo executivo + 8 seções com leitura prática.

Modelo: o e-mail "Resumo de Mercado" que o Rickson gostou (06/10/2026). Diferença de propósito: os números de mercado
são buscados e calculados aqui, em Python (Yahoo, Banco Central, Tesouro, Focus), e as manchetes vêm das fontes de
notícias do Quíron (com crédito). A IA só redige; frase com número que não está nos fatos nem nas manchetes é tirada.
Sem IA, sai a versão em tópicos com os mesmos fatos.

Saída: texto para o Telegram/Terminal + PDF/planilha (modelo Relatorio) em `dados/resumos/AAAA-MM-DD-HHMM/`.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quiron.nucleo.config import ler_yaml, pasta_dados
from quiron.servicos.mercado import bcb, cotacoes, painel, tesouro
from quiron.servicos.mercado.http import FonteIndisponivel

BRT = ZoneInfo("America/Sao_Paulo")
ERROS = (FonteIndisponivel, ValueError, KeyError, IndexError, OSError, ZeroDivisionError)
RODAPE = ("Uso interno — resumo gerado automaticamente a partir das fontes citadas; confira os números antes de repassar "
          "a clientes. Não constitui recomendação nem relatório de análise (Resolução CVM 20).")

# (chave, título, ativos [(código, nome, tipo)], temas de notícia). tipo: preco · pontos · usd · taxa (yield em %)
SECOES: list[tuple[str, str, list[tuple[str, str, str]], list[str]]] = [
    ("bolsa_br", "Bolsa brasileira (Ibovespa)", [("IBOV", "Ibovespa", "pontos"), ("SMLL", "Small caps (SMAL11)", "preco")],
     ["bolsa", "empresas", "politica"]),
    ("bolsa_eua", "Bolsa americana (S&P 500, Nasdaq, Dow Jones)",
     [("^GSPC", "S&P 500", "pontos"), ("^IXIC", "Nasdaq", "pontos"), ("^DJI", "Dow Jones", "pontos")],
     ["bolsa", "internacional", "empresas"]),
    ("renda_fixa", "Renda fixa", [("^TNX", "Treasury 10 anos", "taxa"), ("^TYX", "Treasury 30 anos", "taxa")],
     ["renda_fixa", "juros", "fiscal"]),
    ("juros", "Juros (política monetária)", [], ["copom", "banco_central", "fed", "juros", "inflacao"]),
    ("moedas", "Moedas", [("USDBRL", "Dólar", "preco"), ("EURBRL", "Euro", "preco"), ("DX-Y.NYB", "Índice DXY", "pontos")],
     ["cambio"]),
    ("cripto", "Cripto", [("BTC-USD", "Bitcoin", "usd"), ("ETH-USD", "Ethereum", "usd")], ["cripto"]),
    ("agro", "Agro e commodities",
     [("SB=F", "Açúcar bruto (ICE, US¢/lb)", "pontos"), ("KC=F", "Café arábica (ICE, US¢/lb)", "pontos"),
      ("ZS=F", "Soja (CBOT, US¢/bushel)", "pontos"), ("ZC=F", "Milho (CBOT, US¢/bushel)", "pontos"),
      ("LE=F", "Boi gordo (CME, EUA, US¢/lb)", "pontos"), ("petroleo_brent", "Petróleo Brent", "usd"),
      ("CL=F", "Petróleo WTI", "usd"), ("ouro", "Ouro", "usd"), ("minerio_ferro", "Minério de ferro", "usd")],
     ["commodities"]),
    ("fiis", "Fundos imobiliários (FIIs)", [("IFIX", "IFIX", "pontos")], ["fundos_previdencia", "renda_fixa"]),
]
# manchete só entra na seção se falar do assunto dela (os temas das notícias são largos)
# todas as alternativas começam em início de palavra ("ny" não casa "Germany", "di" não casa "Saudi", "dow" não "window")
_FILTROS = {
    "bolsa_br": r"ibovespa|bolsa|b3|a[cç][oõ]es|[A-Z]{4}[0-9]{1,2}\b|small caps",
    "bolsa_eua": r"s&p|nasdaq|dow\b|dow jones|wall street|nova york|ny\b|stocks\b|eua\b|americana",
    "renda_fixa": r"tesouro|renda fixa|treasur|t[ií]tulos? p[uú]blic|cdb\b|lci\b|lca\b|deb[eê]nture|cr[ia]s?\b|yield|juros futuros|di\b",
    "juros": r"selic|copom|banco central|bc\b|fed\b|fomc|juros|infla[cç][aã]o|ipca|powell|gal[ií]polo",
    "moedas": r"d[oó]lar|c[aâ]mbio|(?<!juro )(?<!juros )real\b|euro\b|moedas?\b|dxy|currenc|dollar",
    "cripto": r"bitcoin|btc\b|ether|cripto|crypto|stablecoin|blockchain",
    "agro": r"soja|milho|caf[eé]\b|a[cç][uú]car|boi\b|arroba|safra|agro|petr[oó]leo|brent|wti\b|ouro\b|min[eé]rio|commodit|oil\b|gold\b",
    "fiis": r"fii|fiis\b|ifix|fundos? imobili|[A-Z]{4}11\b",
}
FILTRO_SECAO = {k: rf"\b(?:{v})" for k, v in _FILTROS.items()}


@dataclass
class Linha:
    """Um ativo com as variações calculadas."""
    nome: str
    tipo: str
    ultimo: float
    data: datetime
    dia: float | None          # % (ou bps, se tipo == "taxa")
    semana: float | None
    mes: float | None
    ano: float | None
    maxima: float
    minima: float

    def valor(self) -> str:
        if self.tipo == "taxa":
            return painel._pct(self.ultimo)
        if self.tipo == "usd":
            return f"US$ {painel._num(self.ultimo)}"
        if self.tipo == "preco":
            return f"R$ {painel._num(self.ultimo, 4 if self.ultimo < 10 else 2)}"
        return painel._num(self.ultimo, 0 if self.ultimo > 10000 else 2)

    def variacao(self, v: float | None) -> str:
        if v is None:
            return "—"
        return f"{v:+.0f} bps" if self.tipo == "taxa" else painel._pct(v, sinal=True)

    def fato(self) -> str:
        perto = ""
        if self.tipo != "taxa" and self.maxima and self.ultimo >= self.maxima * 0.995:
            perto = " · na máxima de 52 semanas"
        elif self.tipo != "taxa" and self.maxima:
            perto = f" · {painel._pct((self.ultimo / self.maxima - 1) * 100, 1, sinal=True)} da máxima de 52 semanas"
        dia = self.variacao(self.dia) if self.dia is not None else "indisponível na fonte"
        return (f"{self.nome}: {self.valor()} em {self.data:%d/%m} (dia {dia}; semana "
                f"{self.variacao(self.semana)}; mês {self.variacao(self.mes)}; no ano {self.variacao(self.ano)}){perto}")


@dataclass
class Bloco:
    chave: str
    titulo: str
    linhas: list[Linha] = field(default_factory=list)
    fatos: list[str] = field(default_factory=list)      # além das linhas (Tesouro, Focus, agenda…)
    manchetes: list[str] = field(default_factory=list)  # "título (veículos)"
    texto: str = ""                                     # redação final


@dataclass
class Resumo:
    data: datetime
    executivo: str
    blocos: list[Bloco]
    fontes: list[str]
    redigido_por_ia: bool
    pasta: Path | None = None

    def texto(self) -> str:
        partes = [f"📰 **Resumo de Mercado — {self.data:%d/%m/%Y}**"]
        if self.executivo:
            partes.append(f"**Resumo executivo:** {self.executivo}")
        for i, b in enumerate(self.blocos, 1):
            if b.texto:
                partes.append(f"**{i}. {b.titulo}**\n{b.texto}")
        partes.append(f"_Fontes: {' · '.join(self.fontes)}._")
        partes.append("_Resumo automático: confira os números antes de repassar a clientes._")
        return "\n\n".join(partes)


# ---------------------------------------------------------------- coleta dos fatos
BRASIL = {"IBOV", "SMLL", "IFIX", "USDBRL", "EURBRL"}


def _dia_confiavel(codigo: str, serie: list, ref: list | None) -> bool:
    """O Yahoo às vezes pula um pregão (SMAL11 sem 05/10) ou repete o fechamento (dólar de 05/10 = 02/10): aí a
    "variação do dia" mistura dois dias. Ativos do Brasil são conferidos contra os pregões do Ibovespa."""
    if len(serie) < 3:
        return False
    d1, d0 = serie[-2][0].date(), serie[-1][0].date()
    if ref and (codigo in BRASIL or codigo.endswith("11") or codigo[-1:].isdigit()):
        datas_ref = [d.date() for d, _ in ref]
        if d0 in datas_ref and datas_ref.index(d0) > 0 and datas_ref[datas_ref.index(d0) - 1] != d1:
            return False
    if codigo in {"USDBRL", "EURBRL"}:  # barras diárias de câmbio do Yahoo vêm defasadas: o dia sai da PTAX (BC)
        return False
    return True


def _linha(codigo: str, nome: str, tipo: str, ref: list | None = None) -> Linha | None:
    try:
        serie = cotacoes.historico(codigo, "1y")
        d = cotacoes.desempenho(codigo, serie)
    except ERROS:
        try:  # histórico curto na fonte (ex.: IFIX no Yahoo): fica só a cotação do dia
            c = cotacoes.cotacao(codigo)
        except ERROS:
            return None
        dia = None if tipo == "taxa" or codigo in {"USDBRL", "EURBRL"} else c.variacao_pct  # % não é bps; câmbio: PTAX
        return Linha(nome, tipo, c.preco, c.horario or datetime.now(BRT), dia, None, None, None, 0.0, 0.0)
    confiavel = _dia_confiavel(codigo, serie, ref)
    if tipo == "taxa":  # yield: variação em pontos-base, não em %
        ult = serie[-1][1]

        def bps(dias: int) -> float | None:
            base = [v for dt, v in serie if (serie[-1][0] - dt).days >= dias]
            return (ult - base[-1]) * 100 if base else None

        inicio_ano = [v for dt, v in serie if dt.year < serie[-1][0].year]
        return Linha(nome, tipo, ult, d["data"], (ult - d["anterior"]) * 100 if confiavel else None, bps(7), bps(30),
                     (ult - inicio_ano[-1]) * 100 if inicio_ano else None, d["maxima_52s"], d["minima_52s"])
    return Linha(nome, tipo, d["ultimo"], d["data"], d["dia"] if confiavel else None, d["semana"], d["mes"], d["ano"],
                 d["maxima_52s"], d["minima_52s"])


def _fatos_juros(ano: int) -> list[str]:
    fatos = []
    for chave, rotulo in (("selic_meta", "Selic meta"), ("cdi", "CDI")):
        try:
            s = bcb.sgs(chave, 2)
            fatos.append(f"{rotulo}: {painel._pct(s.ultimo.valor)} a.a. (Banco Central, {s.ultimo.data:%d/%m/%Y})")
        except ERROS:
            pass
    for ind, a, rot in (("selic", ano, f"Selic fim de {ano}"), ("selic", ano + 1, f"Selic fim de {ano + 1}"),
                        ("ipca", ano, f"IPCA {ano}"), ("ipca", ano + 1, f"IPCA {ano + 1}"), ("pib", ano, f"PIB {ano}")):
        try:
            e = bcb.focus(ind, a)
        except ERROS:
            continue
        semana = ""
        if e.mediana_semana_anterior is not None and abs(e.mediana - e.mediana_semana_anterior) >= 0.005:
            semana = f", era {painel._pct(e.mediana_semana_anterior)} na semana anterior"
        fatos.append(f"Focus ({e.data:%d/%m}) — {rot}: {painel._pct(e.mediana)}{semana}")
    try:
        s = bcb.sgs("ipca_12m", 2)
        fatos.append(f"IPCA acumulado em 12 meses: {painel._pct(s.ultimo.valor)} (até {s.ultimo.data:%m/%Y})")
    except ERROS:
        pass
    try:
        from quiron.servicos.mercado import briefing

        hoje = datetime.now(BRT).date()
        for quando, titulo in briefing.eventos_agenda(hoje, 25):
            if re.search(r"\b(?:copom|fomc|fed\b|ata\b|federal reserve)", titulo, re.I):
                fatos.append(f"Agenda: {titulo} em {quando:%d/%m}")
    except ERROS:
        pass
    return fatos


def _fatos_ptax() -> list[str]:
    fatos = []
    for chave, rotulo in (("dolar_ptax", "Dólar PTAX"), ("euro_ptax", "Euro PTAX")):
        try:
            s = bcb.sgs(chave, 3)
        except ERROS:
            continue
        pts = s.pontos if hasattr(s, "pontos") else []
        var = ""
        if len(pts) >= 2 and pts[-2].valor:
            var = f" ({painel._pct((pts[-1].valor / pts[-2].valor - 1) * 100, sinal=True)} sobre {pts[-2].data:%d/%m})"
        fatos.append(f"{rotulo} (Banco Central): R$ {painel._num(s.ultimo.valor, 4)} em {s.ultimo.data:%d/%m}{var}")
    return fatos


def _fatos_tesouro() -> list[str]:
    try:
        tab = tesouro.titulos_atuais()
    except ERROS:
        return []
    from quiron.servicos.mercado.briefing import _taxas_anteriores

    anterior = _taxas_anteriores(tab.data_base, [])
    fatos = []
    for chave, rotulo in (("prefixado", "Tesouro Prefixado"), ("ipca_mais", "Tesouro IPCA+")):
        for t in sorted(tesouro.por_tipo(tab, chave), key=lambda x: x.vencimento):
            taxa = t.taxa_compra or t.taxa_venda
            if taxa is None:
                continue
            antes = anterior.get((t.tipo, t.vencimento))
            delta = f", {(taxa - antes) * 100:+.0f} bps no dia" if antes is not None else ""
            fatos.append(f"{rotulo} {t.vencimento.year}: {painel._pct(taxa)} a.a. (Tesouro, taxas de {tab.data_base:%d/%m}{delta})")
    return fatos


def _fatos_fiis(ref: list | None) -> tuple[list[Linha], list[str]]:
    """Os FIIs da watchlist que mais andaram no dia (destaques)."""
    fiis = [str(x) for x in (ler_yaml("watchlist") or {}).get("fiis", [])][:15]
    linhas = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for ln in ex.map(lambda f: _linha(f, f, "preco", ref), fiis):
            if ln and ln.dia is not None:
                linhas.append(ln)
    linhas.sort(key=lambda x: abs(x.dia or 0), reverse=True)
    return linhas[:5], [f"FII da watchlist {ln.nome}: {ln.valor()} ({ln.variacao(ln.dia)} no dia; mês {ln.variacao(ln.mes)})"
                        for ln in linhas[:5]]


def _manchetes(horas: int = 24) -> dict[str, list[str]]:
    """Histórias mais relevantes por tema (título + veículos)."""
    try:
        from quiron.servicos.noticias import consultas

        hist = sorted(consultas.historias(horas), key=lambda h: h.nota, reverse=True)
    except Exception as e:  # noqa: BLE001 — sem notícias, o resumo sai só com os números
        logging.info("resumo sem notícias (%s)", type(e).__name__)
        return {}
    por_tema: dict[str, list[str]] = {}
    for h in hist:
        for t in h.temas:
            itens = por_tema.setdefault(t, [])
            if len(itens) < 6:
                itens.append(f"{h.titulo} ({', '.join(h.fontes[:3])}{' +' + str(h.cobertura - 3) if h.cobertura > 3 else ''})")
    return por_tema


def coletar(agora: datetime | None = None) -> tuple[list[Bloco], list[str]]:
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    blocos = [Bloco(ch, tit) for ch, tit, _, _ in SECOES]
    try:
        ref = cotacoes.historico("IBOV", "1mo")  # pregões da B3, para conferir a "variação do dia" dos ativos daqui
    except ERROS:
        ref = None
    with ThreadPoolExecutor(max_workers=8) as ex:
        f_linhas = {ch: [ex.submit(_linha, *a, ref) for a in ativos] for ch, _, ativos, _ in SECOES}
        f_juros = ex.submit(_fatos_juros, agora.year)
        f_tes = ex.submit(_fatos_tesouro)
        f_ptax = ex.submit(_fatos_ptax)
        f_fii = ex.submit(_fatos_fiis, ref)
        f_not = ex.submit(_manchetes)
    manchetes = f_not.result()
    fontes = []
    for b, (_, _, _, temas) in zip(blocos, SECOES):
        b.linhas = [ln for f in f_linhas[b.chave] if (ln := f.result())]
        vistos = set()
        filtro = re.compile(FILTRO_SECAO.get(b.chave, "."), re.I)
        for t in temas:
            for m in manchetes.get(t, []):
                if m not in vistos and len(b.manchetes) < 6 and filtro.search(m.rsplit(" (", 1)[0]):
                    vistos.add(m)
                    b.manchetes.append(m)
    por = {b.chave: b for b in blocos}
    por["juros"].fatos = f_juros.result()
    por["renda_fixa"].fatos = f_tes.result()
    por["moedas"].fatos = f_ptax.result()
    destaques, fatos_fii = f_fii.result()
    por["fiis"].fatos = fatos_fii
    if any(b.linhas for b in blocos) or destaques:
        fontes.append("Yahoo Finance (fechamentos)")
    if por["juros"].fatos:
        fontes.append("Banco Central (SGS e Focus)")
    if por["renda_fixa"].fatos:
        fontes.append("Tesouro Transparente")
    veiculos = sorted({re.sub(r"\s*\+\d+$", "", v).strip() for b in blocos for m in b.manchetes
                       for v in m.rsplit("(", 1)[-1].rstrip(")").split(",") if re.sub(r"\s*\+\d+$", "", v).strip()})
    if veiculos:
        fontes.append("notícias: " + ", ".join(veiculos[:14]) + (f" e mais {len(veiculos) - 14}" if len(veiculos) > 14 else ""))
    return blocos, fontes


# ---------------------------------------------------------------- redação
SISTEMA = (
    "Você é o Quíron, colega sênior de um assessor de investimentos brasileiro (clientes: aposentados e conservadores, "
    "empresários, profissionais liberais). Escreva um RESUMO DE MERCADO em português do Brasil, em prosa corrida e "
    "jornalística, usando SOMENTE os fatos e manchetes fornecidos. Regras: (1) todo número precisa estar nos fatos ou "
    "nas manchetes — nunca calcule, estime ou arredonde diferente; (2) cite datas como aparecem; (3) explique o porquê "
    "dos movimentos só quando uma manchete disser; (4) cada seção termina com 'Leitura prática:' (1–2 frases do que "
    "isso muda na conversa com clientes, sem recomendar ativo específico); (5) seção sem fatos nem manchetes: escreva "
    "'Sem destaque relevante hoje.'; (6) não despeje todos os números: por ativo, use os 2–3 que contam a história do "
    "dia (fechamento e a variação mais relevante), como um bom jornal; quando a variação do dia estiver 'indisponível "
    "na fonte', não a cite. Formato exato:\n"
    "RESUMO EXECUTIVO: <4 a 6 frases>\n"
    "### <chave da seção>\n<1 parágrafo de 4 a 7 frases>\n(repita para cada seção, na ordem dada)")


def _numeros(texto: str) -> set[str]:
    saida = set()
    for m in re.findall(r"\d+(?:[.,]\d+)*", texto):
        digitos = re.sub(r"\D", "", m)
        if len(digitos) >= 2 or "," in m or "." in m:
            saida.add(digitos.lstrip("0") or "0")
    return saida


def _contexto(blocos: list[Bloco]) -> str:
    partes = []
    for b in blocos:
        linhas = [f"### {b.chave} — {b.titulo}", "Fatos:"]
        linhas += [f"- {ln.fato()}" for ln in b.linhas] + [f"- {f}" for f in b.fatos]
        if b.manchetes:
            linhas.append("Manchetes:")
            linhas += [f"- {m}" for m in b.manchetes]
        partes.append("\n".join(linhas))
    return "\n\n".join(partes)


def _limpar(paragrafo: str, permitidos: set[str]) -> str:
    """Tira as frases com número que não está nos fatos/manchetes (nada inventado chega ao Rickson)."""
    frases = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\"“(])", paragrafo.strip())
    boas = []
    for f in frases:
        fora = _numeros(f) - permitidos
        if fora:
            logging.info("resumo: frase descartada (número fora das fontes %s): %s", fora, f[:120])
            continue
        boas.append(f)
    return " ".join(boas).strip()


def redigir(blocos: list[Bloco], config=None) -> tuple[str, bool]:
    """Preenche `texto` de cada bloco e devolve (resumo executivo, se a IA redigiu)."""
    from quiron.nucleo import cerebro

    contexto = _contexto(blocos)
    permitidos = _numeros(contexto) | {str(datetime.now(BRT).year), "2", "3"}
    try:
        # max_tokens alto: no Gemini 3 o "pensamento" conta no limite e cortava o texto no meio
        r = cerebro.perguntar(contexto, sistema=SISTEMA, config=config, temperatura=0.3, max_tokens=8000)
        bruto = r.texto or ""
    except Exception as e:  # noqa: BLE001 — sem IA, sai a versão em tópicos
        logging.info("resumo sem IA (%s)", type(e).__name__)
        bruto = ""
    pedacos = re.split(r"^###\s*", bruto, flags=re.M)
    executivo = ""
    m = re.search(r"RESUMO EXECUTIVO:\s*(.+)", pedacos[0] if pedacos else "", re.S)
    if m:
        executivo = _limpar(" ".join(m.group(1).split()), permitidos)
    por_chave = {}
    for p in pedacos[1:]:
        cab, _, corpo = p.partition("\n")
        chave = cab.split("—")[0].strip().strip("*: ").lower()
        texto = _limpar(" ".join(corpo.split()), permitidos)
        por_chave[chave] = re.sub(r"\s*Leitura prática:\s*", "\n**Leitura prática:** ", texto, count=1)
    redigiu = bool(executivo or any(por_chave.values()))
    for b in blocos:
        b.texto = por_chave.get(b.chave, "")
        if not b.texto:  # plano B: os fatos em tópicos
            itens = [f"• {ln.fato()}" for ln in b.linhas] + [f"• {f}" for f in b.fatos[:8]]
            itens += [f"• {m}" for m in b.manchetes[:3]]
            b.texto = "\n".join(itens) or "Sem destaque relevante hoje."
    return executivo, redigiu


# ---------------------------------------------------------------- saída
def pasta_resumos() -> Path:
    return pasta_dados() / "resumos"


def gerar(agora: datetime | None = None, config=None, salvar: bool = True) -> Resumo:
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    blocos, fontes = coletar(agora)
    executivo, redigiu = redigir(blocos, config)
    r = Resumo(agora, executivo, blocos, fontes, redigiu)
    if salvar:
        r.pasta = _salvar(r)
    return r


def _relatorio(r: Resumo):
    from quiron.servicos.analise.relatorio import Relatorio, Secao, Tabela

    rel = Relatorio(titulo=f"Resumo de Mercado — {r.data:%d/%m/%Y}", tipo="resumo_mercado",
                    subtitulo=f"Gerado às {r.data:%H:%M} · números das fontes oficiais e de mercado; texto "
                              f"{'redigido pela IA e conferido' if r.redigido_por_ia else 'em tópicos (IA indisponível)'}",
                    resumo=[r.executivo] if r.executivo else [], fontes=r.fontes, rodape=RODAPE,
                    limitacoes=["Cotações do Yahoo podem ter atraso; fechamento = último pregão disponível.",
                                "Os porquês dos movimentos vêm das manchetes citadas, não de análise própria.",
                                "Commodities agrícolas em bolsas americanas (o boi gordo da B3 não tem fonte gratuita)."])
    for i, b in enumerate(r.blocos, 1):
        tabelas = []
        if b.linhas:
            tabelas.append(Tabela("Números", ["Ativo", "Último", "Dia", "Semana", "Mês", "No ano"],
                                  [[ln.nome, ln.valor(), ln.variacao(ln.dia), ln.variacao(ln.semana), ln.variacao(ln.mes),
                                    ln.variacao(ln.ano)] for ln in b.linhas]))
        rel.secoes.append(Secao(f"{i}. {b.titulo}", b.texto, tabelas))
    return rel


def _salvar(r: Resumo) -> Path:
    pasta = pasta_resumos() / f"{r.data:%Y-%m-%d-%H%M}"
    _relatorio(r).salvar(pasta)
    import shutil

    shutil.copyfile(pasta / "relatorio.pdf", pasta / f"resumo-de-mercado-{r.data:%Y-%m-%d}.pdf")  # nome bom no Telegram
    (pasta / "resumo.txt").write_text(r.texto(), encoding="utf-8")
    (pasta / "meta.json").write_text(json.dumps({"data": r.data.isoformat(), "ia": r.redigido_por_ia}), encoding="utf-8")
    return pasta


def ultimo() -> dict | None:
    """O resumo mais recente salvo (para o Terminal e para não refazer à toa)."""
    base = pasta_resumos()
    pastas = sorted((p for p in base.glob("*") if (p / "resumo.txt").exists()), reverse=True) if base.exists() else []
    if not pastas:
        return None
    p = pastas[0]
    meta = json.loads((p / "meta.json").read_text(encoding="utf-8")) if (p / "meta.json").exists() else {}
    return {"pasta": str(p), "id": p.name, "data": meta.get("data"), "ia": meta.get("ia"),
            "texto": (p / "resumo.txt").read_text(encoding="utf-8"), "pdf": (p / "relatorio.pdf").exists()}


def pdf_de(r: Resumo) -> Path | None:
    if not r.pasta:
        return None
    bonito = r.pasta / f"resumo-de-mercado-{r.data:%Y-%m-%d}.pdf"
    return bonito if bonito.exists() else (r.pasta / "relatorio.pdf" if (r.pasta / "relatorio.pdf").exists() else None)


_GERANDO = __import__("threading").Event()
_INICIO = __import__("threading").Lock()


def gerar_em_segundo_plano(config=None) -> bool:
    """Para o Terminal: gera sem esperar (um de cada vez). True se começou agora."""
    import threading

    with _INICIO:  # dois cliques ao mesmo tempo não geram dois resumos
        if _GERANDO.is_set():
            return False
        _GERANDO.set()

    def rodar():
        try:
            gerar(config=config)
        except Exception:  # noqa: BLE001
            logging.exception("falha ao gerar o resumo de mercado")
        finally:
            _GERANDO.clear()

    threading.Thread(target=rodar, daemon=True, name="resumo").start()
    return True


def gerando() -> bool:
    return _GERANDO.is_set()
