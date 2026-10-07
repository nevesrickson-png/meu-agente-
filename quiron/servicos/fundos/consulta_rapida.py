"""Consulta rápida de um código (FII/Fiagro, ETF ou ação) SÓ com dados oficiais — nada vem da memória do modelo.

Usada pelo MCP `fii_dados` e pelo atalho do Telegram (mandar só "XPAG11")."""

from __future__ import annotations

import re

from quiron.servicos.fundos import cvm

RE_CODIGO = re.compile(r"^[A-Z]{4}\d{1,2}$")


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def texto_fii(ticker: str) -> str:
    """Último informe mensal do FII/Fiagro na CVM. Levanta cvm.FundoNaoEncontrado se não for FII/Fiagro."""
    h = cvm.fii(ticker)
    u = h[-1]
    dy12 = sum(x["dy_mes"] or 0 for x in h[-12:])
    from datetime import date

    hoje = date.today()
    atraso = (hoje.year * 12 + hoje.month) - (int(u["mes"][:4]) * 12 + int(u["mes"][5:7]))
    aviso = (f"⚠️ Último informe na CVM é de {u['mes']} ({atraso} meses atrás): o fundo pode ter mudado de categoria "
             "(ex.: virou Fiagro) ou estar atrasado — confira antes de usar.\n") if atraso > 4 else ""
    return aviso + (f"{u['ticker'] or ticker} — {u['nome']} · {u['segmento']} · informe {u['mes']}\n"
            f"- VP/cota R$ {_br(u['vp_cota'] or 0)} · PL R$ {_br(u['pl'] or 0, 0)} · cotistas {u['cotistas']}\n"
            f"- DY do mês {_br(u['dy_mes'] or 0)}% (12m: {_br(dy12)}% sobre o VP) · rentabilidade efetiva "
            f"{_br(u['rent_efetiva'] or 0)}%\n" + cvm.fonte())


def consultar(codigo: str) -> str:
    """FII/Fiagro pelo informe da CVM; senão cotação (ação/ETF). Nunca descreve o ativo sem dado."""
    t = (codigo or "").strip().upper()
    if not RE_CODIGO.match(t):
        return f"“{codigo}” não parece um código de negociação da B3 (ex.: HGLG11, PETR4)."
    partes = []
    if t.endswith(("11", "12", "13")):
        try:
            partes.append("🏢 " + texto_fii(t))
        except cvm.FundoNaoEncontrado:
            partes.append(f"{t} não aparece no informe mensal de FII/Fiagro da CVM (pode ser ETF, unit ou BDR).")
        except Exception as e:  # noqa: BLE001 — CVM fora do ar
            partes.append(f"Não consegui consultar a CVM agora ({type(e).__name__}).")
    if not partes or not partes[0].startswith("🏢"):
        try:
            from quiron.servicos.mercado import painel

            partes.append(painel.cotacao(t))
        except Exception as e:  # noqa: BLE001
            partes.append(f"Cotação indisponível agora ({type(e).__name__}).")
    return "\n".join(partes)
