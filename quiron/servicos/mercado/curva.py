"""Curva de juros: ETTJ da ANBIMA (página pública de estrutura a termo), com plano B pelas taxas do Tesouro.

A ANBIMA publica a curva pré, a curva real (IPCA) e a inflação implícita por vértice (dias úteis).
Se a ANBIMA não responder, a curva é montada com as taxas de venda do Tesouro Prefixado e IPCA+
(menos precisa, mas de fonte oficial) e a resposta diz qual fonte foi usada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from quiron.servicos.mercado import tesouro
from quiron.servicos.mercado.http import FonteIndisponivel, numero_br, obter

URL_ETTJ = "https://www.anbima.com.br/informacoes/est-termo/CZ-down.asp"


@dataclass
class Vertice:
    dias_uteis: int
    pre: float | None  # % a.a.
    real: float | None  # % a.a. (IPCA+)
    implicita: float | None  # inflação implícita % a.a.

    @property
    def anos(self) -> float:
        return self.dias_uteis / 252


@dataclass
class Curva:
    data: date
    vertices: list[Vertice]
    fonte: str
    obtido_em: datetime
    desatualizado: bool
    observacao: str = ""


def _dia_util_anterior(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def ler_csv_ettj(texto: str) -> list[Vertice]:
    """Lê a tabela 'Vertices;ETTJ IPCA;ETTJ PREF;Inflação Implícita' do arquivo da ANBIMA."""
    vertices = []
    dentro = False
    for linha in texto.splitlines():
        campos = [c.strip() for c in linha.split(";")]
        if campos and campos[0].lower().startswith("vertices"):
            dentro = True
            continue
        if dentro:
            if not campos or not re.fullmatch(r"[\d.]+", campos[0] or "x"):
                if vertices:
                    break
                continue
            dias = int(campos[0].replace(".", ""))
            real, pre, impl = (numero_br(c) if c else None for c in (campos + ["", "", ""])[1:4])
            vertices.append(Vertice(dias, pre, real, impl))
    return vertices


def ettj_anbima(data: date | None = None) -> Curva:
    """Tenta a data pedida (ou o último dia útil) e volta até 5 dias úteis se ainda não houver curva publicada."""
    d = data or _dia_util_anterior(date.today() + timedelta(days=1))
    for _ in range(5):
        r = obter(
            URL_ETTJ,
            metodo="POST",
            dados={"Idioma": "PT", "Dt_Ref": d.strftime("%d/%m/%Y"), "saida": "csv"},
            fonte="ANBIMA (ETTJ)",
            ttl=12 * 3600,
            formato="texto",
            codificacao="latin-1",
        )
        vertices = ler_csv_ettj(r.conteudo)
        if vertices:
            return Curva(d, vertices, r.fonte, r.obtido_em, r.desatualizado)
        d = _dia_util_anterior(d)
    raise FonteIndisponivel("ANBIMA sem curva publicada nos últimos 5 dias úteis")


def curva_tesouro() -> Curva:
    """Plano B: taxas de venda do Tesouro Prefixado (pré) e IPCA+ (real), por prazo."""
    tab = tesouro.titulos_atuais()
    pre = {t.vencimento: t.taxa_venda for t in tesouro.por_tipo(tab, "prefixado")}
    real = {t.vencimento: t.taxa_venda for t in tesouro.por_tipo(tab, "ipca_mais")}
    vertices = []
    for venc in sorted(set(pre) | set(real)):
        du = round((venc - tab.data_base).days * 252 / 365)
        p, rr = pre.get(venc), real.get(venc)
        impl = ((1 + p / 100) / (1 + rr / 100) - 1) * 100 if p and rr else None
        vertices.append(Vertice(du, p, rr, impl))
    return Curva(
        tab.data_base, vertices, tab.fonte, tab.obtido_em, tab.desatualizado,
        "Curva aproximada pelas taxas do Tesouro Direto (ANBIMA indisponível); dias úteis estimados.",
    )


def curva(data: date | None = None) -> Curva:
    try:
        return ettj_anbima(data)
    except (FonteIndisponivel, ValueError):
        return curva_tesouro()


def no_prazo(c: Curva, anos: float) -> Vertice | None:
    """Vértice mais próximo do prazo pedido."""
    if not c.vertices:
        return None
    return min(c.vertices, key=lambda v: abs(v.anos - anos))
