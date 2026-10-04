"""Painel de mercado: junta as fontes e formata em Markdown (usado pelo MCP e, depois, pelo Terminal).

Regra: todo número sai com `📊 Fonte — horário`. Falha de uma fonte não derruba o resto — aparece como
"indisponível" com o motivo. Nada é estimado ou inventado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import yaml

from quiron.nucleo.config import PASTA_CONFIG, ler_yaml
from quiron.servicos.mercado import abertos, bcb, cotacoes, curva, tesouro
from quiron.servicos.mercado.http import FonteIndisponivel


def _fonte(nome: str, quando: datetime, desatualizado: bool = False, extra: str = "") -> str:
    aviso = " ⚠️ DESATUALIZADO (fonte fora do ar; último valor guardado)" if desatualizado else ""
    # horário sempre em Brasília, mesmo num servidor com relógio em UTC (sem fuso = relógio do sistema)
    local = quando.astimezone(ZoneInfo("America/Sao_Paulo"))
    return f"📊 {nome} — {local:%d/%m %H:%M}{(' · ' + extra) if extra else ''}{aviso}"


def _pct(v: float | None, casas: int = 2, sinal: bool = False) -> str:
    if v is None:
        return "—"
    return (f"{v:+.{casas}f}" if sinal else f"{v:.{casas}f}").replace(".", ",") + "%"


def _num(v: float | None, casas: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _seguro(func: Callable[[], str], rotulo: str) -> str:
    try:
        return func()
    except (FonteIndisponivel, ValueError, KeyError) as e:
        return f"- {rotulo}: indisponível ({str(e)[:120]})"


# ---------------------------------------------------------------- cotação


def texto_cotacao(c: cotacoes.Cotacao) -> str:
    preco = f"R$ {_num(c.preco)}" if c.moeda == "BRL" and c.ativo not in {"IBOV", "IFIX", "SMLL"} else _num(c.preco)
    if c.ativo in {"petroleo_brent", "ouro", "minerio_ferro"}:
        preco = f"US$ {_num(c.preco)}"
    if c.ativo in {"IBOV", "IFIX"}:
        preco = _num(c.preco, 0) + " pts"
    quando = f"dado de {c.horario:%d/%m %H:%M}" if c.horario else ""
    return f"- **{c.nome}** ({c.ativo}): {preco} ({_pct(c.variacao_pct, sinal=True)} no dia) — {_fonte(c.fonte, c.obtido_em, extra=' · '.join(x for x in (quando, c.atraso) if x))}"


def cotacao(ativo: str) -> str:
    return _seguro(lambda: texto_cotacao(cotacoes.cotacao(ativo)), ativo)


def watchlist() -> str:
    w = ler_yaml("watchlist") or {}
    ativos = [*w.get("indices", []), *w.get("moedas", []), *w.get("acoes", []), *w.get("fiis", []), *w.get("etfs", []), *w.get("commodities", [])]
    return "\n".join(cotacao(str(a)) for a in ativos)


# ---------------------------------------------------------------- juros


def _linha_serie(chave: str, casas: int = 2) -> str:
    s = bcb.sgs(chave, 2)
    valor = f"R$ {_num(s.ultimo.valor, 4)}" if s.unidade == "R$" else (_pct(s.ultimo.valor, casas) if "%" in s.unidade else _num(s.ultimo.valor))
    return f"- **{s.nome}**: {valor} (ref. {s.ultimo.data:%d/%m/%Y}) — {_fonte(s.fonte, s.obtido_em, s.desatualizado)}"


def texto_tesouro(tipos: tuple[str, ...] = ("selic", "prefixado", "ipca_mais")) -> str:
    tab = tesouro.titulos_atuais()
    linhas = [f"**Tesouro Direto** (taxas de compra, data-base {tab.data_base:%d/%m/%Y}) — {_fonte(tab.fonte, tab.obtido_em, tab.desatualizado)}"]
    for chave in tipos:
        for t in tesouro.por_tipo(tab, chave):
            prefixo = {"ipca_mais": "IPCA + ", "selic": "Selic + "}.get(chave, "")
            linhas.append(f"- {t.nome}: {prefixo}{_pct(t.taxa_compra if t.taxa_compra else t.taxa_venda, 4 if chave == 'selic' else 2)}")
    return "\n".join(linhas)


def taxas() -> str:
    partes = ["## Juros e Tesouro"]
    partes += [_seguro(lambda c=c: _linha_serie(c), c) for c in ("selic_meta", "cdi")]
    partes.append(_seguro(texto_tesouro, "Tesouro Direto"))
    return "\n".join(partes)


def texto_curva(prazos: tuple[float, ...] = (0.5, 1, 2, 3, 5, 10)) -> str:
    c = curva.curva()
    linhas = [
        f"## Curva de juros ({c.data:%d/%m/%Y}) — {_fonte(c.fonte, c.obtido_em, c.desatualizado)}",
        *([f"_{c.observacao}_"] if c.observacao else []),
        "| Prazo | Pré | Real (IPCA+) | Inflação implícita |",
        "|---|---:|---:|---:|",
    ]
    vistos = set()
    for anos in prazos:
        v = curva.no_prazo(c, anos)
        if v and v.dias_uteis not in vistos:
            vistos.add(v.dias_uteis)
            linhas.append(f"| {v.anos:.1f} anos ({v.dias_uteis} du) | {_pct(v.pre)} | {_pct(v.real)} | {_pct(v.implicita)} |")
    return "\n".join(linhas)


# ---------------------------------------------------------------- macro


def texto_focus(ano: int | None = None) -> str:
    ano = ano or date.today().year
    linhas = [f"**Focus — medianas para {ano}**"]
    fonte = ""
    for ind in ("ipca", "pib", "selic", "cambio"):
        try:
            e = bcb.focus(ind, ano)
        except (FonteIndisponivel, ValueError) as err:
            linhas.append(f"- {bcb.INDICADORES_FOCUS[ind]}: indisponível ({str(err)[:80]})")
            continue
        mud = ""
        if e.mediana_semana_anterior is not None:
            d = e.mediana - e.mediana_semana_anterior
            mud = " (estável na semana)" if abs(d) < 1e-9 else f" ({'+' if d > 0 else ''}{_num(d)} na semana)"
        valor = f"R$ {_num(e.mediana)}" if ind == "cambio" else _pct(e.mediana)
        linhas.append(f"- {e.indicador}: {valor}{mud}")
        fonte = _fonte(f"{e.fonte}, coleta até {e.data:%d/%m/%Y}", e.obtido_em)
    return "\n".join(linhas + ([fonte] if fonte else []))


def macro() -> str:
    partes = ["## Macro"]
    partes += [_seguro(lambda c=c: _linha_serie(c), c) for c in ("ipca_12m", "ipca_mes", "igpm_mes", "dolar_ptax", "euro_ptax", "ibc_br", "desemprego")]
    partes.append(_seguro(texto_focus, "Focus"))
    return "\n".join(partes)


# ---------------------------------------------------------------- agenda


@dataclass
class Evento:
    quando: datetime
    titulo: str
    fonte: str


DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def eventos_fixos() -> list[Evento]:
    dados = yaml.safe_load((PASTA_CONFIG / "agenda_fixa.yaml").read_text(encoding="utf-8")) or {}
    saida = []
    for e in dados.get("eventos") or []:
        d = e["data"] if isinstance(e["data"], date) else date.fromisoformat(str(e["data"]))
        h, m = (int(x) for x in str(e.get("hora") or "00:00").split(":"))
        rotulo = "agenda_fixa.yaml" + ("" if dados.get("verificado_em") else ", datas a confirmar")
        saida.append(Evento(datetime(d.year, d.month, d.day, h, m), e["titulo"], rotulo))
    return saida


def agenda(dias: int = 7) -> str:
    inicio = datetime.combine(date.today(), datetime.min.time())
    fim = inicio + timedelta(days=dias + 1)
    eventos = [e for e in eventos_fixos() if inicio <= e.quando < fim]
    erro = ""
    try:
        eventos += [Evento(d.quando, d.titulo, d.fonte) for d in abertos.calendario_ibge(dias)]
    except (FonteIndisponivel, ValueError) as e:
        erro = f"\n_IBGE indisponível: {str(e)[:100]}_"
    if not eventos:
        return f"## Agenda ({dias} dias)\nNenhum evento encontrado.{erro}"
    linhas = [f"## Agenda ({dias} dias)"]
    for e in sorted(eventos, key=lambda x: x.quando):
        hora = "" if e.quando.hour == 0 and e.quando.minute == 0 else f" {e.quando:%H:%M}"
        linhas.append(f"- {DIAS[e.quando.weekday()]} {e.quando:%d/%m}{hora} — {e.titulo} ({e.fonte})")
    return "\n".join(linhas) + erro


# ---------------------------------------------------------------- briefing


def briefing() -> str:
    """Dados do briefing (a skill `briefing.md` transforma em texto curto e opinativo)."""
    agora = datetime.now()
    partes = [
        f"# Dados para o briefing — {agora:%d/%m/%Y %H:%M}",
        "## Juros",
        _seguro(lambda: _linha_serie("selic_meta"), "Selic"),
        _seguro(lambda: _linha_serie("cdi"), "CDI"),
        _seguro(lambda: texto_tesouro(("prefixado", "ipca_mais")), "Tesouro"),
        "## Inflação e expectativas",
        _seguro(lambda: _linha_serie("ipca_12m"), "IPCA 12m"),
        _seguro(texto_focus, "Focus"),
        "## Câmbio e bolsa",
        *[cotacao(a) for a in ("USDBRL", "IBOV", "^GSPC", "petroleo_brent")],
        agenda(1),
    ]
    return "\n".join(partes)
