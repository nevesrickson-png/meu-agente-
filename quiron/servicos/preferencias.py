"""Preferências que o Rickson muda pela tela de Configurações (sem editar arquivo).

Tudo vai para `dados/ajustes/*.yaml` (por cima de `config/`, fora do git) ou para o agendador:
- watchlist (ações, FIIs, ETFs, índices, moedas, commodities) → ajustes/watchlist.yaml
- briefing: liga/desliga, horário e dias → rotina "Faça meu briefing." no agendador
- mensagens automáticas por dia → ajustes/persona.yaml (mensagens_automaticas.maximo_por_dia)
- fontes de notícias ligadas/desligadas → ajustes/fontes_noticias.yaml (lista `desligadas`)
"""

from __future__ import annotations

import re
from typing import Any

from quiron.nucleo.config import escrever_ajuste, ler_ajuste, ler_yaml, salvar_ajuste

TEXTO_BRIEFING = "Faça meu briefing."
LISTAS_WATCHLIST = ("acoes", "fiis", "etfs", "indices", "moedas", "commodities")
_ATIVO = re.compile(r"^[A-Za-z0-9^=._\-]{2,20}$")
_HORA = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class PreferenciaInvalida(ValueError):
    pass


def _agendador():
    from quiron.runtime.agendador import Agendador

    return Agendador()


def rotina_briefing(ag=None):
    """A rotina do briefing (a primeira que pede o briefing), ou None se estiver desligada."""
    ag = ag or _agendador()
    return next((a for a in ag.listar() if a.tipo != "lembrete" and "briefing" in a.texto.lower()), None)


def _registro_rotinas():
    from quiron.nucleo.config import pasta_dados

    return pasta_dados() / "rotinas_padrao_criadas.json"


def _briefing_ja_configurado() -> bool:
    """O bot já criou a rotina padrão do briefing (ou o Rickson já mexeu nela)?"""
    import json

    try:
        return TEXTO_BRIEFING in json.loads(_registro_rotinas().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def _marcar_briefing_configurado() -> None:
    """Escolha feita pela tela vale: o bot não cria (nem recria) a rotina padrão do briefing por cima dela."""
    import json

    arq = _registro_rotinas()
    try:
        ja = set(json.loads(arq.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        ja = set()
    ja.add(TEXTO_BRIEFING)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(sorted(ja), ensure_ascii=False), encoding="utf-8")


def ler() -> dict[str, Any]:
    w = ler_yaml("watchlist") or {}
    persona = ler_yaml("persona") or {}
    fontes_cfg = ler_yaml("fontes_noticias") or {}
    desligadas = set(fontes_cfg.get("desligadas") or [])
    r = rotina_briefing()
    hora, dias = "07:30", "diario"
    if r:
        partes = r.recorrencia.split()
        if len(partes) == 2 and partes[0] in {"diario", "dias_uteis"}:
            dias, hora = partes
    return {
        "watchlist": {k: [str(x) for x in (w.get(k) or [])] for k in LISTAS_WATCHLIST},
        # antes da 1ª vez do bot a rotina ainda não existe, mas vai ser criada às 07:30: mostra como ligada
        "briefing": {"ativo": r is not None or not _briefing_ja_configurado(), "hora": hora, "dias": dias},
        "mensagens_dia": int(((persona.get("mensagens_automaticas") or {}).get("maximo_por_dia")) or 3),
        "noticias": [{"nome": f["nome"], "grupo": f.get("grupo", ""), "ativa": f["nome"] not in desligadas and f.get("ativo", True)}
                     for f in fontes_cfg.get("fontes") or []],
    }


def _lista_ativos(valor: Any, rotulo: str) -> list[str]:
    itens = valor if isinstance(valor, list) else re.split(r"[,\s;]+", str(valor or ""))
    saida = []
    for x in (str(i).strip() for i in itens):
        if not x:
            continue
        if not _ATIVO.fullmatch(x):
            raise PreferenciaInvalida(f"“{x}” não parece um código de ativo válido ({rotulo}).")
        if rotulo == "commodities":  # commodities usam nomes internos (ouro, petroleo_brent) ou tickers do Yahoo (GC=F)
            x = x if "=" in x else x.lower()
        elif not x.startswith("^"):
            x = x.upper()
        if x not in saida:
            saida.append(x)
    if len(saida) > 40:
        raise PreferenciaInvalida(f"Muitos ativos em {rotulo} (máximo 40).")
    return saida


def salvar(novas: dict[str, Any]) -> dict[str, Any]:
    """Valida e grava só o que veio. Devolve as preferências atualizadas."""
    if "watchlist" in novas:
        w = novas["watchlist"] or {}
        base = ler_yaml("watchlist", com_ajustes=False) or {}
        ajuste = ler_ajuste("watchlist")
        for k in LISTAS_WATCHLIST:  # guarda só o que difere do padrão (melhorias futuras do padrão continuam chegando)
            if k in w:
                lista = _lista_ativos(w[k], k)
                if lista == [str(x) for x in (base.get(k) or [])]:
                    ajuste.pop(k, None)
                else:
                    ajuste[k] = lista
        escrever_ajuste("watchlist", ajuste)
    if "mensagens_dia" in novas:
        try:
            n = int(novas["mensagens_dia"])
        except (TypeError, ValueError) as e:
            raise PreferenciaInvalida("Mensagens automáticas por dia: use um número de 0 a 10.") from e
        if not 0 <= n <= 10:
            raise PreferenciaInvalida("Mensagens automáticas por dia: use um número de 0 a 10.")
        padrao = ((ler_yaml("persona", com_ajustes=False) or {}).get("mensagens_automaticas") or {}).get("maximo_por_dia", 3)
        ajuste = ler_ajuste("persona")
        if n == padrao:
            (ajuste.get("mensagens_automaticas") or {}).pop("maximo_por_dia", None)
            if not ajuste.get("mensagens_automaticas"):
                ajuste.pop("mensagens_automaticas", None)
            escrever_ajuste("persona", ajuste)
        else:
            salvar_ajuste("persona", {"mensagens_automaticas": {"maximo_por_dia": n}})
    if "noticias" in novas:
        validas = {f["nome"] for f in (ler_yaml("fontes_noticias", com_ajustes=False) or {}).get("fontes", [])}
        desligadas = sorted({f["nome"] for f in novas["noticias"] or [] if f.get("nome") in validas and not f.get("ativa", True)})
        if validas and len(desligadas) >= len(validas):
            raise PreferenciaInvalida("Deixe pelo menos uma fonte de notícias ligada.")
        ajuste = ler_ajuste("fontes_noticias")
        if desligadas:
            ajuste["desligadas"] = desligadas
        else:
            ajuste.pop("desligadas", None)
        escrever_ajuste("fontes_noticias", ajuste)
        try:
            from quiron.servicos.noticias import relevancia

            relevancia.limpar_cache()
        except Exception:  # noqa: BLE001
            pass
    if "briefing" in novas:
        b = novas["briefing"] or {}
        configurar_briefing(bool(b.get("ativo", True)), str(b.get("hora", "07:30")), str(b.get("dias", "diario")))
    return ler()


def configurar_briefing(ativo: bool, hora: str, dias: str = "diario") -> str:
    """Troca a rotina do briefing (uma só). Desligar = cancelar a rotina; o bot não a recria sozinho."""
    if not _HORA.fullmatch(hora.strip()):
        raise PreferenciaInvalida("Horário do briefing no formato HH:MM (ex.: 07:30).")
    if dias not in {"diario", "dias_uteis"}:
        raise PreferenciaInvalida("Dias do briefing: todos os dias ou só dias úteis.")
    h, m = (int(x) for x in hora.strip().split(":"))
    recorrencia = f"{dias} {h:02d}:{m:02d}"
    ag = _agendador()
    atuais = [a for a in ag.listar() if a.tipo != "lembrete" and "briefing" in a.texto.lower()]
    if ativo and len(atuais) == 1 and atuais[0].recorrencia == recorrencia:
        _marcar_briefing_configurado()
        return recorrencia
    for a in atuais:
        ag.cancelar(a.id)
    if ativo:
        ag.criar(TEXTO_BRIEFING, "tarefa", recorrencia, None)
    _marcar_briefing_configurado()
    return recorrencia if ativo else "desligado"
