"""Datas ditas em português ("amanhã", "sexta que vem", "dia 20", "15/10", "daqui a 2 semanas") → data de calendário.

O modelo só copia a expressão que ouviu; a conta da data é feita aqui, em Python (nunca pelo modelo)."""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from datetime import date, timedelta

DIAS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
           "nove": 9, "dez": 10, "quinze": 15, "trinta": 30}


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
    elif re.search(r"\bdepois de amanha\b", t):
        d = hoje + timedelta(days=2)
    elif re.search(r"\bamanha\b", t):
        d = hoje + timedelta(days=1)
    elif re.search(r"\bhoje\b|\bainda hoje\b|\bagora\b", t):
        d = hoje
    elif m := re.search(r"\b(?:em|daqui a|dentro de)\s+(\d+|\w+)\s+(dias? uteis|dias?|semanas?|mes(?:es)?)\b", t):
        n = _num(m[1])
        if n is None:
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
        d = fim
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
    """'às 10h', '14h30', '9:15', '10 da manhã', '3 da tarde' → (h, m)."""
    if not expressao:
        return None
    t = _sem_acento(str(expressao))
    m = re.search(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b", t) or re.search(r"\b(\d{1,2})\s+(?:horas?\s+)?da\s+(manha|tarde|noite)\b", t)
    if not m:
        return None
    h = int(m[1])
    minutos = int(m[2]) if m.lastindex and m[2] and m[2].isdigit() else 0
    if m.lastindex and m[2] in {"tarde", "noite"} and h < 12:
        h += 12
    if h > 23 or minutos > 59:
        return None
    return h, minutos
