"""Tesouro Direto: taxas e preços dos títulos (Tesouro Transparente, dados abertos). Sem chave."""

from __future__ import annotations

import csv
import io
import threading
from functools import lru_cache
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


@lru_cache(maxsize=None)  # o arquivo tem ~177 mil linhas e poucos milhares de datas diferentes
def _data(t: str) -> date:
    return datetime.strptime(t.strip(), "%d/%m/%Y").date()


_TRAVA = threading.Lock()
_MEMO: dict = {}  # arquivo já lido: (obtido_em, tamanho) → linhas (o CSV traz todo o histórico e é grande)


def _linhas(ttl: int):
    """Linhas do CSV como tuplas (tipo, data-base, vencimento, taxa compra, taxa venda, PU compra, PU venda), lidas uma
    vez por download — `titulos_atuais` e `historico_taxas` usam o mesmo arquivo."""
    r = obter(URL_PRECOS, fonte="Tesouro Transparente", ttl=ttl, formato="texto", codificacao="latin-1")
    chave = (r.obtido_em, len(r.conteudo))
    with _TRAVA:
        return _ler_memo(chave, r), r


def _ler_memo(chave, r):
    if _MEMO.get("chave") != chave:
        # csv.reader por posição (não DictReader) + datas em cache + nome do tipo compartilhado: 2,4 s → ~0,7 s e
        # ~40% menos memória guardada, com o mesmo resultado
        leitor = csv.reader(io.StringIO(r.conteudo), delimiter=";")
        cab = {c.strip(): i for i, c in enumerate(next(leitor, []))}
        it, ib, iv = cab.get("Tipo Titulo"), cab.get("Data Base"), cab.get("Data Vencimento")
        ix = [cab.get(c) for c in ("Taxa Compra Manha", "Taxa Venda Manha", "PU Compra Manha", "PU Venda Manha")]
        tipos: dict[str, str] = {}
        linhas = []
        for l in leitor:
            try:
                tipo = l[it].strip()
                linhas.append((tipos.setdefault(tipo, tipo), _data(l[ib]), _data(l[iv]),
                               *(numero_br(l[i]) if i is not None and i < len(l) else None for i in ix)))
            except (IndexError, TypeError, ValueError, AttributeError):
                continue  # linha quebrada no arquivo oficial (ou coluna que sumiu): ignora
        _MEMO.clear()
        _MEMO.update(chave=chave, linhas=linhas)
    return _MEMO["linhas"]


def titulos_atuais() -> Tabela:
    """Títulos da data-base mais recente do arquivo (o arquivo traz todo o histórico)."""
    linhas, r = _linhas(3 * 3600)
    if not linhas:
        raise ValueError("Arquivo do Tesouro vazio")
    ultima = max(l[1] for l in linhas)
    titulos = [Titulo(tipo, venc, ultima, tc, tv, pc, pv) for tipo, base, venc, tc, tv, pc, pv in linhas
               if base == ultima and venc > ultima]
    titulos.sort(key=lambda t: (t.tipo, t.vencimento))
    return Tabela(titulos, ultima, r.fonte, r.obtido_em, r.desatualizado)


def por_tipo(tabela: Tabela, chave: str) -> list[Titulo]:
    nomes = TIPOS[chave]
    return [t for t in tabela.titulos if t.tipo in nomes]


def historico_taxas(chave: str) -> tuple[list[tuple[date, date, float]], str]:
    """Todo o histórico de taxas de compra de um tipo de título: [(data-base, vencimento, taxa % a.a.)]."""
    linhas, r = _linhas(12 * 3600)
    nomes = TIPOS[chave]
    saida = [(base, venc, tc) for tipo, base, venc, tc, *_ in linhas if tipo in nomes and tc]  # 0,00 = sem oferta de compra
    saida.sort()
    return saida, r.fonte