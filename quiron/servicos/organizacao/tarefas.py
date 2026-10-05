"""Tarefas do Rickson por texto ou áudio: "amanhã às 10h ligar para o CLI-012" → tarefa com prazo e lembrete.

- Data e hora são tiradas da frase em Python (`assessoria/datas.extrair`), nunca pelo modelo.
- Com hora: lembrete na hora. Só com data: lembrete às 8h daquele dia (`HORA_SEM_HORARIO`). Sem data: fica na lista.
- O lembrete é um agendamento do `Agendador` (o mesmo do Telegram); quando chega, vem com botões Feito / +1h / Amanhã.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from quiron.servicos.assessoria import datas
from quiron.servicos.organizacao.banco import conectar

HORA_SEM_HORARIO = (8, 0)
RE_CLIENTE = re.compile(r"\bCLI-\w+\b", re.I)


class TarefaInvalida(ValueError):
    pass


@dataclass
class Tarefa:
    id: int
    texto: str
    cliente: str = ""
    prazo: str = ""  # AAAA-MM-DD
    hora: str = ""  # HH:MM
    lembrete: int | None = None
    evento: str = ""
    origem: str = ""
    criada_em: str = ""
    concluida_em: str = ""

    @property
    def data(self) -> date | None:
        return date.fromisoformat(self.prazo) if self.prazo else None

    def atrasada(self, hoje: date) -> bool:
        return not self.concluida_em and self.data is not None and self.data < hoje

    def descrever(self, hoje: date | None = None) -> str:
        hoje = hoje or _agora().date()
        if self.concluida_em:
            marca = "✅"
        elif self.atrasada(hoje):
            marca = "🔴"
        else:
            marca = "☐"
        quando = ""
        if self.data:
            rotulo = {hoje: "hoje", hoje + timedelta(days=1): "amanhã"}.get(self.data, self.data.strftime("%d/%m"))
            quando = f" — {rotulo}" + (f" {self.hora}" if self.hora else "")
        return f"{marca} #{self.id} {self.texto}{quando}"


def _agora() -> datetime:
    from quiron.runtime.agendador import BRT

    return datetime.now(BRT)


def _de_linha(r) -> Tarefa:
    return Tarefa(**{k: r[k] for k in r.keys()})


def obter(ident: int) -> Tarefa:
    with conectar() as con:
        r = con.execute("SELECT * FROM tarefas WHERE id = ?", (ident,)).fetchone()
    if not r:
        raise TarefaInvalida(f"tarefa #{ident} não existe")
    return _de_linha(r)


def _agendar(t: Tarefa, agora: datetime) -> int | None:
    """Cria (ou recria) o lembrete da tarefa. Devolve o id do agendamento, ou None se não couber."""
    from quiron.runtime.agendador import BRT, Agendador

    if not t.data:
        return None
    h, m = map(int, t.hora.split(":")) if t.hora else HORA_SEM_HORARIO
    quando = datetime.combine(t.data, time(h, m), tzinfo=BRT)
    if quando <= agora:
        return None  # já passou (ex.: "hoje" sem hora depois das 8h): aparece no /hoje
    return Agendador().criar(f"[T{t.id}] {t.texto}", "lembrete", "uma vez", quando, agora=agora).id


def criar(texto: str, agora: datetime | None = None, origem: str = "") -> Tarefa:
    agora = agora or _agora()
    limpo, d, h = datas.extrair(texto or "", agora.date())
    if len(limpo) < 2:
        raise TarefaInvalida("diga o que é a tarefa (ex.: “amanhã às 10h ligar para o CLI-012”)")
    if h and not d:  # só a hora: hoje se ainda não passou, senão amanhã
        d = agora.date() if (h[0], h[1]) > (agora.hour, agora.minute) else agora.date() + timedelta(days=1)
    cliente = (RE_CLIENTE.search(limpo) or [""])[0].upper()
    with conectar() as con:
        cur = con.execute("INSERT INTO tarefas(texto, cliente, prazo, hora, origem, criada_em) VALUES (?,?,?,?,?,?)",
                          (limpo[:300], cliente, d.isoformat() if d else "", f"{h[0]:02d}:{h[1]:02d}" if h else "", origem,
                           agora.isoformat(timespec="seconds")))
    t = obter(cur.lastrowid)
    t.lembrete = _agendar(t, agora)
    with conectar() as con:
        con.execute("UPDATE tarefas SET lembrete = ? WHERE id = ?", (t.lembrete, t.id))
    return t


def confirmar(t: Tarefa) -> str:
    """Frase de confirmação para o Rickson."""
    if t.lembrete:
        from quiron.runtime.agendador import Agendador

        ag = next((a for a in Agendador().listar() if a.id == t.lembrete), None)
        quando = f" · lembrete {ag.proxima:%d/%m às %H:%M}" if ag else ""
    elif t.data:
        quando = " · sem lembrete (horário já passou; aparece no /hoje)"
    else:
        quando = " · sem data (fica na lista /tarefas)"
    return f"📌 Tarefa criada: {t.descrever()}{quando}"


def listar(filtro: str = "pendentes", hoje: date | None = None, limite: int = 50) -> list[Tarefa]:
    hoje = hoje or _agora().date()
    with conectar() as con:
        if filtro == "concluidas":
            linhas = con.execute("SELECT * FROM tarefas WHERE concluida_em != '' ORDER BY concluida_em DESC LIMIT ?", (limite,))
        else:
            linhas = con.execute("SELECT * FROM tarefas WHERE concluida_em = '' ORDER BY prazo = '', prazo, hora = '', hora, id LIMIT ?", (limite,))
        itens = [_de_linha(r) for r in linhas]
    if filtro == "hoje":
        return [t for t in itens if t.data and t.data <= hoje]
    if filtro == "atrasadas":
        return [t for t in itens if t.atrasada(hoje)]
    return itens


def _cancelar_lembrete(t: Tarefa) -> None:
    if t.lembrete:
        from quiron.runtime.agendador import Agendador

        Agendador().cancelar(t.lembrete)


def concluir(ident: int, agora: datetime | None = None) -> Tarefa:
    t = obter(ident)
    if t.concluida_em:
        return t
    agora = agora or _agora()
    _cancelar_lembrete(t)
    with conectar() as con:
        con.execute("UPDATE tarefas SET concluida_em = ? WHERE id = ?", (agora.isoformat(timespec="seconds"), ident))
    return obter(ident)


def adiar(ident: int, para: str, agora: datetime | None = None) -> Tarefa:
    """Adia: '1h', '30min' (a partir de agora) ou uma expressão de data ('amanhã', 'sexta', 'dia 20 às 15h')."""
    agora = agora or _agora()
    t = obter(ident)
    if t.concluida_em:
        raise TarefaInvalida(f"a tarefa #{ident} já foi concluída")
    m = re.fullmatch(r"\s*(\d+)\s*(h|min)\s*", para or "")
    if m:
        novo = (agora + timedelta(hours=int(m[1])) if m[2] == "h" else agora + timedelta(minutes=int(m[1]))).replace(second=0, microsecond=0)
        d, h = novo.date(), (novo.hour, novo.minute)
    else:
        _, d, h = datas.extrair(para or "", agora.date())
        if not d and not h:
            raise TarefaInvalida(f"não entendi para quando: “{para}”")
        d = d or agora.date()
        h = h or ((tuple(map(int, t.hora.split(":"))) if t.hora else None))
    _cancelar_lembrete(t)
    t.prazo, t.hora = d.isoformat(), f"{h[0]:02d}:{h[1]:02d}" if h else ""
    t.lembrete = _agendar(t, agora)
    with conectar() as con:
        con.execute("UPDATE tarefas SET prazo = ?, hora = ?, lembrete = ? WHERE id = ?", (t.prazo, t.hora, t.lembrete, ident))
    return t


def remover(ident: int) -> bool:
    try:
        t = obter(ident)
    except TarefaInvalida:
        return False
    _cancelar_lembrete(t)
    with conectar() as con:
        con.execute("DELETE FROM tarefas WHERE id = ?", (ident,))
    return True


def por_lembrete(agendamento: int) -> Tarefa | None:
    with conectar() as con:
        r = con.execute("SELECT * FROM tarefas WHERE lembrete = ?", (agendamento,)).fetchone()
    return _de_linha(r) if r else None


def descrever_lista(itens: list[Tarefa], hoje: date | None = None) -> str:
    hoje = hoje or _agora().date()
    if not itens:
        return "Nenhuma tarefa pendente. Crie com /tarefa (ex.: /tarefa amanhã às 10h ligar para o CLI-012)."
    grupos = {"🔴 Atrasadas": [t for t in itens if t.atrasada(hoje)], "📍 Hoje": [t for t in itens if t.data == hoje],
              "🗓️ Próximas": [t for t in itens if t.data and t.data > hoje], "📥 Sem data": [t for t in itens if not t.data]}
    partes = [f"{titulo}\n" + "\n".join(t.descrever(hoje) for t in lista) for titulo, lista in grupos.items() if lista]
    return "\n\n".join(partes) + "\n\n/feito <nº> conclui · /adiar <nº> amanhã"
