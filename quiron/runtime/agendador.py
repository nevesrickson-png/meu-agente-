"""Agendador (ideia do Hermes/OpenClaw): lembretes e tarefas recorrentes em linguagem simples, guardados em SQLite.

Recorrências legíveis (o modelo traduz o pedido do Rickson para uma delas):
- "uma vez"               → só na data/hora informada
- "diario HH:MM"          → todo dia
- "dias_uteis HH:MM"      → segunda a sexta
- "semanal <dia> HH:MM"   → ex.: "semanal sexta 18:00"
- "mensal <dia> HH:MM"    → ex.: "mensal 5 09:00"
Tipos: "lembrete" (manda o texto) ou "tarefa" (o agente executa o pedido e manda o resultado, ex.: briefing).
Também controla o limite de mensagens automáticas por dia (persona: 3).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from quiron.nucleo.config import ler_yaml, pasta_dados

BRT = ZoneInfo("America/Sao_Paulo")
DIAS = {"segunda": 0, "terca": 1, "terça": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6}


class RecorrenciaInvalida(ValueError):
    pass


@dataclass
class Agendamento:
    id: int
    texto: str
    tipo: str
    recorrencia: str
    proxima: datetime

    def descrever(self) -> str:
        quando = self.proxima.strftime("%d/%m %H:%M")
        rec = "" if self.recorrencia == "uma vez" else f" · repete: {self.recorrencia}"
        return f"#{self.id} {quando} — {'⏰' if self.tipo == 'lembrete' else '⚙️'} {self.texto}{rec}"


def _hora(texto: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2})[:h](\d{2})", texto.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise RecorrenciaInvalida(f"hora inválida: {texto}")
    return int(m.group(1)), int(m.group(2))


def proxima_execucao(recorrencia: str, depois_de: datetime) -> datetime | None:
    """Próxima data/hora (Brasília) estritamente depois de `depois_de`. None para "uma vez"."""
    partes = recorrencia.strip().lower().split()
    if not partes or partes[0] == "uma":
        return None
    tipo = partes[0]
    base = depois_de.astimezone(BRT)
    if tipo in {"diario", "diário", "dias_uteis"} and len(partes) == 2:
        h, m = _hora(partes[1])
        cand = base.replace(hour=h, minute=m, second=0, microsecond=0)
        while cand <= base or (tipo == "dias_uteis" and cand.weekday() >= 5):
            cand += timedelta(days=1)
        return cand
    if tipo == "semanal" and len(partes) == 3 and partes[1] in DIAS:
        h, m = _hora(partes[2])
        cand = base.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=(DIAS[partes[1]] - base.weekday()) % 7)
        return cand if cand > base else cand + timedelta(days=7)
    if tipo == "mensal" and len(partes) == 3 and partes[1].isdigit() and 1 <= int(partes[1]) <= 28:
        h, m = _hora(partes[2])
        cand = base.replace(day=int(partes[1]), hour=h, minute=m, second=0, microsecond=0)
        if cand <= base:
            cand = (cand.replace(day=1) + timedelta(days=32)).replace(day=int(partes[1]))
        return cand
    raise RecorrenciaInvalida(
        f"recorrência inválida: “{recorrencia}”. Use: uma vez · diario HH:MM · dias_uteis HH:MM · semanal <dia> HH:MM · mensal <1-28> HH:MM")


class Agendador:
    def __init__(self, caminho: Path | None = None):
        caminho = caminho or pasta_dados() / "agenda.db"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        with self.con:
            self.con.execute("CREATE TABLE IF NOT EXISTS agendamentos (id INTEGER PRIMARY KEY, texto TEXT, tipo TEXT, recorrencia TEXT, "
                             "proxima TEXT, ativo INTEGER DEFAULT 1, criado_em TEXT)")
            self.con.execute("CREATE TABLE IF NOT EXISTS envios_automaticos (dia TEXT, quando TEXT, motivo TEXT)")

    def criar(self, texto: str, tipo: str, recorrencia: str, quando: datetime | None, agora: datetime | None = None) -> Agendamento:
        agora = (agora or datetime.now(BRT)).astimezone(BRT)
        if tipo not in {"lembrete", "tarefa"}:
            raise ValueError("tipo deve ser 'lembrete' ou 'tarefa'")
        recorrencia = (recorrencia or "uma vez").strip().lower()
        if recorrencia.startswith("uma"):
            if not quando:
                raise ValueError("para 'uma vez' informe a data e hora")
            proxima = quando.astimezone(BRT) if quando.tzinfo else quando.replace(tzinfo=BRT)
            if proxima <= agora:
                raise ValueError(f"o horário {proxima:%d/%m %H:%M} já passou")
            recorrencia = "uma vez"
        else:
            proxima = proxima_execucao(recorrencia, agora)
        with self.con:
            cur = self.con.execute("INSERT INTO agendamentos(texto, tipo, recorrencia, proxima, criado_em) VALUES (?,?,?,?,?)",
                                   (texto.strip(), tipo, recorrencia, proxima.isoformat(), agora.isoformat()))
        return Agendamento(cur.lastrowid, texto.strip(), tipo, recorrencia, proxima)

    def listar(self) -> list[Agendamento]:
        linhas = self.con.execute("SELECT id, texto, tipo, recorrencia, proxima FROM agendamentos WHERE ativo = 1 ORDER BY proxima").fetchall()
        return [Agendamento(i, t, tp, r, datetime.fromisoformat(p)) for i, t, tp, r, p in linhas]

    def cancelar(self, ident: int) -> bool:
        with self.con:
            return self.con.execute("UPDATE agendamentos SET ativo = 0 WHERE id = ? AND ativo = 1", (ident,)).rowcount > 0

    def vencidos(self, agora: datetime | None = None) -> list[Agendamento]:
        """Agendamentos na hora (ou atrasados) — já reprograma os recorrentes e desativa os de uma vez."""
        agora = (agora or datetime.now(BRT)).astimezone(BRT)
        devidos = [a for a in self.listar() if a.proxima <= agora]
        with self.con:
            for a in devidos:
                prox = proxima_execucao(a.recorrencia, agora)
                if prox:
                    self.con.execute("UPDATE agendamentos SET proxima = ? WHERE id = ?", (prox.isoformat(), a.id))
                else:
                    self.con.execute("UPDATE agendamentos SET ativo = 0 WHERE id = ?", (a.id,))
        return devidos

    # ------------------------------------------------------------ limite de mensagens automáticas
    def limite_diario(self) -> int:
        return int(((ler_yaml("persona") or {}).get("mensagens_automaticas") or {}).get("maximo_por_dia", 3))

    def envios_hoje(self, agora: datetime | None = None) -> int:
        dia = (agora or datetime.now(BRT)).astimezone(BRT).strftime("%Y-%m-%d")
        return self.con.execute("SELECT COUNT(*) FROM envios_automaticos WHERE dia = ?", (dia,)).fetchone()[0]

    def pode_enviar(self, agora: datetime | None = None) -> bool:
        return self.envios_hoje(agora) < self.limite_diario()

    def registrar_envio(self, motivo: str, agora: datetime | None = None) -> None:
        agora = (agora or datetime.now(BRT)).astimezone(BRT)
        with self.con:
            self.con.execute("INSERT INTO envios_automaticos VALUES (?,?,?)", (agora.strftime("%Y-%m-%d"), agora.isoformat(), motivo))
