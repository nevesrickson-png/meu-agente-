"""Rotina do Cérebro: preparar a pasta (uma vez por processo) e o ciclo do bot (a cada 15 min).

O ciclo: atualiza o índice, lê as edições que o Rickson fez na nota de Memória e regrava a nota diária de hoje (e a
de ontem logo depois da meia-noite, para fechar o dia). Tudo local, sem internet e sem IA.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from quiron.servicos.obsidian import diario, indice
from quiron.servicos.obsidian import pasta as P

_preparado: set[str] = set()
_trava = threading.Lock()


def preparar() -> int:
    """Cria a estrutura que faltar e leva as notas antigas do /nota para o Cérebro. Devolve quantas foram levadas."""
    chave = str(P.pasta())
    with _trava:
        if chave in _preparado:
            return 0
        _preparado.add(chave)
    P.garantir()
    from quiron.servicos.organizacao import notas

    try:
        levadas = notas.migrar_antigas()
    except Exception:  # noqa: BLE001 — a migração tenta de novo no próximo início
        logging.exception("Cérebro: falha ao levar as notas antigas")
        with _trava:
            _preparado.discard(chave)
        return 0
    if levadas:
        logging.info("Cérebro: %d nota(s) antiga(s) levada(s) para Minhas notas/Entrada", levadas)
    return levadas


def ciclo(longa=None) -> dict[str, object]:
    preparar()
    mudancas: list[str] = []
    if longa is not None:
        try:
            mudancas = longa.importar_edicoes_md()
        except Exception:  # noqa: BLE001
            logging.exception("Cérebro: falha ao ler as edições da memória")
    contagem = indice.atualizar(forcar=True)
    hoje = P.agora()
    diario.atualizar(hoje.date(), longa)
    if hoje.hour < 1:
        diario.atualizar(hoje.date() - timedelta(days=1), longa)
    return {"indice": contagem, "memoria": mudancas}


def situacao() -> dict[str, object]:
    preparar()
    return {"pasta": str(P.pasta().resolve()), **indice.estatisticas(), "diario": diario.caminho_rel(P.agora().date())}
