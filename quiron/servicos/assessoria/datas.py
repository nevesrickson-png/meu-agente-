"""Datas ditas em português ("amanhã", "sexta que vem", "dia 20", "15/10", "daqui a 2 semanas") → data de calendário.

O modelo só copia a expressão que ouviu; a conta da data é feita aqui, em Python (nunca pelo modelo)."""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from datetime import date, datetime, timedelta

DIAS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
           "nove": 9, "dez": 10, "quinze": 15, "trinta": 30}
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
LIMITE_DIAS = 3650  # "daqui a 999999999 dias" não quebra: passa de 10 anos, não é data de tarefa


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def dia_util(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def somar_dias_uteis(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _num(t: str) -> int | None:
    return int(t) if t.isdigit() else NUMEROS.get(t)


def interpretar(expressao: str | None, hoje: date) -> date | None:
    """Data da expressão, ou None se não houver data reconhecível. Datas no passado viram None."""
    if not expressao:
        return None
    t = _sem_acento(str(expressao)).strip()
    if re.search(r"\b(passad[oa]|ultim[oa])\b", t):
        return None  # "sexta passada": já foi
    d: date | None = None
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t):
        d = date(int(m[1]), int(m[2]), int(m[3]))
    elif m := re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):
        ano = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else hoje.year
        try:
            d = date(ano, int(m[2]), int(m[1]))
        except ValueError:
            return None
        if not m[3] and d < hoje:
            d = d.replace(year=d.year + 1)
    elif m := re.search(r"\b(\d{1,2}) de (" + "|".join(MESES) + r")(?: de (\d{4}))?\b", t):
        try:
            d = date(int(m[3]) if m[3] else hoje.year, MESES[m[2]], int(m[1]))
        except ValueError:
            return None
        if not m[3] and d < hoje:
            d = d.replace(year=d.year + 1)
    elif re.search(r"\bdepois de amanha\b", t):
        d = hoje + timedelta(days=2)
    elif re.search(r"\bamanha\b", t):
        d = hoje + timedelta(days=1)
    elif re.search(r"\bhoje\b|\bainda hoje\b|\bagora\b", t):
        d = hoje
    elif m := re.search(r"\b(?:em|daqui a|dentro de)\s+(\d+|\w+)\s+(dias? uteis|dias?|semanas?|mes(?:es)?)\b", t):
        n = _num(m[1])
        if n is None or n > LIMITE_DIAS:
            return None
        unidade = m[2]
        if unidade.startswith("dias u") or unidade.startswith("dia u"):
            d = somar_dias_uteis(hoje, n)
        elif unidade.startswith("dia"):
            d = hoje + timedelta(days=n)
        elif unidade.startswith("semana"):
            d = hoje + timedelta(weeks=n)
        else:
            mes = hoje.month - 1 + n
            ano, mes = hoje.year + mes // 12, mes % 12 + 1
            d = date(ano, mes, min(hoje.day, monthrange(ano, mes)[1]))
    elif m := re.search(r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)\b", t):
        alvo = DIAS[m[1]]
        dif = (alvo - hoje.weekday()) % 7
        proxima = re.search(r"que vem|proxim|seguinte", t)
        if dif == 0 or (proxima and dif < 7 and re.search(r"(semana que vem|proxima semana)", t)):
            dif = dif or 7
        if proxima and re.search(r"(semana que vem|proxima semana)", t):
            seg = hoje + timedelta(days=7 - hoje.weekday())  # segunda da semana que vem
            d = seg + timedelta(days=alvo)
        else:
            d = hoje + timedelta(days=dif)
    elif re.search(r"(semana que vem|proxima semana)", t):
        d = hoje + timedelta(days=7 - hoje.weekday())
    elif re.search(r"(fim|final) d[oe]s? mes", t):
        fim = date(hoje.year, hoje.month, monthrange(hoje.year, hoje.month)[1])
        while fim.weekday() >= 5:
            fim -= timedelta(days=1)
        d = max(fim, hoje)  # no último fim de semana do mês, o "fim do mês" é hoje (e não some)
    elif re.search(r"(mes que vem|proximo mes)", t):
        ano, mes = (hoje.year + 1, 1) if hoje.month == 12 else (hoje.year, hoje.month + 1)
        if m := re.search(r"\bdia (\d{1,2})\b", t):
            d = date(ano, mes, min(int(m[1]), monthrange(ano, mes)[1]))
        else:
            d = date(ano, mes, 1)
    elif m := re.search(r"\bdia (\d{1,2})\b", t):
        n = int(m[1])
        if not 1 <= n <= 31:
            return None
        ano, mes = hoje.year, hoje.month
        if n < hoje.day:
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        d = date(ano, mes, min(n, monthrange(ano, mes)[1]))
    if d is None or d < hoje:
        return None
    return d


def hora(expressao: str | None) -> tuple[int, int] | None:
    """'às 10h', '14h30', '9:15', 'às 10 horas', '3 da tarde' → (h, m)."""
    if not expressao:
        return None
    return extrair(str(expressao), date(2000, 1, 1))[2]


# ---------------------------------------------------------------- tempo relativo ("daqui a 2 horas")
RE_RELATIVO = re.compile(r"\b(?:daqui a|daqui|em|dentro de)\s+(?P<n>\d+|uma|um|duas|dois|tr[eê]s|meia)\s*"
                         r"(?P<u>horas?|h|minutos?|min)\b", re.I)


def relativo(texto: str, agora: datetime) -> tuple[str, datetime | None]:
    """'daqui a 2 horas ligar' → ('ligar', agora + 2 h). Só horas/minutos; dias ficam com `interpretar`."""
    m = RE_RELATIVO.search(texto or "")
    if not m:
        return texto, None
    n = {"uma": 1, "um": 1, "duas": 2, "dois": 2, "tres": 3, "três": 3, "meia": 0.5}.get(m["n"].lower()) or int(m["n"])
    if n > 24 * LIMITE_DIAS:
        return texto, None
    if m.group(0).lower().startswith("em") and m["u"].lower() == "h" and n > 6:
        return texto, None  # "reunião em 15h" é horário (15h), não "daqui a 15 horas"
    delta = timedelta(hours=n) if m["u"].lower().startswith("h") else timedelta(minutes=n)
    if m["n"].lower() == "meia" and not m["u"].lower().startswith("h"):
        return texto, None  # "meia minuto" não existe
    quando = (agora + delta).replace(second=0, microsecond=0)
    return (texto[:m.start()] + " " + texto[m.end():]).strip(), quando


# ---------------------------------------------------------------- extrair data e hora de uma frase (tarefas)
RE_DATA = re.compile(
    r"\b(depois de amanh[ãa]|amanh[ãa]|hoje|(?:na |nesta |nessa |esta |essa |(?:n[ao] )?próxim[ao] |(?:n[ao] )?proxim[ao] )?(?:segunda|terça|terca|quarta|quinta|"
    r"sexta|sábado|sabado|domingo)(?:-feira)?(?: que vem| da semana que vem| da próxima semana| passada)?|semana que vem|próxima semana|"
    r"proxima semana|(?:no )?(?:fim|final) do mês|m[êe]s que vem(?: dia \d{1,2})?|"
    r"(?:(?:no )?dia )?\d{1,2} de (?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?: de \d{4})?|"
    r"(?:no )?dia \d{1,2}(?:/\d{1,2}(?:/\d{2,4})?)?|"
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?|(?:daqui a|em|dentro de) \w+ (?:dias? úteis|dias? uteis|dias?|semanas?|m[eê]s(?:es)?))\b", re.I)
_PERIODO = r"(?:\s*(?:da\s+)?(?P<{}>manhã|manha|tarde|noite))"
RE_HORA = re.compile(r"(?:\b(?:às|as|a partir das|lá pelas|umas)\s*)?\b(?P<h>\d{1,2})\s*(?:h|:)\s*(?P<m>\d{2})?\b(?:min)?"
                     + _PERIODO.format("p1") + "?"
                     r"|\bàs\s+(?P<h2>\d{1,2})(?:\s+horas?|\s*hs)?(?:\s+e\s+(?P<m2>meia|quinze|\d{2})\b)?" + _PERIODO.format("p2") + r"?\b"
                     # "as" sem acento também é artigo ("comprar as 3 apostilas"): só vale com horas/período ou no fim
                     r"|\bas\s+(?P<h4>\d{1,2})(?:(?:\s+horas?|\s*hs)" + _PERIODO.format("p4") + r"?\b|" + _PERIODO.format("p5")
                     + r"\b|(?=\s*(?:$|[,.;!?]|\s(?:com|para|pra|no|na|em)\b)))"
                     r"|\b(?P<h3>\d{1,2})\s+(?:horas?\s+)?da\s+(?P<p3>manhã|manha|tarde|noite)\b", re.I)
_PREFIXOS = re.compile(r"^(?:me\s+lembr[ae]\s+(?:de\s+)?|lembr(?:ar|e-me|e)\s+(?:de\s+)?|lembrete:?\s*|tarefa:?\s*|anota(?:r)?\s+(?:a[ií]\s+)?(?:que\s+)?|"
                       r"preciso\s+|tenho\s+que\s+|não\s+esquecer\s+de\s+|nao\s+esquecer\s+de\s+)", re.I)


def extrair(texto: str, hoje: date) -> tuple[str, date | None, tuple[int, int] | None]:
    """'amanhã às 10h ligar para o CLI-012' → ('Ligar para o CLI-012', amanhã, (10, 0)). A data é calculada em Python."""
    resto = re.sub(r"\b(?:ao |às |as )?meio[- ]dia(?: e meia)?\b",
                   lambda m: " às 12h30 " if "meia" in m.group(0) else " às 12h ", texto.strip(), flags=re.I)
    resto = re.sub(r"\b(?:à |a )?meia[- ]noite\b", " às 23h59 ", resto, flags=re.I)
    d = None
    if m := RE_DATA.search(resto):
        d = interpretar(m.group(0), hoje)
        if d is not None:
            resto = resto[:m.start()] + " " + resto[m.end():]
    h = None
    m = RE_HORA.search(resto)
    if m and m.group("h") and re.match(r"\s*(de|por|semanais|diárias|diarias|seguidas)\b", resto[m.end():], re.I) \
            and not re.match(r"(às|as)\b", m.group(0), re.I):
        m = None  # "estudar 2h por dia" é duração, não horário
    if m and m.group("h4") and not (m.group("p4") or m.group("p5")) and not re.search(r"hora|hs", m.group(0), re.I) \
            and int(m.group("h4")) < 6 and resto[m.end():].strip()[:1] not in ("", ",", ".", ";", "!", "?"):
        m = None  # "vender as 2 no fechamento": "as" sem acento + número pequeno no meio da frase é quantidade
    if m:
        if m.group("h"):
            hh, mm = int(m.group("h")), int(m.group("m") or 0)
        else:
            hh = int(m.group("h2") or m.group("h4") or m.group("h3"))
            mm = {"meia": 30, "quinze": 15}.get(m.group("m2") or "", int(m.group("m2") or 0) if (m.group("m2") or "").isdigit() else 0)
        periodo = next((m.group(g) for g in ("p1", "p2", "p3", "p4", "p5") if m.group(g)), "") or ""
        if periodo.lower() in {"tarde", "noite"} and hh < 12:
            hh += 12
        if hh <= 23 and mm <= 59:
            h = (hh, mm)
            resto = resto[:m.start()] + " " + resto[m.end():]
    resto = re.sub(r"\s+", " ", resto)
    resto = re.sub(r"^[\s,;:.\-–]+|[\s,;:.\-–]+$", "", resto)
    resto = re.sub(r"\s+([,;.])", r"\1", resto)
    for _ in range(3):  # "anota aí que preciso comprar…" tem prefixos em sequência
        resto = _PREFIXOS.sub("", resto).strip()
    resto = re.sub(r"\b(às|as|no|na|em|de|para|até|ate)$", "", resto, flags=re.I).strip(" ,")
    return (resto[:1].upper() + resto[1:]) if resto else "", d, h
