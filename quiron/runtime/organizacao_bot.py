"""Organização no Telegram, direto e sem modelo (rápido, sem gastar cota): /tarefa, /tarefas, /feito, /adiar, /hoje,
/nota, /notas, /meta, /metas, /revisao, /evento. Botões dos lembretes de tarefa: `or:<ação>:<nº>[:<para>]`."""

from __future__ import annotations

import asyncio
import re

from quiron.runtime.academia_bot import Clique, Tela
from quiron.servicos.organizacao import google_agenda, hoje, metas, notas, tarefas

COMANDOS = {"tarefa", "tarefas", "feito", "adiar", "hoje", "nota", "notas", "meta", "metas", "revisao", "evento"}


def botoes_tarefa(t: tarefas.Tarefa) -> list[list[tuple[str, str]]]:
    return [[("✅ Feito", f"or:feito:{t.id}"), ("⏰ +1h", f"or:adiar:{t.id}:1h"), ("📅 Amanhã", f"or:adiar:{t.id}:amanha")]]


class OrganizacaoBot:
    async def comando(self, nome: str, args: str) -> list[Tela]:
        args = (args or "").strip()
        try:
            return await asyncio.to_thread(self._comando, nome, args)
        except (tarefas.TarefaInvalida, metas.MetaInvalida, google_agenda.AgendaIndisponivel, ValueError) as e:
            return [Tela(f"⚠️ {e}")]

    def _comando(self, nome: str, args: str) -> list[Tela]:
        if nome == "tarefa":
            if not args:
                return [Tela("Diga a tarefa: /tarefa amanhã às 10h ligar para o CLI-012 (também entendo “sexta”, “dia 20”, "
                             "“daqui a 2 dias”; sem data, fica na lista).")]
            t = tarefas.criar(args, origem="telegram")
            return [Tela(tarefas.confirmar(t), [[("✅ Feito", f"or:feito:{t.id}"), ("🗑️ Apagar", f"or:apagar:{t.id}")]])]
        if nome == "tarefas":
            filtro = {"hoje": "hoje", "atrasadas": "atrasadas", "feitas": "concluidas", "concluidas": "concluidas"}.get(args.lower(), "pendentes")
            itens = tarefas.listar(filtro)
            if filtro == "concluidas":
                return [Tela("\n".join(t.descrever() for t in itens[:20]) or "Nenhuma concluída ainda.")]
            return [Tela(tarefas.descrever_lista(itens))]
        if nome == "feito":
            nums = [int(n) for n in re.findall(r"\d+", args)]
            if not nums:
                return [Tela("Use /feito <nº> (veja os números em /tarefas).")]
            return [Tela("\n".join("✅ " + tarefas.concluir(n).texto for n in nums))]
        if nome == "adiar":
            m = re.match(r"#?(\d+)\s+(.+)", args)
            if not m:
                return [Tela("Use /adiar <nº> <quando> (ex.: /adiar 3 amanhã às 9h · /adiar 3 2h).")]
            t = tarefas.adiar(int(m[1]), m[2])
            return [Tela("⏰ Adiada: " + tarefas.confirmar(t).removeprefix("📌 Tarefa criada: "))]
        if nome == "hoje":
            return [Tela(hoje.montar_hoje())]
        if nome == "revisao":
            return [Tela(hoje.montar_revisao())]
        if nome == "nota":
            if not args:
                return [Tela("Use /nota <texto> (#tags ajudam: /nota pauta sobre duration #conteudo).")]
            return [Tela("🗒️ Anotado (#" + str(notas.criar(args).id) + ").")]
        if nome == "notas":
            return [Tela(notas.descrever(notas.buscar(args), args))]
        if nome == "meta":
            if m := re.fullmatch(r"#?(\d+)\s*\+\s*(\d+(?:[.,]\d+)?)\s*(.*)", args):
                return [Tela(metas.descrever(metas.registrar(int(m[1]), float(m[2].replace(",", ".")), m[3])))]
            if m := re.fullmatch(r"#?(\d+)\s+(encerrar|apagar|fim)", args, re.I):
                return [Tela("Meta encerrada." if metas.encerrar(int(m[1])) else "Não encontrei essa meta.")]
            if not args:
                return [Tela(metas.descrever_todas())]
            return [Tela("Meta criada:\n" + metas.descrever(metas.criar(args)) + f"\nRegistre o progresso com /meta {metas.listar()[-1].id} +1")]
        if nome == "metas":
            return [Tela(metas.descrever_todas())]
        if nome == "evento":
            if not args:
                return [Tela("Use /evento quinta às 15h reunião com CLI-012 por 1h30 (vai para o seu Google Agenda).")]
            e = google_agenda.evento_de_texto(args)
            return [Tela(f"📅 No Google Agenda: {e.inicio:%d/%m %H:%M}–{e.fim:%H:%M} {e.titulo}")]
        return [Tela("Comando desconhecido.")]

    async def clique(self, dado: str) -> Clique:
        partes = dado.split(":")
        try:
            acao, n = partes[1], int(partes[2])
            if acao == "feito":
                t = await asyncio.to_thread(tarefas.concluir, n)
                return Clique(editar=f"✅ Feito: {t.texto}")
            if acao == "apagar":
                ok = await asyncio.to_thread(tarefas.remover, n)
                return Clique(editar="🗑️ Tarefa apagada." if ok else "Essa tarefa já não existe.")
            if acao == "adiar":
                para = "amanhã" if partes[3] == "amanha" else partes[3]
                t = await asyncio.to_thread(tarefas.adiar, n, para)
                return Clique(editar="⏰ Adiada: " + tarefas.confirmar(t).removeprefix("📌 Tarefa criada: "))
        except (IndexError, ValueError, tarefas.TarefaInvalida) as e:
            return Clique(novas=[Tela(f"⚠️ {e}" if str(e) else "Botão inválido.")])
        return Clique(novas=[Tela("Botão inválido.")])
