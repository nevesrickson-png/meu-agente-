"""Textos prontos das cartas de gestores (MCP `quiron-noticias`, Telegram /cartas)."""

from __future__ import annotations

from collections import Counter

from quiron.servicos.cartas import coleta

ROTULOS = {"ativa": "ativas", "desatualizada": "desatualizadas (podem ter encerrado ou mudado de site)", "sem_data": "sem data",
           "sem_cartas": "sem cartas reconhecidas", "bloqueada": "bloqueiam leitura automática", "fora_do_ar": "fora do ar",
           "nao_conferida": "ainda não conferidas"}


def _data(iso: str) -> str:
    if not iso:
        return "s/ data"
    a, m, d = iso.split("-")
    return f"{m}/{a}" if d == "01" else f"{d}/{m}/{a}"


def listar(gestora: str | None = None, dias: int = 60, tipo: str | None = None, limite: int = 15) -> str:
    """Cartas recentes (ou as últimas de uma gestora). Confere as fontes vencidas antes (rápido se já conferiu hoje)."""
    try:
        coleta.atualizar(nomes=None if not gestora else [f["nome"] for f in coleta.fontes() if gestora.lower() in f["nome"].lower()])
    except Exception:  # noqa: BLE001 — sem rede: mostra o que já está guardado
        pass
    if gestora:
        itens = coleta.da_fonte(gestora, limite)
        cab = f"📬 **Cartas — {gestora}**"
        if not itens:
            nomes = [s for s in coleta.situacoes() if gestora.lower() in s["fonte"].lower()]
            if not nomes:
                return f"Não tenho a gestora “{gestora}” na lista (config/cartas_gestores.yaml)."
            s = nomes[0]
            return f"{cab}\nNão achei cartas no site ({ROTULOS.get(s['situacao'], s['situacao'])}). {s['detalhe']}\nPágina: {s['url']}"
    else:
        itens = coleta.recentes(dias=dias, tipo=tipo, limite=limite)
        cab = f"📬 **Cartas de gestores — últimos {dias} dias**"
        if not itens:
            return cab + "\nNenhuma carta nova encontrada no período."
    linhas = [cab] + [f"• {_data(c['data'])} — {c['fonte']}: {c['titulo']}\n  {c['link']}" for c in itens]
    linhas.append("📊 Sites públicos das gestoras — só título, data e link. Peça “resuma a carta da <gestora>” para ler uma.")
    return "\n".join(linhas)


def situacao() -> str:
    sits = coleta.situacoes()
    cont = Counter(s["situacao"] for s in sits)
    linhas = [f"📬 **Gestoras acompanhadas: {len(sits)}**"] + [f"• {n} {ROTULOS[k]}" for k, n in cont.most_common() if k in ROTULOS]
    paradas = sorted((s for s in sits if s["situacao"] == "desatualizada"), key=lambda s: s["ultima_carta"], reverse=True)[:12]
    if paradas:
        linhas.append("\nÚltima carta antiga (confira se a gestora ainda existe):")
        linhas += [f"• {s['fonte']} — {_data(s['ultima_carta'])}" for s in paradas]
    return "\n".join(linhas)


def ler(link: str) -> str:
    texto = coleta.ler_carta(link)
    return f"{texto}\n\n📄 Fonte: {link}"
