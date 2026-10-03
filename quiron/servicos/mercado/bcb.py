"""Banco Central: séries do SGS e expectativas do Focus (Olinda). Sem chave."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from quiron.servicos.mercado.http import numero_br, obter

URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}"
URL_FOCUS = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"

# Séries usadas no Quíron (código SGS → descrição, unidade)
SERIES = {
    "selic_meta": (432, "Selic meta", "% a.a."),
    "selic_efetiva": (1178, "Selic efetiva (anualizada, base 252)", "% a.a."),
    "cdi": (4389, "CDI (anualizado, base 252)", "% a.a."),
    "ipca_mes": (433, "IPCA no mês", "%"),
    "ipca_12m": (13522, "IPCA acumulado em 12 meses", "%"),
    "igpm_mes": (189, "IGP-M no mês", "%"),
    "dolar_ptax": (1, "Dólar PTAX (venda)", "R$"),
    "euro_ptax": (21619, "Euro PTAX (venda)", "R$"),
    "ibc_br": (24364, "IBC-Br (dessazonalizado)", "índice"),
    "desemprego": (24369, "Taxa de desocupação (PNAD)", "%"),
}


@dataclass
class Ponto:
    data: date
    valor: float


@dataclass
class Serie:
    chave: str
    nome: str
    unidade: str
    pontos: list[Ponto]
    fonte: str
    obtido_em: datetime
    desatualizado: bool

    @property
    def ultimo(self) -> Ponto:
        return self.pontos[-1]

    @property
    def variacao(self) -> float | None:
        """Diferença entre os dois últimos pontos."""
        return self.pontos[-1].valor - self.pontos[-2].valor if len(self.pontos) >= 2 else None


def sgs(chave: str, n: int = 2) -> Serie:
    codigo, nome, unidade = SERIES[chave]
    r = obter(URL_SGS.format(codigo=codigo, n=n), params={"formato": "json"}, fonte=f"Banco Central (SGS {codigo})", ttl=6 * 3600)
    pontos = [Ponto(datetime.strptime(p["data"], "%d/%m/%Y").date(), numero_br(p["valor"])) for p in r.conteudo]
    if not pontos:
        raise ValueError(f"SGS {codigo} sem dados")
    return Serie(chave, nome, unidade, pontos, r.fonte, r.obtido_em, r.desatualizado)


@dataclass
class Expectativa:
    indicador: str
    ano: int
    mediana: float
    mediana_semana_anterior: float | None
    data: date
    respondentes: int | None
    fonte: str
    obtido_em: datetime


INDICADORES_FOCUS = {"ipca": "IPCA", "pib": "PIB Total", "selic": "Selic", "cambio": "Câmbio"}


def focus(indicador: str, ano: int | None = None) -> Expectativa:
    """Mediana do Focus para o ano (padrão: ano corrente) e a da semana anterior, para mostrar a mudança."""
    nome = INDICADORES_FOCUS[indicador]
    ano = ano or date.today().year
    params = {
        "$top": "20",
        "$filter": f"Indicador eq '{nome}' and DataReferencia eq '{ano}' and baseCalculo eq 0",
        "$orderby": "Data desc",
        "$format": "json",
        "$select": "Indicador,Data,DataReferencia,Mediana,numeroRespondentes,baseCalculo",
    }
    r = obter(URL_FOCUS, params=params, fonte="Banco Central (Focus)", ttl=12 * 3600)
    linhas = r.conteudo.get("value", [])
    if not linhas:
        raise ValueError(f"Focus sem dados para {nome} {ano}")
    atual = linhas[0]
    d_atual = date.fromisoformat(atual["Data"])
    anterior = next((l for l in linhas if (d_atual - date.fromisoformat(l["Data"])).days >= 7), None)
    return Expectativa(
        nome,
        ano,
        float(atual["Mediana"]),
        float(anterior["Mediana"]) if anterior else None,
        d_atual,
        atual.get("numeroRespondentes"),
        r.fonte,
        r.obtido_em,
    )
