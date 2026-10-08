"""Nota diária do Cérebro: `Quíron/Diário/AAAA-MM-DD.md`.

O Quíron escreve só entre os marcadores `<!-- quiron:inicio -->` e `<!-- quiron:fim -->`; o resto da nota (ex.: a seção
"Minhas anotações") é do Rickson e nunca é tocado. A nota só é regravada quando o conteúdo muda (o Obsidian não fica
recarregando à toa). Clientes ficam de fora: tarefas e conversas que citam CLI-XXX entram só como contagem.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

from quiron.servicos.obsidian import indice
from quiron.servicos.obsidian import pasta as P

INICIO, FIM = "<!-- quiron:inicio -->", "<!-- quiron:fim -->"
RE_CLIENTE = re.compile(r"\bCLI-\w+", re.I)
DIAS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


def caminho_rel(dia: date) -> str:
    return f"{P.DIARIO}/{dia:%Y-%m-%d}.md"


def _tarefas(dia: date) -> list[str]:
    from quiron.servicos.organizacao import tarefas

    pendentes = tarefas.listar("pendentes", dia, limite=200)
    feitas = [t for t in tarefas.listar("concluidas", dia, limite=200) if t.concluida_em[:10] == dia.isoformat()]
    linhas, de_clientes = [], 0
    for t in pendentes:
        if not t.data or t.data > dia:
            continue
        if t.cliente or RE_CLIENTE.search(t.texto):
            de_clientes += 1
            continue
        atraso = " _(atrasada)_" if t.data < dia else ""
        linhas.append(f"- [ ] {t.texto}{' às ' + t.hora if t.hora else ''}{atraso}")
    for t in feitas:
        if t.cliente or RE_CLIENTE.search(t.texto):
            de_clientes += 1
            continue
        linhas.append(f"- [x] {t.texto}")
    if de_clientes:
        linhas.append(f"- {de_clientes} tarefa(s) de clientes — veja no /tarefas (clientes não entram no Cérebro)")
    return linhas


def _estudo(dia: date) -> list[str]:
    from quiron.servicos.academia.banco import Banco

    ini, fim = dia.isoformat(), (dia + timedelta(days=1)).isoformat()
    try:
        with Banco()._con() as con:
            linhas = con.execute(
                "SELECT q.cert, q.topico, COUNT(*) n, SUM(r.acertou) a FROM respostas r JOIN questoes q ON q.id = r.questao_id "
                "WHERE r.quando >= ? AND r.quando < ? GROUP BY q.cert, q.topico ORDER BY n DESC", (ini, fim)).fetchall()
            cards = con.execute("SELECT COUNT(*) FROM revisoes_cards WHERE quando >= ? AND quando < ?", (ini, fim)).fetchone()[0]
    except sqlite3.Error:
        return []
    if not linhas and not cards:
        return []
    total, acertos = sum(r[2] for r in linhas), sum(r[3] or 0 for r in linhas)
    saida = []
    if total:
        saida.append(f"- {total} questões, {acertos} acertos ({acertos / total:.0%})")
        saida += [f"  - {r[0]} {r[1]}: {r[3] or 0}/{r[2]}" for r in linhas[:8]]
    if cards:
        saida.append(f"- {cards} flashcard(s) revisado(s)")
    return saida


def _registros(longa, dia: date) -> tuple[list[str], list[str]]:
    """(briefing/resumo do dia, conversas importantes) a partir da memória do Quíron."""
    if longa is None:
        return [], []
    momento = datetime(dia.year, dia.month, dia.day, 12, tzinfo=P_BRT())
    mercado = []
    for r in longa.registros_do_dia(momento, {"proativo", "resposta_comando"}):
        texto = r["conteudo"] or ""
        if re.search(r"briefing|resumo de mercado", texto[:200], re.I) and not RE_CLIENTE.search(texto):
            mercado = [texto.strip()]
            break
    ini = datetime(dia.year, dia.month, dia.day, tzinfo=P_BRT()).astimezone(timezone.utc)
    conversas = []
    try:
        for r in longa.con.execute("SELECT titulo, resumo FROM episodios WHERE fim >= ? AND fim < ? ORDER BY fim",
                                   (ini.isoformat(timespec="seconds"), (ini + timedelta(days=1)).isoformat(timespec="seconds"))):
            if RE_CLIENTE.search(f"{r[0]} {r[1]}"):
                continue
            conversas.append(f"- **{r[0]}** — {r[1]}")
    except sqlite3.Error:
        pass
    return mercado, conversas


def P_BRT():
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/Sao_Paulo")


def _notas_do_dia(dia: date) -> list[str]:
    indice.atualizar()
    ini = datetime(dia.year, dia.month, dia.day).timestamp()
    with indice.conectar() as con:
        linhas = con.execute("SELECT titulo FROM notas WHERE caminho LIKE ? AND mtime >= ? AND mtime < ? ORDER BY mtime",
                             (P.MINHAS + "/%", ini, ini + 86400)).fetchall()
    return [f"- [[{r[0]}]]" for r in linhas]


def _secao(titulo: str, linhas: list[str], vazio: str) -> str:
    return f"## {titulo}\n" + ("\n".join(linhas) if linhas else f"_{vazio}_") + "\n"


def montar_bloco(dia: date, longa=None) -> str:
    partes = []
    for titulo, func, vazio in (("Tarefas", lambda: _tarefas(dia), "nenhuma tarefa para o dia"),
                                ("Estudo", lambda: _estudo(dia), "nada estudado ainda")):
        try:
            partes.append(_secao(titulo, func(), vazio))
        except Exception:  # noqa: BLE001 — uma parte com problema não impede a nota
            logging.exception("diário do Cérebro: falha em %s", titulo)
    mercado, conversas = _registros(longa, dia)
    partes.append(_secao("Mercado", mercado, "o briefing do dia aparece aqui quando for enviado"))
    partes.append(_secao("Conversas importantes", conversas, "nenhuma conversa resumida ainda"))
    partes.append(_secao("Notas do dia", _notas_do_dia(dia), "nenhuma nota sua criada ou mexida hoje"))
    return f"{INICIO}\n" + "\n".join(partes) + f"{FIM}"


def atualizar(dia: date | None = None, longa=None) -> bool:
    """Cria ou atualiza a nota do dia. Devolve True se o arquivo mudou."""
    dia = dia or P.agora().date()
    P.garantir()
    arq = P.caminho(caminho_rel(dia))
    bloco = montar_bloco(dia, longa)
    if arq.exists():
        atual = arq.read_text(encoding="utf-8-sig")
        if INICIO in atual and FIM in atual:
            antes, resto = atual.split(INICIO, 1)
            _, depois = resto.split(FIM, 1)
            novo = antes + bloco + depois
        else:  # o Rickson apagou os marcadores: o bloco volta no fim, sem mexer no que ele escreveu
            novo = atual.rstrip() + "\n\n" + bloco + "\n"
        if novo == atual:
            return False
    else:
        cabeca = P.frontmatter({"data": dia.isoformat(), "tipo": "diário", "tags": ["diario"]})
        novo = (f"{cabeca}# {DIAS[dia.weekday()]}, {dia:%d/%m/%Y}\n\n← [[{dia - timedelta(days=1):%Y-%m-%d}]] · "
                f"[[{dia + timedelta(days=1):%Y-%m-%d}]] →\n\n{bloco}\n\n## Minhas anotações\n\n")
    P.gravar_quiron(caminho_rel(dia), novo)
    return True
