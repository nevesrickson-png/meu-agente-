"""Dossiê de reunião: junta tudo o que o Quíron sabe sobre o cliente (CLI-XXX) antes de uma reunião.

Só fatos guardados e números calculados aqui; quem redige o roteiro da reunião é o agente (skill `reuniao`)."""

from __future__ import annotations

from datetime import date, datetime

from quiron.servicos.analise.relatorio import brl, pct
from quiron.servicos.assessoria import pos_reuniao, vencimentos
from quiron.servicos.planejamento import ficha as fichas
from quiron.servicos.planejamento.ficha import codigo


def _carteira(cod: str) -> list[str]:
    from quiron.servicos.analise.tipos.carteira import _enquadramento
    from quiron.servicos.carteira.modelo import CLASSES, perfis

    achada = vencimentos.ultimas_carteiras().get(cod)
    if not achada:
        return ["Carteira: nenhuma guardada (mande print, planilha ou cole a carteira)."]
    ident, c = achada
    linhas = [f"Carteira {ident} (lida em {datetime.strptime(ident[5:20], '%Y%m%d-%H%M%S'):%d/%m/%Y}): {brl(c.total)} em "
              f"{len(c.posicoes)} posições · perfil {c.perfil or '?'}"]
    pesos = c.pesos_por_classe()
    linhas += [f"- {CLASSES[k]['nome']}: {pct(v * 100, 1)}" for k, v in sorted(pesos.items(), key=lambda x: -x[1]) if v]
    perfil = c.perfil if c.perfil in perfis() else ""
    if perfil:
        fora = [f"{x[0]} {x[5]}" for x in _enquadramento(pesos, perfis()[perfil]["classes"]) if x[5] != "dentro"]
        linhas.append("Fora da faixa do perfil: " + ("; ".join(fora) if fora else "nada"))
    maior = max(c.posicoes, key=lambda p: p.valor)
    if c.total and maior.valor / c.total > 0.25:
        linhas.append(f"Concentração: {maior.nome} = {pct(maior.valor / c.total * 100, 1)} da carteira")
    return linhas


def _tarefas_abertas(cod: str) -> list[str]:
    from quiron.runtime.agendador import Agendador
    from quiron.servicos.lgpd import _cita

    return [a.descrever() for a in Agendador().listar() if _cita(a.texto, cod)]


def _relatorios(cod: str) -> list[str]:
    from quiron.servicos.analise.fila import fila
    from quiron.servicos.lgpd import _cita

    try:
        itens = [t for t in fila().listar(200) if _cita(f"{t.titulo} {t.parametros}", cod)][:5]
    except Exception:  # noqa: BLE001
        return []
    return [f"#{t.id} {t.titulo or t.tipo} ({(t.terminada_em or t.criada_em)[:10]}, {t.situacao})" for t in itens]


def montar(cliente: str, hoje: date | None = None) -> str:
    cod = codigo(cliente)
    hoje = hoje or date.today()
    partes = [f"DOSSIÊ DE REUNIÃO — {cod} — {hoje:%d/%m/%Y}"]
    if fichas.existe(cod):
        f = fichas.carregar(cod)
        partes.append(fichas.descrever(f))
        idade_ficha = (hoje - datetime.fromisoformat(f.atualizado_em).date()).days if f.atualizado_em else None
        if idade_ficha is not None and idade_ficha > 365:
            partes.append(f"⚠️ Ficha sem atualização há {idade_ficha} dias — revisar suitability e dados (Res. CVM 30: "
                          "atualizar o perfil no prazo da política da instituição, no máximo 24 meses).")
    else:
        partes.append("Ficha de planejamento: não existe (dá para montar conversando: /cliente).")
    partes.append("\n".join(_carteira(cod)))
    venc = vencimentos.proximos(120, cod, hoje)
    partes.append("Vencimentos em 120 dias:\n" + ("\n".join(f"- {v.vencimento:%d/%m/%Y}: {v.nome} {brl(v.valor)}" for v in venc)
                                                  if venc else "- nenhum informado"))
    reunioes = pos_reuniao.listar(cod, 3)
    if reunioes:
        bloco = ["Últimas reuniões:"]
        for r in reunioes:
            bloco.append(f"- {datetime.fromisoformat(r.data):%d/%m/%Y}: " + " ".join(r.resumo[:2]))
            bloco += [f"  · decidido: {d}" for d in r.decisoes[:3]]
            bloco += [f"  · atenção: {p}" for p in r.pontos_de_atencao[:3]]
        partes.append("\n".join(bloco))
    else:
        partes.append("Últimas reuniões: nenhuma registrada (depois da reunião, use /pos).")
    tarefas = _tarefas_abertas(cod)
    partes.append("Lembretes/tarefas em aberto:\n" + ("\n".join(f"- {t}" for t in tarefas) if tarefas else "- nenhum"))
    rel = _relatorios(cod)
    if rel:
        partes.append("Relatórios já feitos:\n" + "\n".join(f"- {r}" for r in rel))
    return "\n\n".join(partes)
