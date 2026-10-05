"""/hoje e /revisao: o dia e a semana do Rickson, montados em Python (sem modelo) a partir do que está guardado.

Hoje: Google Agenda, tarefas (atrasadas e de hoje), lembretes do dia, vencimentos de clientes em 7 dias e metas.
Revisão semanal: o que foi feito (tarefas, reuniões, treinos, estudo, notas), metas, o que ficou para trás e a
próxima semana (agenda + tarefas), com 3 perguntas para pensar."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

from quiron.nucleo.config import pasta_dados
from quiron.servicos.organizacao import google_agenda, metas, notas, tarefas

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _agora() -> datetime:
    from quiron.runtime.agendador import BRT

    return datetime.now(BRT)


def _agenda(dia_ini: date, dias: int = 1) -> list[str]:
    if not google_agenda.configurado():
        return [f"(Google Agenda não conectado — {google_agenda.como_configurar()})"] if google_agenda.arquivo_cliente().exists() else []
    from quiron.runtime.agendador import BRT

    try:
        ini = datetime.combine(dia_ini, datetime.min.time(), tzinfo=BRT)
        itens = google_agenda.eventos(ini, ini + timedelta(days=dias))
    except google_agenda.AgendaIndisponivel as e:
        return [f"⚠️ {e}"]
    if dias == 1:
        return [e.descrever() for e in itens] or ["Agenda livre."]
    linhas = []
    for e in itens:
        d = e.inicio if isinstance(e.inicio, date) and not isinstance(e.inicio, datetime) else e.inicio.date()
        linhas.append(f"{DIAS[d.weekday()][:3]} {d:%d/%m} " + e.descrever().removeprefix("📅 "))
    return linhas or ["Agenda livre."]


def _lembretes_do_dia(dia: date) -> list[str]:
    from quiron.runtime.agendador import Agendador

    return [f"⏰ {a.proxima:%H:%M} {a.texto}" for a in Agendador().listar()
            if a.proxima.date() == dia and not a.texto.startswith("[T")]  # os de tarefa já aparecem nas tarefas


def montar_hoje(agora: datetime | None = None) -> str:
    agora = agora or _agora()
    hoje = agora.date()
    partes = [f"☀️ Hoje — {DIAS[hoje.weekday()]}, {hoje:%d/%m/%Y}"]
    agenda = _agenda(hoje)
    if agenda:
        partes.append("Agenda:\n" + "\n".join(agenda))
    pend = tarefas.listar("pendentes", hoje)
    atrasadas = [t for t in pend if t.atrasada(hoje)]
    de_hoje = [t for t in pend if t.data == hoje]
    if atrasadas:
        partes.append("🔴 Atrasadas:\n" + "\n".join(t.descrever(hoje) for t in atrasadas))
    partes.append("📍 Tarefas de hoje:\n" + ("\n".join(t.descrever(hoje) for t in de_hoje) if de_hoje else "nenhuma com prazo hoje"))
    sem_data = [t for t in pend if not t.data]
    if sem_data:
        partes.append(f"📥 {len(sem_data)} sem data (ex.: {sem_data[0].texto})")
    lembretes = _lembretes_do_dia(hoje)
    if lembretes:
        partes.append("Lembretes:\n" + "\n".join(lembretes))
    try:
        from quiron.servicos.assessoria import vencimentos

        venc = vencimentos.proximos(7, hoje=hoje)
        if venc:
            partes.append("💼 Vencimentos de clientes em 7 dias:\n" + "\n".join(
                f"{v.vencimento:%d/%m} {v.cliente}: {v.nome}" for v in venc))
    except Exception:  # noqa: BLE001 — sem carteiras guardadas
        pass
    ms = metas.listar()
    if ms:
        partes.append("Metas:\n" + "\n".join(metas.descrever(m, hoje) for m in ms))
    return "\n\n".join(partes)


# ---------------------------------------------------------------- revisão semanal
def _contar_reunioes(ini: date, fim: date) -> int:
    n = 0
    for arq in (pasta_dados() / "reunioes").glob("CLI-*/*.json"):
        try:
            d = datetime.fromisoformat(json.loads(arq.read_text(encoding="utf-8"))["data"]).date()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        n += ini <= d <= fim
    return n


def _sql(banco: str, consulta: str, params: tuple) -> list[tuple]:
    caminho = pasta_dados() / banco
    if not caminho.exists():
        return []
    con = sqlite3.connect(caminho)
    try:
        return con.execute(consulta, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()


def montar_revisao(agora: datetime | None = None) -> str:
    agora = agora or _agora()
    hoje = agora.date()
    ini = hoje - timedelta(days=hoje.weekday())  # segunda desta semana
    fim = ini + timedelta(days=6)
    a, b = ini.isoformat(), (fim + timedelta(days=1)).isoformat()
    partes = [f"🗓️ Revisão da semana — {ini:%d/%m} a {fim:%d/%m}"]

    feitas = [t for t in tarefas.listar("concluidas", hoje, 500) if a <= t.concluida_em[:10] < b]
    pend = tarefas.listar("pendentes", hoje, 500)
    atrasadas = [t for t in pend if t.atrasada(hoje)]
    criadas = _sql("organizacao.db", "SELECT COUNT(*) FROM tarefas WHERE substr(criada_em,1,10) >= ? AND substr(criada_em,1,10) < ?", (a, b))
    linhas = [f"✅ {len(feitas)} tarefa(s) concluída(s) · {criadas[0][0] if criadas else 0} criada(s) · {len(atrasadas)} atrasada(s)"]
    linhas += [f"   · {t.texto}" for t in feitas[:8]]
    reun = _contar_reunioes(ini, fim)
    treinos = _sql("treino.db", "SELECT COUNT(*), AVG(json_extract(feedback, '$.nota_final')) FROM sessoes "
                                "WHERE substr(iniciada_em,1,10) >= ? AND substr(iniciada_em,1,10) < ? AND feedback IS NOT NULL", (a, b))
    estudo = _sql("academia.db", "SELECT COUNT(*), SUM(acertou) FROM respostas WHERE substr(quando,1,10) >= ? AND substr(quando,1,10) < ?", (a, b))
    n_notas = len([n for n in notas.buscar("", 500) if a <= n.criada_em[:10] < b])
    linhas.append(f"🤝 {reun} reunião(ões) registrada(s) no /pos")
    if treinos and treinos[0][0]:
        media = f", nota média {treinos[0][1]:.1f}".replace(".", ",") if treinos[0][1] is not None else ""
        linhas.append(f"🎭 {treinos[0][0]} treino(s){media}")
    if estudo and estudo[0][0]:
        linhas.append(f"🎓 {estudo[0][0]} questão(ões) na Academia, {estudo[0][1] / estudo[0][0] * 100:.0f}% de acerto")
    else:
        linhas.append("🎓 Nenhuma questão na Academia esta semana")
    linhas.append(f"🗒️ {n_notas} nota(s)")
    partes.append("O que foi feito:\n" + "\n".join(linhas))

    ms = metas.listar()
    if ms:
        partes.append("Metas:\n" + "\n".join(metas.descrever(m, hoje) for m in ms))
    if atrasadas:
        partes.append("Ficou para trás:\n" + "\n".join(t.descrever(hoje) for t in atrasadas[:10]))

    try:
        from quiron.servicos.carreira import diario

        devidas = [t for t in diario.listar("aberta") if t.revisar_em and t.revisar_em <= (fim + timedelta(days=7)).isoformat()]
        if devidas:
            partes.append("📓 Teses para revisar:\n" + "\n".join(t.resumo() for t in devidas) + "\n/diario revisar para os números")
    except Exception:  # noqa: BLE001
        pass

    prox_ini = fim + timedelta(days=1)
    prox = [t for t in pend if t.data and prox_ini <= t.data <= prox_ini + timedelta(days=6)]
    bloco = _agenda(prox_ini, 7)
    bloco += [t.descrever(hoje) for t in prox]
    try:
        from quiron.servicos.assessoria import vencimentos

        bloco += [f"💼 {v.vencimento:%d/%m} vence {v.nome} ({v.cliente})" for v in vencimentos.proximos(14, hoje=hoje)
                  if prox_ini <= v.vencimento <= prox_ini + timedelta(days=6)]
    except Exception:  # noqa: BLE001
        pass
    partes.append(f"Próxima semana ({prox_ini:%d/%m}–{prox_ini + timedelta(days=6):%d/%m}):\n" + ("\n".join(bloco) if bloco else "nada marcado ainda"))
    partes.append("Para pensar (responda aqui se quiser que eu guarde):\n1. O que mais avançou seus objetivos esta semana?\n"
                  "2. O que você vai deixar de fazer na próxima?\n3. Qual é a UMA prioridade da semana que vem?")
    return "\n\n".join(partes)
