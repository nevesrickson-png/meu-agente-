"""Alertas do Rickson: preço de ativo, variação no dia e palavra-chave nas notícias (`dados/alertas.json`).

O Terminal (`ALRT`) e o agente (MCP `quiron-mercado`) criam/listam/removem; o bot do Telegram avalia a cada poucos minutos
e avisa quando um alerta dispara (uma vez por disparo: depois de avisado, só volta a avisar se a condição sumir e voltar).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from quiron.nucleo.config import pasta_dados

TIPOS = {"preco_acima": "preço acima de", "preco_abaixo": "preço abaixo de", "variacao": "variação no dia (±%) de pelo menos",
         "noticia": "notícia com a palavra"}
_trava = threading.Lock()


class AlertaInvalido(ValueError):
    pass


@dataclass
class Alerta:
    id: int
    tipo: str
    alvo: str  # ticker (preço/variação) ou palavra (notícia)
    valor: float | None = None
    criado_em: str = ""
    disparado_em: str = ""  # último disparo avisado
    ativo_agora: bool = False  # condição verdadeira na última avaliação
    ultimo_valor: float | None = None
    detalhe: str = ""
    vistos: list[str] = field(default_factory=list)  # links de notícias já avisadas

    def descrever(self) -> str:
        if self.tipo == "noticia":
            cond = f"notícia com “{self.alvo}”"
        elif self.tipo == "variacao":
            cond = f"{self.alvo} variar ±{self.valor:g}% no dia"
        else:
            cond = f"{self.alvo} {TIPOS[self.tipo]} {self.valor:g}"
        estado = " 🔔 DISPARADO" if self.ativo_agora else ""
        return f"#{self.id} {cond}{estado}" + (f" — {self.detalhe}" if self.detalhe else "")


def _arquivo() -> Path:
    return pasta_dados() / "alertas.json"


def listar() -> list[Alerta]:
    arq = _arquivo()
    if not arq.exists():
        return []
    return [Alerta(**a) for a in json.loads(arq.read_text(encoding="utf-8"))]


def _gravar(itens: list[Alerta]) -> None:
    arq = _arquivo()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps([asdict(a) for a in itens], ensure_ascii=False, indent=1), encoding="utf-8")


def criar(tipo: str, alvo: str, valor: float | None = None) -> Alerta:
    tipo = tipo.strip().lower()
    if tipo not in TIPOS:
        raise AlertaInvalido(f"tipo de alerta desconhecido: {tipo} (use {', '.join(TIPOS)})")
    alvo = alvo.strip()
    if not alvo:
        raise AlertaInvalido("informe o ativo ou a palavra")
    if tipo != "noticia":
        alvo = alvo.upper()
        if valor is None or float(valor) <= 0:
            raise AlertaInvalido("informe um valor positivo")
        valor = float(valor)
    with _trava:
        itens = listar()
        novo = Alerta(max((a.id for a in itens), default=0) + 1, tipo, alvo, valor, datetime.now().isoformat(timespec="seconds"))
        _gravar(itens + [novo])
    return novo


def remover(ident: int) -> bool:
    with _trava:
        itens = listar()
        restantes = [a for a in itens if a.id != ident]
        _gravar(restantes)
    return len(restantes) != len(itens)


def avaliar(cotacao: Callable[[str], Any] | None = None, buscar_noticias: Callable[[str], list[dict]] | None = None,
            agora: datetime | None = None) -> list[Alerta]:
    """Avalia todos os alertas. Devolve os que DISPARARAM AGORA (para avisar); o estado fica gravado."""
    if cotacao is None:
        from quiron.servicos.mercado import cotacoes

        cotacao = cotacoes.cotacao
    if buscar_noticias is None:
        buscar_noticias = _noticias
    agora = agora or datetime.now()
    novos = []
    with _trava:
        itens = listar()
        for a in itens:
            try:
                if a.tipo == "noticia":
                    achadas = [n for n in buscar_noticias(a.alvo) if n.get("link") not in a.vistos]
                    cond = bool(achadas)
                    if achadas:
                        a.detalhe = achadas[0].get("titulo", "")[:160]
                        a.vistos = (a.vistos + [n.get("link") for n in achadas])[-50:]
                else:
                    c = cotacao(a.alvo)
                    a.ultimo_valor = float(c.preco) if a.tipo != "variacao" else (c.variacao_pct or 0.0)
                    if a.tipo == "preco_acima":
                        cond = a.ultimo_valor >= a.valor
                    elif a.tipo == "preco_abaixo":
                        cond = a.ultimo_valor <= a.valor
                    else:
                        cond = abs(a.ultimo_valor) >= a.valor
                    a.detalhe = (f"agora {a.ultimo_valor:+.2f}%" if a.tipo == "variacao" else f"agora {a.ultimo_valor:.2f}") \
                        .replace(".", ",")
            except Exception as e:  # noqa: BLE001 — uma fonte fora do ar não derruba os outros alertas
                a.detalhe = f"sem dado agora ({type(e).__name__})"
                continue
            if cond and (not a.ativo_agora or a.tipo == "noticia"):
                a.disparado_em = agora.isoformat(timespec="seconds")
                novos.append(a)
            a.ativo_agora = cond
        _gravar(itens)
    return novos


def _noticias(termo: str) -> list[dict]:
    """Notícias das últimas 6 horas com a palavra no título (mesma coleta de RSS do Quíron)."""
    from quiron.servicos.noticias import coleta
    from quiron.servicos.noticias import consultas

    consultas._garantir_coleta()
    return [{"titulo": n.titulo, "link": n.link} for n in coleta.listar(6) if re.search(re.escape(termo), n.titulo, re.I)]


def mensagem(a: Alerta) -> str:
    return f"🔔 Alerta #{a.id}: " + a.descrever().split(" ", 1)[1].replace(" 🔔 DISPARADO", "")
