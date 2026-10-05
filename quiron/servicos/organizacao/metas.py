"""Metas com progresso: "/meta estudar 5 horas por semana", "/meta captar 2 milhões até dezembro", "/meta ler 12 livros".

O progresso é registrado com "/meta <nº> +2" e calculado aqui: metas semanais/mensais contam só o período corrente
(semana de segunda a domingo, mês do calendário); metas com prazo comparam com o ritmo esperado até a data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from quiron.servicos.assessoria import datas
from quiron.servicos.carteira.leitura import numero
from quiron.servicos.organizacao.banco import conectar

MULTIPLICADORES = {"mil": 1e3, "k": 1e3, "milhao": 1e6, "milhão": 1e6, "milhoes": 1e6, "milhões": 1e6, "mi": 1e6, "bi": 1e9}
MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


class MetaInvalida(ValueError):
    pass


@dataclass
class Meta:
    id: int
    texto: str
    alvo: float
    unidade: str
    periodo: str  # semanal | mensal | total
    prazo: str
    criada_em: str
    ativa: int = 1


def _de(r) -> Meta:
    return Meta(**{k: r[k] for k in r.keys()})


def interpretar(texto: str, hoje: date) -> tuple[str, float, str, str, str]:
    """→ (texto, alvo, unidade, periodo, prazo ISO)."""
    t = texto.strip()
    m = re.search(r"(?:R\$\s*)?(\d+(?:[.,]\d+)*)\s*(milh(?:ão|ao|ões|oes)\b|mil\b|mi\b|bi\b|k\b)?\s*([a-zà-ú$%]+)?", t, re.I)
    if not m:
        raise MetaInvalida("diga o número da meta (ex.: “estudar 5 horas por semana”, “captar 2 milhões até dezembro”)")
    alvo = numero(m.group(1))
    if alvo is None or alvo <= 0:
        raise MetaInvalida("a meta precisa de um número positivo")
    if m.group(2):
        alvo *= MULTIPLICADORES[m.group(2).lower()]
    unidade = (m.group(3) or "").lower()
    if unidade in {"por", "até", "ate", "em", "de", "no", "na"}:
        unidade = ""
    if "R$" in t or (m.group(2) and not unidade) or unidade in {"reais", "real"}:
        unidade = "R$"
    periodo = "semanal" if re.search(r"por semana|semanal|na semana|toda semana", t, re.I) else \
        "mensal" if re.search(r"por m[eê]s|mensal|no m[eê]s|todo m[eê]s", t, re.I) else "total"
    prazo = ""
    if mm := re.search(r"at[ée]\s+(?:o fim de\s+|o final de\s+)?(" + "|".join(MESES) + r")(?:\s+de\s+(\d{4}))?", t, re.I):
        mes = MESES[mm.group(1).lower()]
        ano = int(mm.group(2)) if mm.group(2) else (hoje.year if mes >= hoje.month else hoje.year + 1)
        prox = date(ano + (mes == 12), mes % 12 + 1, 1)
        prazo = (prox - timedelta(days=1)).isoformat()
    elif mm := re.search(r"at[ée]\s+(.+)$", t, re.I):
        d = datas.interpretar(mm.group(1), hoje)
        prazo = d.isoformat() if d else ""
    return t[:200], alvo, unidade, periodo, prazo


def criar(texto: str, hoje: date | None = None) -> Meta:
    hoje = hoje or date.today()
    t, alvo, unidade, periodo, prazo = interpretar(texto, hoje)
    with conectar() as con:
        cur = con.execute("INSERT INTO metas(texto, alvo, unidade, periodo, prazo, criada_em) VALUES (?,?,?,?,?,?)",
                          (t, alvo, unidade, periodo, prazo, datetime.now().isoformat(timespec="seconds")))
        return _de(con.execute("SELECT * FROM metas WHERE id = ?", (cur.lastrowid,)).fetchone())


def obter(ident: int) -> Meta:
    with conectar() as con:
        r = con.execute("SELECT * FROM metas WHERE id = ? AND ativa = 1", (ident,)).fetchone()
    if not r:
        raise MetaInvalida(f"meta #{ident} não existe")
    return _de(r)


def listar() -> list[Meta]:
    with conectar() as con:
        return [_de(r) for r in con.execute("SELECT * FROM metas WHERE ativa = 1 ORDER BY id")]


def registrar(ident: int, valor: float, nota: str = "", quando: datetime | None = None) -> Meta:
    m = obter(ident)
    with conectar() as con:
        con.execute("INSERT INTO metas_registros(meta, valor, quando, nota) VALUES (?,?,?,?)",
                    (ident, float(valor), (quando or datetime.now()).isoformat(timespec="seconds"), nota[:200]))
    return m


def encerrar(ident: int) -> bool:
    with conectar() as con:
        return con.execute("UPDATE metas SET ativa = 0 WHERE id = ?", (ident,)).rowcount > 0


def inicio_periodo(m: Meta, hoje: date) -> date:
    if m.periodo == "semanal":
        return hoje - timedelta(days=hoje.weekday())
    if m.periodo == "mensal":
        return hoje.replace(day=1)
    return date.fromisoformat(m.criada_em[:10])


def progresso(m: Meta, hoje: date | None = None) -> dict:
    """Feito no período, % do alvo e, se houver prazo, o ritmo esperado até hoje (tudo calculado aqui)."""
    hoje = hoje or date.today()
    ini = inicio_periodo(m, hoje)
    with conectar() as con:
        feito = con.execute("SELECT COALESCE(SUM(valor), 0) FROM metas_registros WHERE meta = ? AND substr(quando, 1, 10) >= ?",
                            (m.id, ini.isoformat())).fetchone()[0]
    p = {"feito": feito, "pct": feito / m.alvo * 100 if m.alvo else 0.0, "inicio": ini.isoformat(), "esperado_pct": None}
    if m.periodo == "semanal":
        p["esperado_pct"] = hoje.weekday() / 6 * 100  # segunda 0% → domingo 100%
    elif m.periodo == "mensal":
        from calendar import monthrange

        p["esperado_pct"] = (hoje.day - 1) / (monthrange(hoje.year, hoje.month)[1] - 1) * 100
    elif m.prazo:
        total = (date.fromisoformat(m.prazo) - ini).days or 1
        p["esperado_pct"] = min(100.0, max(0.0, (hoje - ini).days / total * 100))
    return p


def _num(v: float, unidade: str) -> str:
    from quiron.servicos.analise.relatorio import brl

    if unidade == "R$":
        return brl(v)
    return (f"{v:,.1f}".rstrip("0").rstrip(".") if v % 1 else f"{v:,.0f}").replace(",", "X").replace(".", ",").replace("X", ".") + (f" {unidade}" if unidade else "")


def descrever(m: Meta, hoje: date | None = None) -> str:
    p = progresso(m, hoje)
    barra = "▰" * min(10, round(p["pct"] / 10)) + "▱" * (10 - min(10, round(p["pct"] / 10)))
    periodo = {"semanal": " nesta semana", "mensal": " neste mês"}.get(m.periodo, "")
    linha = f"🎯 #{m.id} {m.texto}\n   {barra} {_num(p['feito'], m.unidade)} de {_num(m.alvo, m.unidade)}{periodo} ({p['pct']:.0f}%)"
    if p["esperado_pct"] is not None:
        dif = p["pct"] - p["esperado_pct"]
        linha += f" · {'no ritmo ✅' if dif >= -5 else f'abaixo do ritmo ({dif:+.0f} p.p.)'}"
    if m.prazo:
        linha += f" · prazo {date.fromisoformat(m.prazo):%d/%m/%Y}"
    return linha


def descrever_todas(hoje: date | None = None) -> str:
    itens = listar()
    if not itens:
        return "Nenhuma meta. Crie com /meta (ex.: /meta estudar 5 horas por semana)."
    return "\n".join(descrever(m, hoje) for m in itens) + "\n\nRegistrar progresso: /meta <nº> +2"
