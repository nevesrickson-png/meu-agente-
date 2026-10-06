"""Alertas do Rickson: preço de ativo, variação no dia e palavra-chave nas notícias (`dados/alertas.json`).

O Terminal (`ALRT`) e o agente (MCP `quiron-mercado`) criam/listam/removem; o bot do Telegram avalia a cada poucos minutos
e avisa quando um alerta dispara (uma vez por disparo: depois de avisado, só volta a avisar se a condição sumir e voltar).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from quiron.nucleo.config import pasta_dados
from quiron.nucleo.trava import gravar_atomico, trava_arquivo

TIPOS = {"preco_acima": "preço acima de", "preco_abaixo": "preço abaixo de", "variacao": "variação no dia (±%) de pelo menos",
         "noticia": "notícia com a palavra"}


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
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):  # arquivo estragado (versão antiga sem gravação atômica)
        arq.replace(arq.with_name(f"alertas-estragado-{datetime.now():%Y%m%d-%H%M%S}.json"))
        return []
    return [Alerta(**a) for a in dados]


def _trava():
    """Bot, Terminal e MCP gravam o mesmo arquivo: trava entre processos."""
    return trava_arquivo(_arquivo())


def _gravar(itens: list[Alerta]) -> None:
    gravar_atomico(_arquivo(), json.dumps([asdict(a) for a in itens], ensure_ascii=False, indent=1))


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
    with _trava():
        itens = listar()
        novo = Alerta(max((a.id for a in itens), default=0) + 1, tipo, alvo, valor, datetime.now().isoformat(timespec="seconds"))
        _gravar(itens + [novo])
    return novo


def remover(ident: int) -> bool:
    with _trava():
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
    itens = listar()  # as consultas (rede, segundos) ficam FORA da trava; no fim só o estado é mesclado
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
    campos = ("disparado_em", "ativo_agora", "ultimo_valor", "detalhe", "vistos")
    avaliados = {a.id: a for a in itens}
    with _trava():  # relê: alerta criado ou removido durante a avaliação não se perde nem volta
        atuais = listar()
        for a in atuais:
            if (b := avaliados.get(a.id)) and (a.tipo, a.alvo, a.valor) == (b.tipo, b.alvo, b.valor):
                for c in campos:
                    setattr(a, c, getattr(b, c))
        _gravar(atuais)
    vivos = {a.id for a in atuais}
    return [a for a in novos if a.id in vivos]


def _noticias(termo: str) -> list[dict]:
    """Notícias das últimas 6 horas com a palavra no título (mesma coleta de RSS do Quíron)."""
    from quiron.servicos.noticias import coleta
    from quiron.servicos.noticias import consultas

    consultas._garantir_coleta()
    return [{"titulo": n.titulo, "link": n.link} for n in coleta.listar(6) if re.search(re.escape(termo), n.titulo, re.I)]


def mensagem(a: Alerta) -> str:
    return f"🔔 Alerta #{a.id}: " + a.descrever().split(" ", 1)[1].replace(" 🔔 DISPARADO", "")
