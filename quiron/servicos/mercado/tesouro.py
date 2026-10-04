"""Tesouro Direto: taxas e preços dos títulos (Tesouro Transparente, dados abertos). Sem chave."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from quiron.servicos.mercado.http import numero_br, obter

URL_PRECOS = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
    "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv"
)

TIPOS = {
    "prefixado": ("Tesouro Prefixado",),
    "prefixado_juros": ("Tesouro Prefixado com Juros Semestrais",),
    "ipca_mais": ("Tesouro IPCA+",),
    "ipca_mais_juros": ("Tesouro IPCA+ com Juros Semestrais",),
    "selic": ("Tesouro Selic",),
    "renda_mais": ("Tesouro Renda+ Aposentadoria Extra",),
    "educa_mais": ("Tesouro Educa+",),
}


@dataclass
class Titulo:
    tipo: str
    vencimento: date
    data_base: date
    taxa_compra: float | None  # % a.a. (IPCA+ e Selic: taxa real / spread)
    taxa_venda: float | None
    pu_compra: float | None
    pu_venda: float | None

    @property
    def nome(self) -> str:
        return f"{self.tipo} {self.vencimento.year}"


@dataclass
class Tabela:
    titulos: list[Titulo]
    data_base: date
    fonte: str
    obtido_em: datetime
    desatualizado: bool


def _data(t: str) -> date:
    return datetime.strptime(t.strip(), "%d/%m/%Y").date()


def titulos_atuais() -> Tabela:
    """Títulos da data-base mais recente do arquivo (o arquivo traz todo o histórico)."""
    r = obter(URL_PRECOS, fonte="Tesouro Transparente", ttl=3 * 3600, formato="texto", codificacao="latin-1")
    leitor = csv.DictReader(io.StringIO(r.conteudo), delimiter=";")
    linhas = list(leitor)
    if not linhas:
        raise ValueError("Arquivo do Tesouro vazio")
    ultima = max(_data(l["Data Base"]) for l in linhas)
    titulos = [
        Titulo(
            l["Tipo Titulo"].strip(),
            _data(l["Data Vencimento"]),
            ultima,
            numero_br(l.get("Taxa Compra Manha")),
            numero_br(l.get("Taxa Venda Manha")),
            numero_br(l.get("PU Compra Manha")),
            numero_br(l.get("PU Venda Manha")),
        )
        for l in linhas
        if _data(l["Data Base"]) == ultima and _data(l["Data Vencimento"]) > ultima
    ]
    titulos.sort(key=lambda t: (t.tipo, t.vencimento))
    return Tabela(titulos, ultima, r.fonte, r.obtido_em, r.desatualizado)


def por_tipo(tabela: Tabela, chave: str) -> list[Titulo]:
    nomes = TIPOS[chave]
    return [t for t in tabela.titulos if t.tipo in nomes]


def historico_taxas(chave: str) -> tuple[list[tuple[date, date, float]], str]:
    """Todo o histórico de taxas de compra de um tipo de título: [(data-base, vencimento, taxa % a.a.)]."""
    r = obter(URL_PRECOS, fonte="Tesouro Transparente", ttl=12 * 3600, formato="texto", codificacao="latin-1")
    nomes = TIPOS[chave]
    saida = []
    for l in csv.DictReader(io.StringIO(r.conteudo), delimiter=";"):
        if l["Tipo Titulo"].strip() in nomes:
            taxa = numero_br(l.get("Taxa Compra Manha"))
            if taxa is not None:
                saida.append((_data(l["Data Base"]), _data(l["Data Vencimento"]), taxa))
    saida.sort()
    return saida, r.fonte
