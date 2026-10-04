"""Banco Central: séries do SGS e expectativas do Focus (Olinda). Sem chave."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote

from quiron.servicos.mercado.http import FonteIndisponivel, numero_br, obter

URL_SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}"
URL_SGS_SOAP = "https://www3.bcb.gov.br/wssgs/services/FachadaWSSGS"
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


_SOAP = (
    '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
    'xmlns:pub="http://publico.ws.casosdeuso.sgs.pec.bcb.gov.br"><soapenv:Body><pub:getValoresSeriesXML>'
    '<in0 xsi:type="soapenc:Array" soapenc:arrayType="xsd:long[1]"><item>{codigo}</item></in0>'
    "<in1>{inicio}</in1><in2>{fim}</in2></pub:getValoresSeriesXML></soapenv:Body></soapenv:Envelope>"
)


def _data_sgs(t: str) -> date:
    """'02/10/2026', '2/10/2026' ou '8/2026' (séries mensais → dia 1)."""
    partes = [int(x) for x in t.strip().split("/")]
    return date(partes[-1], partes[-2], partes[0] if len(partes) == 3 else 1)


def _pontos_api(codigo: int, n: int):
    # pede alguns pontos a mais: séries como a Selic meta já vêm preenchidas até a próxima reunião do Copom
    r = obter(URL_SGS.format(codigo=codigo, n=n + 40), params={"formato": "json"}, fonte=f"Banco Central (SGS {codigo})", ttl=6 * 3600)
    return [Ponto(_data_sgs(p["data"]), numero_br(p["valor"])) for p in r.conteudo], r


def _pontos_soap(codigo: int):
    """Plano B: web service oficial do SGS (www3.bcb.gov.br), quando a api.bcb.gov.br recusa a conexão."""
    hoje = date.today()
    corpo = _SOAP.format(codigo=codigo, inicio=(hoje - timedelta(days=500)).strftime("%d/%m/%Y"), fim=(hoje + timedelta(days=60)).strftime("%d/%m/%Y"))
    r = obter(
        URL_SGS_SOAP, metodo="POST", corpo=corpo, cabecalhos={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
        fonte=f"Banco Central (SGS {codigo}, web service)", ttl=6 * 3600, formato="texto",
    )
    xml = html.unescape(r.conteudo)
    itens = re.findall(r"<DATA>\s*([\d/]+)\s*</DATA>\s*<VALOR>\s*([^<]*)</VALOR>", xml)
    return [Ponto(_data_sgs(d), numero_br(v)) for d, v in itens if v.strip()], r


_api_fora_ate = 0.0  # depois de uma recusa da api.bcb.gov.br, vai direto ao web service por 10 min


def sgs(chave: str, n: int = 2) -> Serie:
    global _api_fora_ate
    codigo, nome, unidade = SERIES[chave]
    try:
        if time.time() < _api_fora_ate:
            raise FonteIndisponivel("api.bcb.gov.br recusou a conexão há pouco")
        pontos, r = _pontos_api(codigo, n)
    except FonteIndisponivel:
        _api_fora_ate = time.time() + 600
        pontos, r = _pontos_soap(codigo)
    pontos = [p for p in pontos if p.data <= date.today() and p.valor is not None][-n:]
    if not pontos:
        raise ValueError(f"SGS {codigo} sem dados")
    return Serie(chave, nome, unidade, pontos, r.fonte, r.obtido_em, r.desatualizado)


URL_SGS_PERIODO = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def sgs_periodo(codigo: int, inicio: date, fim: date | None = None) -> tuple[list[Ponto], str]:
    """Série do SGS entre duas datas (para históricos longos, ex.: CDI mensal desde 2006). Devolve (pontos, fonte)."""
    global _api_fora_ate
    fim = fim or date.today()
    try:
        if time.time() < _api_fora_ate:
            raise FonteIndisponivel("api.bcb.gov.br recusou a conexão há pouco")
        r = obter(URL_SGS_PERIODO.format(codigo=codigo), params={"formato": "json", "dataInicial": inicio.strftime("%d/%m/%Y"),
                  "dataFinal": fim.strftime("%d/%m/%Y")}, fonte=f"Banco Central (SGS {codigo})", ttl=12 * 3600)
        pontos = [Ponto(_data_sgs(p["data"]), numero_br(p["valor"])) for p in r.conteudo]
    except FonteIndisponivel:
        _api_fora_ate = time.time() + 600
        corpo = _SOAP.format(codigo=codigo, inicio=inicio.strftime("%d/%m/%Y"), fim=fim.strftime("%d/%m/%Y"))
        r = obter(URL_SGS_SOAP, metodo="POST", corpo=corpo,
                  cabecalhos={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
                  fonte=f"Banco Central (SGS {codigo}, web service)", ttl=12 * 3600, formato="texto")
        itens = re.findall(r"<DATA>\s*([\d/]+)\s*</DATA>\s*<VALOR>\s*([^<]*)</VALOR>", html.unescape(r.conteudo))
        pontos = [Ponto(_data_sgs(d), numero_br(v)) for d, v in itens if v.strip()]
    return [p for p in pontos if p.valor is not None and p.data <= fim], r.fonte


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
    # O OData do BC exige espaço como %20 (com "+" a consulta é rejeitada), então a URL é montada aqui.
    seguros = "',"
    consulta = "&".join(f"{k}={quote(v, safe=seguros)}" for k, v in params.items())
    r = obter(f"{URL_FOCUS}?{consulta}", fonte="Banco Central (Focus)", ttl=12 * 3600)
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
