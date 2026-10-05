"""Portfólio de análises: o Rickson escolhe relatórios prontos do motor de análise (só os SEM dados de cliente) e o
Quíron monta um PDF com resumo de cada um + o track record do diário de teses.

Privacidade: qualquer relatório que cite CLI-XXX, planejamento/carteira de cliente fica de fora. Rodapé de uso interno
(Resolução CVM 20): mostrar como amostra de trabalho, não distribuir recomendações a terceiros sem CNPI."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.carreira.banco import conectar

TIPOS_DE_CLIENTE = {"planejamento_completo", "aposentadoria", "sucessao", "tributario", "protecao", "empresario", "carteira_diagnostico"}
RE_CLIENTE = re.compile(r"\bCLI-\w+", re.I)


def _cita_cliente(t) -> bool:
    return t.tipo in TIPOS_DE_CLIENTE or bool(RE_CLIENTE.search(f"{t.titulo} {t.resumo} {t.parametros}"))


def candidatos(limite: int = 30) -> list:
    """Relatórios prontos que podem entrar (sem cliente), mais recentes primeiro."""
    from quiron.servicos.analise.fila import fila

    no_port = {i["tarefa"] for i in itens()}
    return [t for t in fila().listar(200, "pronta") if not _cita_cliente(t) and t.id not in no_port][:limite]


def itens() -> list[dict]:
    with conectar() as con:
        return [dict(r) for r in con.execute("SELECT * FROM portfolio ORDER BY adicionado_em")]


def adicionar(tarefa: int, comentario: str = "") -> str:
    from quiron.servicos.analise.fila import fila

    t = fila().obter(tarefa)
    if not t or t.situacao != "pronta":
        raise ValueError(f"relatório #{tarefa} não existe ou não está pronto")
    if _cita_cliente(t):
        raise ValueError(f"#{tarefa} tem dados de cliente — não entra no portfólio")
    with conectar() as con:
        con.execute("INSERT OR REPLACE INTO portfolio VALUES (?,?,?)", (tarefa, comentario[:500], datetime.now().isoformat(timespec="seconds")))
    return f"✅ #{tarefa} {t.titulo} entrou no portfólio."


def remover(tarefa: int) -> bool:
    with conectar() as con:
        return con.execute("DELETE FROM portfolio WHERE tarefa = ?", (tarefa,)).rowcount > 0


def listar_texto() -> str:
    from quiron.servicos.analise.fila import fila

    escolhidos = itens()
    linhas = ["🗂️ Portfólio de análises"]
    if escolhidos:
        for i in escolhidos:
            t = fila().obter(i["tarefa"])
            if t:
                linhas.append(f"✅ #{t.id} {t.titulo} ({(t.terminada_em or '')[:10]})" + (f" — {i['comentario']}" if i["comentario"] else ""))
    else:
        linhas.append("Nenhuma análise escolhida ainda.")
    cand = candidatos(10)
    if cand:
        linhas += ["", "Pode entrar (sem dados de cliente):"] + [f"• #{t.id} {t.titulo} ({(t.terminada_em or '')[:10]})" for t in cand]
        linhas.append("Adicionar: /portfolio add <nº> <por que é uma boa amostra> · PDF: /portfolio pdf")
    return "\n".join(linhas)


def gerar_pdf(autor: str = "Rickson Messias") -> Path:
    """Monta o PDF do portfólio (resumos + track record) em dados/relatorios/portfolio-AAAAMMDD/."""
    from quiron.servicos.analise.fila import fila
    from quiron.servicos.analise.relatorio import Relatorio, Secao, Tabela
    from quiron.servicos.carreira import diario

    secoes = []
    for i in itens():
        t = fila().obter(i["tarefa"])
        if not t or _cita_cliente(t):
            continue
        rel = fila().relatorio(t.id)
        resumo = "\n".join(f"- {r}" for r in (rel.resumo if rel else [])[:6]) or (t.resumo or "")
        texto = (f"**Por que está aqui:** {i['comentario']}\n\n" if i["comentario"] else "") + resumo
        if rel and rel.fontes:
            texto += "\n\nFontes: " + "; ".join(rel.fontes[:4])
        secoes.append(Secao(f"{t.titulo} ({(t.terminada_em or '')[:10]})", texto))
    if not secoes:
        raise ValueError("escolha ao menos uma análise com /portfolio add <nº>")
    est = diario.estatisticas()
    linhas = [["Teses fechadas", est["fechadas"]], ["Teses abertas", est["abertas"]]]
    if "acerto" in est:
        linhas.append(["Acerto (%)", round(est["acerto"], 1)])
    if "brier" in est:
        linhas.append(["Brier (0 = perfeito)", round(est["brier"], 3)])
    fechadas = [t for t in diario.listar("todas") if t.resultado is not None][-10:]
    tab_teses = Tabela("Últimas teses fechadas", ["Tese", "Confiança", "Resultado", "Aprendizado"],
                       [[t.titulo, f"{t.confianca:.0f}%" if t.confianca is not None else "—", t.situacao, t.aprendizado[:120]] for t in fechadas])
    secoes.append(Secao("Track record (diário de teses)", "Teses registradas com premissas, gatilhos de invalidação e confiança; "
                        "revisadas com números na data combinada.", [Tabela("Resumo", ["Indicador", "Valor"], linhas)] + ([tab_teses] if fechadas else [])))
    r = Relatorio(f"Portfólio de análises — {autor}", "portfolio", subtitulo=f"{len(secoes) - 1} análise(s) · {datetime.now():%d/%m/%Y}",
                  resumo=["Amostras de trabalho próprio com dados públicos (CVM, BCB, Tesouro, B3) e números calculados em código.",
                          "Sem dados de clientes."],
                  secoes=secoes, fontes=["Motor de análise do Quíron (relatórios originais disponíveis)"],
                  limitacoes=["Material de estudo; análises de empresas não constituem relatório de análise (exclusivo de CNPI)."])
    pasta = pasta_dados() / "relatorios" / f"portfolio-{datetime.now():%Y%m%d-%H%M%S}"
    return r.salvar(pasta)["pdf"]
