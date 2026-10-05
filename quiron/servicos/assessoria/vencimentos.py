"""Vencimentos: títulos e aplicações das carteiras guardadas (`dados/carteiras`) que vencem nos próximos dias.

Usa a carteira MAIS RECENTE de cada cliente (CLI-XXX); carteiras sem cliente entram como "sem código"."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from quiron.servicos.analise.relatorio import brl
from quiron.servicos.carteira import arquivo
from quiron.servicos.carteira.modelo import Carteira


@dataclass
class Vencimento:
    cliente: str
    carteira: str
    nome: str
    valor: float
    vencimento: date
    taxa: str = ""

    @property
    def dias(self) -> int:
        return (self.vencimento - date.today()).days


def ultimas_carteiras() -> dict[str, tuple[str, Carteira]]:
    """{cliente: (id, carteira)} com a carteira mais recente de cada cliente."""
    saida: dict[str, tuple[str, Carteira]] = {}
    for arq in sorted(arquivo.pasta().glob("CART-*.json")):
        try:
            c = Carteira.de_dict(json.loads(arq.read_text(encoding="utf-8")))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        saida[c.cliente or f"sem código ({arq.stem})"] = (arq.stem, c)  # ordem por nome = ordem de data: fica a última
    return saida


def proximos(dias: int = 90, cliente: str = "", hoje: date | None = None) -> list[Vencimento]:
    hoje = hoje or date.today()
    limite = hoje + timedelta(days=dias)
    itens = []
    for cli, (ident, c) in ultimas_carteiras().items():
        if cliente and cli.upper() != cliente.upper():
            continue
        for p in c.posicoes:
            if p.vencimento and hoje <= p.vencimento <= limite:
                itens.append(Vencimento(cli, ident, p.nome, p.valor, p.vencimento, p.taxa))
    return sorted(itens, key=lambda v: v.vencimento)


def descrever(itens: list[Vencimento], dias: int) -> str:
    if not itens:
        return (f"Nenhum vencimento nos próximos {dias} dias nas carteiras guardadas. (Só entram posições com vencimento "
                "informado — cole a carteira com 'venc 03/2027' ou mande o print/planilha.)")
    linhas = [f"📅 Vencimentos nos próximos {dias} dias (total {brl(sum(v.valor for v in itens))}):"]
    linhas += [f"• {v.vencimento:%d/%m/%Y} ({v.dias} dias) — {v.cliente}: {v.nome} · {brl(v.valor)}" + (f" · {v.taxa}" if v.taxa else "")
               for v in itens]
    linhas.append("Dica: chame o cliente ~30 dias antes para decidir a renovação (taxa atual vs. alternativas, IR, liquidez).")
    return "\n".join(linhas)
