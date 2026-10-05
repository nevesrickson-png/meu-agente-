"""Diário de teses e decisões: registrar a tese com premissas, o que a invalidaria, horizonte e confiança; revisar depois
com números e aprender com o resultado (track record do futuro analista).

- O modelo só ESTRUTURA o texto do Rickson (sem modelo, regras simples). Preço do dia, horizonte em data, retornos,
  excesso sobre o benchmark e calibração (Brier) são calculados aqui.
- Ativo da B3 é comparado com o Ibovespa. Fica em `dados/carreira.db`; na data de revisão chega um lembrete.
- Uso interno e de estudo (Resolução CVM 20): o diário não é recomendação para terceiros."""

from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from quiron.nucleo import cerebro
from quiron.servicos.assessoria import datas
from quiron.servicos.carreira.banco import conectar

HORIZONTE_PADRAO_DIAS = 90
RESULTADOS = {"acertou": 1.0, "parcial": 0.5, "errou": 0.0, "abandonada": None}
RE_TICKER = re.compile(r"\b([A-Z]{4}(?:3|4|5|6|11))\b")
MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


class TeseInvalida(ValueError):
    pass


@dataclass
class Tese:
    id: int
    titulo: str
    tese: str
    ativo: str = ""
    direcao: str = ""
    premissas: list[str] = field(default_factory=list)
    invalidacao: list[str] = field(default_factory=list)
    confianca: float | None = None
    criada_em: str = ""
    revisar_em: str = ""
    preco_inicial: float | None = None
    benchmark: str = ""
    bench_inicial: float | None = None
    lembrete: int | None = None
    situacao: str = "aberta"
    resultado: float | None = None
    resolvida_em: str = ""
    aprendizado: str = ""

    def resumo(self) -> str:
        conf = f" · confiança {self.confianca:.0f}%" if self.confianca is not None else ""
        ativo = f" · {self.ativo} {'▲' if self.direcao == 'alta' else '▼' if self.direcao == 'baixa' else ''}" if self.ativo else ""
        rev = f" · revisar {date.fromisoformat(self.revisar_em):%d/%m/%Y}" if self.revisar_em and self.situacao == "aberta" else ""
        return f"📓 #{self.id} {self.titulo}{ativo}{conf}{rev} ({self.situacao})"


def _de(r) -> Tese:
    d = {k: r[k] for k in r.keys()}
    d["premissas"], d["invalidacao"] = json.loads(d["premissas"] or "[]"), json.loads(d["invalidacao"] or "[]")
    return Tese(**d)


def obter(ident: int) -> Tese:
    with conectar() as con:
        r = con.execute("SELECT * FROM teses WHERE id = ?", (ident,)).fetchone()
    if not r:
        raise TeseInvalida(f"tese #{ident} não existe")
    return _de(r)


def listar(situacao: str = "aberta") -> list[Tese]:
    with conectar() as con:
        sql = "SELECT * FROM teses" + ("" if situacao == "todas" else " WHERE situacao = ?") + " ORDER BY revisar_em, id"
        return [_de(r) for r in con.execute(sql, () if situacao == "todas" else (situacao,))]


# ---------------------------------------------------------------- preço (fonte única, trocável nos testes)
def _cotacao_real(ativo: str) -> float:
    from quiron.servicos.mercado import cotacoes

    return float(cotacoes.cotacao(ativo).preco)


def _preco(ativo: str, cotacao: Callable[[str], float] | None) -> float | None:
    if not ativo:
        return None
    try:
        return (cotacao or _cotacao_real)(ativo)
    except Exception as e:  # noqa: BLE001 — sem preço não impede registrar
        logging.warning("sem cotação de %s (%s)", ativo, type(e).__name__)
        return None


def benchmark_de(ativo: str) -> str:
    return "IBOV" if RE_TICKER.fullmatch(ativo or "") else ""


# ---------------------------------------------------------------- registrar
SISTEMA = ("Você organiza o diário de teses de um assessor de investimentos que estuda para ser analista. Responda só JSON. "
           "Não invente fatos nem números; use só o que está no texto. Sem nomes de clientes.")
PEDIDO = """Texto da tese/decisão:
\"\"\"{texto}\"\"\"

JSON: {{"titulo": "até 80 caracteres", "tese": "a tese em 1-2 frases",
 "ativo": "ticker da B3 (ex.: WEGE3), IBOV, USDBRL, ou vazio se não houver ativo",
 "direcao": "alta" | "baixa" | "outro",
 "premissas": ["o que precisa ser verdade"], "invalidacao": ["o que mostraria que a tese está errada"],
 "horizonte": "a expressão de prazo como foi dita (ex.: 'em 6 meses', 'até dezembro') ou null",
 "confianca": número de 0 a 100 se foi dito, senão null}}"""


def _horizonte(expr: str | None, hoje: date) -> date:
    if expr:
        t = datas._sem_acento(str(expr))
        if m := re.search(r"\bem\s+(\d+)\s+anos?\b", t):
            return hoje.replace(year=hoje.year + int(m[1]))
        if m := re.search(r"(?:ate|em|no fim de|final de)\s+(" + "|".join(datas._sem_acento(k) for k in MESES) + r")(?:\s+de\s+(\d{4}))?", t):
            mes = {datas._sem_acento(k): v for k, v in MESES.items()}[m[1]]
            ano = int(m[2]) if m[2] else (hoje.year if mes >= hoje.month else hoje.year + 1)
            return date(ano, mes, monthrange(ano, mes)[1])
        d = datas.interpretar(expr, hoje)
        if d and d > hoje:
            return d
    return hoje + timedelta(days=HORIZONTE_PADRAO_DIAS)


def _por_regras(texto: str) -> dict[str, Any]:
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()]
    ativo = (RE_TICKER.search(texto) or [None, ""])[1]
    baixa = re.search(r"\b(cair|cai|queda|vender|caro|baixa|piorar)\b", texto, re.I)
    conf = re.search(r"(\d{1,3})\s*%\s*(?:de\s+)?(?:confian|certeza|chance)", texto, re.I)
    prazo = re.search(r"\b(em\s+\d+\s+(?:dias|semanas|mes(?:es)?|anos?)|até\s+\w+(?:\s+de\s+\d{4})?)\b", texto, re.I)
    return {"titulo": frases[0][:80] if frases else texto[:80], "tese": texto[:400], "ativo": ativo,
            "direcao": ("baixa" if baixa else "alta") if ativo else "outro", "premissas": [], "invalidacao": [],
            "horizonte": prazo.group(0) if prazo else None, "confianca": float(conf[1]) if conf else None}


def registrar(texto: str, agora: datetime | None = None, usar_cerebro: bool = True,
              cotacao: Callable[[str], float] | None = None, **extras: Any) -> Tese:
    from quiron.runtime.agendador import BRT

    texto = (texto or "").strip()
    if len(texto) < 15:
        raise TeseInvalida("escreva a tese com um pouco mais de detalhe (o quê, por quê, em quanto tempo)")
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    bruto = None
    if usar_cerebro:
        try:
            r = cerebro.perguntar(PEDIDO.format(texto=texto[:4000]), sistema=SISTEMA, temperatura=0, max_tokens=1500,
                                  response_format={"type": "json_object"}, **extras)
            b = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.texto.strip())
            bruto = json.loads(b[b.find("{"):b.rfind("}") + 1])
        except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
            logging.warning("diário sem IA (%s); usando regras", type(e).__name__)
    bruto = bruto or _por_regras(texto)
    ativo = str(bruto.get("ativo") or "").upper().strip()
    if ativo and not (RE_TICKER.fullmatch(ativo) or ativo in {"IBOV", "USDBRL", "EURBRL", "IFIX", "SMLL"}):
        ativo = (RE_TICKER.search(texto.upper()) or [None, ""])[1]
    conf = bruto.get("confianca")
    try:
        conf = max(0.0, min(100.0, float(conf))) if conf not in (None, "") else None
    except (TypeError, ValueError):
        conf = None
    revisar = _horizonte(bruto.get("horizonte"), agora.date())
    bench = benchmark_de(ativo)
    t = Tese(0, str(bruto.get("titulo") or texto[:80])[:120], str(bruto.get("tese") or texto)[:1000], ativo,
             str(bruto.get("direcao") or "outro").lower(), [str(x) for x in bruto.get("premissas") or []][:8],
             [str(x) for x in bruto.get("invalidacao") or []][:8], conf, agora.isoformat(timespec="seconds"), revisar.isoformat(),
             _preco(ativo, cotacao), bench, _preco(bench, cotacao))
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO teses(titulo, tese, ativo, direcao, premissas, invalidacao, confianca, criada_em, revisar_em, preco_inicial, "
            "benchmark, bench_inicial) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (t.titulo, t.tese, t.ativo, t.direcao, json.dumps(t.premissas, ensure_ascii=False), json.dumps(t.invalidacao, ensure_ascii=False),
             t.confianca, t.criada_em, t.revisar_em, t.preco_inicial, t.benchmark, t.bench_inicial))
        t.id = cur.lastrowid
    t.lembrete = _lembrete(t, agora)
    with conectar() as con:
        con.execute("UPDATE teses SET lembrete = ? WHERE id = ?", (t.lembrete, t.id))
    return t


def _lembrete(t: Tese, agora: datetime) -> int | None:
    from quiron.runtime.agendador import BRT, Agendador

    quando = datetime.combine(date.fromisoformat(t.revisar_em), time(9, 0), tzinfo=BRT)
    if quando <= agora:
        return None
    return Agendador().criar(f"[D{t.id}] Revisar a tese: {t.titulo} — /diario revisar {t.id}", "lembrete", "uma vez", quando, agora=agora).id


def descrever(t: Tese) -> str:
    linhas = [t.resumo(), f"Tese: {t.tese}"]
    if t.premissas:
        linhas.append("Premissas: " + "; ".join(t.premissas))
    if t.invalidacao:
        linhas.append("Invalidaria: " + "; ".join(t.invalidacao))
    if t.preco_inicial is not None:
        linhas.append(f"Preço no registro: {t.ativo} {t.preco_inicial:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                      + (f" · {t.benchmark} {t.bench_inicial:,.0f}".replace(",", ".") if t.bench_inicial else ""))
    return "\n".join(linhas)


# ---------------------------------------------------------------- revisar e resolver
def medir(t: Tese, cotacao: Callable[[str], float] | None = None, agora: datetime | None = None) -> dict[str, Any]:
    """Retorno do ativo e do benchmark desde o registro (calculado aqui)."""
    from quiron.runtime.agendador import BRT

    agora = agora or datetime.now(BRT)
    m: dict[str, Any] = {"dias": (agora.date() - datetime.fromisoformat(t.criada_em).date()).days,
                         "vencida": bool(t.revisar_em) and agora.date() >= date.fromisoformat(t.revisar_em)}
    preco, bench = _preco(t.ativo, cotacao), _preco(t.benchmark, cotacao)
    m.update(preco=preco, bench=bench)
    if preco and t.preco_inicial:
        m["retorno"] = (preco / t.preco_inicial - 1) * 100
    if bench and t.bench_inicial:
        m["retorno_bench"] = (bench / t.bench_inicial - 1) * 100
    if "retorno" in m and "retorno_bench" in m:
        m["excesso"] = m["retorno"] - m["retorno_bench"]
    if "retorno" in m and t.direcao in {"alta", "baixa"}:
        base = m.get("excesso", m["retorno"])
        m["a_favor"] = base > 0 if t.direcao == "alta" else base < 0
    return m


def _pct(v: float | None) -> str:
    return "—" if v is None else (f"{v:+.1f}%".replace(".", ","))


def revisar(ident: int, nota: str = "", cotacao: Callable[[str], float] | None = None, agora: datetime | None = None) -> str:
    t = obter(ident)
    m = medir(t, cotacao, agora)
    with conectar() as con:
        con.execute("INSERT INTO revisoes_teses(tese, quando, preco, bench, nota) VALUES (?,?,?,?,?)",
                    (ident, (agora or datetime.now()).isoformat(timespec="seconds"), m.get("preco"), m.get("bench"), nota[:500]))
    return _texto_revisao(t, m)


def _texto_revisao(t: Tese, m: dict[str, Any]) -> str:
    linhas = [t.resumo(), f"Tese: {t.tese}", f"Há {m['dias']} dias" + (" — chegou a data de revisão" if m["vencida"] else "")]
    if "retorno" in m:
        linhas.append(f"{t.ativo}: {_pct(m['retorno'])}" + (f" · {t.benchmark}: {_pct(m.get('retorno_bench'))} · excesso {_pct(m.get('excesso'))}"
                                                            if "retorno_bench" in m else ""))
    if "a_favor" in m:
        linhas.append("O mercado, até aqui: " + ("a favor da tese ✅" if m["a_favor"] else "contra a tese ❌") + " (preço não é tudo: confira as premissas)")
    if t.premissas:
        linhas.append("Premissas — ainda valem? " + "; ".join(t.premissas))
    if t.invalidacao:
        linhas.append("Algum gatilho de invalidação aconteceu? " + "; ".join(t.invalidacao))
    linhas.append(f"Fechar: /diario {t.id} acertou | parcial | errou | abandonada <o que aprendeu> · manter aberta: /diario adiar {t.id} 3 meses")
    return "\n".join(linhas)


def resolver(ident: int, resultado: str, aprendizado: str = "", agora: datetime | None = None) -> Tese:
    resultado = resultado.lower().strip()
    if resultado not in RESULTADOS:
        raise TeseInvalida(f"resultado deve ser: {', '.join(RESULTADOS)}")
    t = obter(ident)
    if t.lembrete:
        from quiron.runtime.agendador import Agendador

        Agendador().cancelar(t.lembrete)
    with conectar() as con:
        con.execute("UPDATE teses SET situacao = ?, resultado = ?, resolvida_em = ?, aprendizado = ? WHERE id = ?",
                    (resultado, RESULTADOS[resultado], (agora or datetime.now()).isoformat(timespec="seconds"), aprendizado[:1000], ident))
    return obter(ident)


def adiar(ident: int, expressao: str, agora: datetime | None = None) -> Tese:
    from quiron.runtime.agendador import BRT, Agendador

    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    t = obter(ident)
    if t.situacao != "aberta":
        raise TeseInvalida(f"a tese #{ident} já foi fechada")
    exp = re.sub(r"^(\d+)\s*(mes(?:es)?|meses|dias?|semanas?|anos?)$", r"em \1 \2", expressao.strip())
    t.revisar_em = _horizonte(exp, agora.date()).isoformat()
    if t.lembrete:
        Agendador().cancelar(t.lembrete)
    t.lembrete = _lembrete(t, agora)
    with conectar() as con:
        con.execute("UPDATE teses SET revisar_em = ?, lembrete = ? WHERE id = ?", (t.revisar_em, t.lembrete, ident))
    return t


def estatisticas() -> dict[str, Any]:
    """Track record: acertos e calibração (Brier: 0 = perfeito; 0,25 = chutar 50% sempre)."""
    fechadas = [t for t in listar("todas") if t.resultado is not None]
    com_conf = [t for t in fechadas if t.confianca is not None]
    est: dict[str, Any] = {"fechadas": len(fechadas), "abertas": len(listar("aberta"))}
    if fechadas:
        est["acerto"] = sum(t.resultado for t in fechadas) / len(fechadas) * 100
    if com_conf:
        est["brier"] = sum((t.confianca / 100 - t.resultado) ** 2 for t in com_conf) / len(com_conf)
        faixas = {}
        for nome, lo, hi in (("até 59%", 0, 60), ("60–79%", 60, 80), ("80%+", 80, 101)):
            g = [t for t in com_conf if lo <= t.confianca < hi]
            if g:
                faixas[nome] = (len(g), sum(t.resultado for t in g) / len(g) * 100, sum(t.confianca for t in g) / len(g))
        est["faixas"] = faixas
    return est


def texto_estatisticas() -> str:
    e = estatisticas()
    if not e["fechadas"]:
        return f"Track record: {e['abertas']} tese(s) aberta(s), nenhuma fechada ainda."
    linhas = [f"Track record: {e['fechadas']} fechada(s), acerto {e['acerto']:.0f}% · {e['abertas']} aberta(s)".replace(".", ",")]
    if "brier" in e:
        linhas.append(f"Calibração (Brier): {e['brier']:.3f} (0 = perfeito; 0,25 = sempre 50%)".replace(".", ","))
        for nome, (n, acerto, conf) in e["faixas"].items():
            leitura = "bem calibrado" if abs(acerto - conf) <= 10 else ("confiante demais" if acerto < conf else "confiança de menos")
            linhas.append(f"• confiança {nome}: {n} tese(s), acertou {acerto:.0f}% vs. confiança média {conf:.0f}% — {leitura}")
    return "\n".join(linhas)


def revisao_de_teses(dias: int = 7, cotacao: Callable[[str], float] | None = None, agora: datetime | None = None) -> str:
    """Revisão das teses que vencem nos próximos `dias` (ou já venceram) + track record."""
    from quiron.runtime.agendador import BRT

    agora = agora or datetime.now(BRT)
    limite = agora.date() + timedelta(days=dias)
    devidas = [t for t in listar("aberta") if t.revisar_em and date.fromisoformat(t.revisar_em) <= limite]
    partes = [f"📓 Revisão de teses — {agora:%d/%m/%Y}"]
    if not devidas:
        partes.append(f"Nenhuma tese para revisar até {limite:%d/%m}.")
    for t in devidas:
        partes.append(_texto_revisao(t, medir(t, cotacao, agora)))
    partes.append(texto_estatisticas())
    partes.append("Uso interno e de estudo — não constitui recomendação nem relatório de análise.")
    return "\n\n".join(partes)
