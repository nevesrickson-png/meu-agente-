"""Carteiras lidas ficam guardadas em `dados/carteiras/<id>.json` (fora do git): o agente passa só o id para a
análise, sem retranscrever posições (evita erro de cópia e não espalha dados pelo histórico da conversa)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.analise.relatorio import brl, pct
from quiron.servicos.carteira.modelo import CLASSES, Carteira


def pasta() -> Path:
    p = pasta_dados() / "carteiras"
    p.mkdir(parents=True, exist_ok=True)
    return p


def salvar(c: Carteira) -> str:
    base = "CART-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    ident, i = base, 2
    while (pasta() / f"{ident}.json").exists():
        ident, i = f"{base}-{i}", i + 1
    (pasta() / f"{ident}.json").write_text(json.dumps(c.como_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return ident


def carregar(ident: str) -> Carteira:
    ident = ident.strip()
    if ident.lower() in {"ultima", "última"}:
        arquivos = sorted(pasta().glob("CART-*.json"))
        if not arquivos:
            raise ValueError("nenhuma carteira guardada ainda")
        arq = arquivos[-1]
    else:
        if not re.fullmatch(r"CART-[\d-]+", ident):
            raise ValueError(f"id de carteira inválido: {ident}")
        arq = pasta() / f"{ident}.json"
        if not arq.exists():
            raise ValueError(f"carteira {ident} não encontrada")
    return Carteira.de_dict(json.loads(arq.read_text(encoding="utf-8")))


def descrever(c: Carteira, ident: str = "") -> str:
    """Resumo legível para conferir a leitura (vai para o agente e para o Rickson)."""
    total = c.total or 1
    linhas = [f"Carteira {ident} — {c.cliente or 'cliente não informado'} · perfil {c.perfil or 'não informado'} · "
              f"{brl(c.total)} em {len(c.posicoes)} posições"]
    for p in sorted(c.posicoes, key=lambda p: -p.valor):
        extra = [x for x in (p.ticker, p.taxa, f"venc. {p.vencimento:%m/%Y}" if p.vencimento else "",
                             f"custo {brl(p.custo)}" if p.custo else "") if x]
        linhas.append(f"- {p.nome} · {CLASSES[p.classe]['nome']} · {brl(p.valor)} ({pct(p.valor / total * 100, 1)})"
                      + (f" · {' · '.join(extra)}" if extra else ""))
    linhas += [f"⚠️ {a}" for a in c.avisos]
    return "\n".join(linhas)
