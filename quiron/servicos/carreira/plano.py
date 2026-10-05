"""Plano de carreira: onde o Rickson está e os próximos passos, com números do que o Quíron já guarda
(Academia, diário de teses, portfólio, metas). Contas aqui; textos curtos e diretos."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from quiron.nucleo.config import ler_yaml
from quiron.servicos.carreira.banco import conectar


def config() -> dict[str, Any]:
    return ler_yaml("carreira")


def trilha() -> list[dict[str, Any]]:
    return ler_yaml("trilha_certificacoes")["trilha"]


def provas() -> dict[str, dict[str, str]]:
    with conectar() as con:
        return {r["cert"]: {"data": r["data"], "situacao": r["situacao"]} for r in con.execute("SELECT * FROM provas")}


def registrar_prova(cert: str, data_prova: date | None = None, situacao: str = "agendada") -> str:
    cert = cert.upper().replace(" ", "_")
    ids = {t["id"] for t in trilha()}
    if cert not in ids:
        raise ValueError(f"{cert} não está na trilha ({', '.join(sorted(ids))})")
    if situacao not in {"planejada", "agendada", "aprovado", "reprovado"}:
        raise ValueError("situação: planejada, agendada, aprovado ou reprovado")
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO provas VALUES (?,?,?,?)",
                    (cert, data_prova.isoformat() if data_prova else "", situacao, datetime.now().isoformat(timespec="seconds")))
    if data_prova:  # a Academia usa a mesma data no plano de estudo
        try:
            from quiron.servicos.academia.banco import Banco

            Banco().definir_pref(f"data_prova:{cert}", data_prova.isoformat())
        except Exception:  # noqa: BLE001
            pass
    return f"{cert}: {situacao}" + (f" — prova em {data_prova:%d/%m/%Y}" if data_prova else "")


def avaliar(competencia: str, nota: int) -> str:
    if not 0 <= nota <= 10:
        raise ValueError("nota de 0 a 10")
    nome = competencia.strip().lower()
    with conectar() as con:
        con.execute("INSERT INTO competencias(nome, nota, quando) VALUES (?,?,?)", (nome, nota, datetime.now().isoformat(timespec="seconds")))
    return f"Anotado: {nome} = {nota}/10"


def competencias() -> dict[str, list[tuple[str, int]]]:
    with conectar() as con:
        saida: dict[str, list[tuple[str, int]]] = {}
        for r in con.execute("SELECT nome, nota, quando FROM competencias ORDER BY quando"):
            saida.setdefault(r["nome"], []).append((r["quando"][:10], r["nota"]))
    return saida


def _prontidao(cert: str) -> float | None:
    try:
        from quiron.servicos.academia import diagnostico
        from quiron.servicos.academia.banco import Banco

        mods = diagnostico.diagnosticar(Banco(), cert)
        if not mods or not any(m.respostas for m in mods):
            return None
        return diagnostico.prontidao(mods)
    except Exception:  # noqa: BLE001 — área sem programa ainda
        return None


def semanas_necessarias(cert: str, horas_semana: float, prontidao: float | None = None) -> int:
    horas = float(config().get("horas_estudo", {}).get(cert, 250))
    if prontidao is not None:  # o que já domina reduz o caminho (até metade)
        horas *= max(0.5, 1 - prontidao * 0.5)
    return math.ceil(horas / max(horas_semana, 0.5))


def montar(hoje: date | None = None) -> str:
    from quiron.servicos.carreira import diario, portfolio

    hoje = hoje or date.today()
    cfg = config()
    hs = float(cfg.get("horas_semana", 5))
    pv = provas()
    partes = [f"🧭 Plano de carreira — {cfg['objetivo']}"]

    linhas, proxima = [], None
    for t in trilha():
        p = pv.get(t["id"], {})
        sit = p.get("situacao", "")
        if sit == "aprovado":
            linhas.append(f"✅ {t['id']} ({t['entidade']})")
            continue
        pront = _prontidao(t["id"])
        info = f" · domínio estimado {pront:.0%}" if pront is not None else ""
        if p.get("data"):
            d = date.fromisoformat(p["data"])
            sem = (d - hoje).days / 7
            precisa = semanas_necessarias(t["id"], hs, pront)
            folga = "no prazo" if sem >= precisa else f"apertado: precisa de ~{precisa} semanas a {hs:g} h/sem, faltam {sem:.0f}"
            info += f" · prova {d:%d/%m/%Y} ({folga})"
        linhas.append(f"{'▶️' if proxima is None else '⏳'} {t['id']} ({t['entidade']}){info}")
        if proxima is None:
            proxima = (t, pront)
    partes.append("Certificações:\n" + "\n".join(linhas))

    est = diario.estatisticas()
    meta_teses = cfg["pilares"]["track_record"].get("meta_teses_ano", 24)
    ano = hoje.year
    teses_ano = len([t for t in diario.listar("todas") if t.criada_em[:4] == str(ano)])
    tr = f"Track record: {teses_ano}/{meta_teses} teses em {ano} · {est['fechadas']} fechada(s)"
    if "acerto" in est:
        tr += f" · acerto {est['acerto']:.0f}%"
    if "brier" in est:
        tr += f" · Brier {est['brier']:.2f}".replace(".", ",")
    meta_port = cfg["pilares"]["portfolio"].get("meta_analises", 12)
    n_port = len(portfolio.itens())
    partes.append(tr + f"\nPortfólio: {n_port}/{meta_port} análises selecionadas")

    comp = competencias()
    if comp:
        partes.append("Competências (autoavaliação, a mais fraca primeiro):\n" + "\n".join(
            f"• {n}: {h[-1][1]}/10" + (f" ({h[-1][1] - h[0][1]:+d} desde {h[0][0][8:10]}/{h[0][0][5:7]})" if len(h) > 1 else "")
            for n, h in sorted(comp.items(), key=lambda x: x[1][-1][1])))
    else:
        partes.append("Competências: ainda sem autoavaliação. Ex.: /carreira avaliar valuation 6 ("
                      + ", ".join(cfg.get("competencias", [])[:5]) + "…)")

    passos = []
    if proxima:
        t, pront = proxima
        if not pv.get(t["id"], {}).get("data"):
            passos.append(f"Definir a data da prova {t['id']}: /carreira prova {t['id']} AAAA-MM-DD "
                          f"(~{semanas_necessarias(t['id'], hs, pront)} semanas a {hs:g} h/semana)")
        passos.append(f"Estudar {t['id']} na Academia: /area {t['id']} e /questoes · meta: /meta estudar {hs:g} horas por semana")
    if teses_ano < meta_teses:
        passos.append("Registrar 2 teses por mês no /diario (com confiança e o que invalidaria)")
    if n_port < meta_port:
        passos.append("Escolher análises para o portfólio: /portfolio (só as sem dados de cliente)")
    passos.append("Treinar entrevista para o cargo-alvo: /entrevista analista_research")
    partes.append("Próximos 90 dias:\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(passos, 1)))
    return "\n\n".join(partes)
