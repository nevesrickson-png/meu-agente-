"""Assessoria no Telegram: `/pos` (pós-reunião por áudio ou texto) e `/treino` (cliente simulado), direto, sem o laço
do agente — o treino precisa de estado (quem está falando é o "cliente") e o pós-reunião espera o áudio seguinte.

Botões: `as:<ação>:...` (cabem nos 64 bytes do Telegram).
"""

from __future__ import annotations

import asyncio
import re

from quiron.nucleo.cerebro import CerebroIndisponivel
from quiron.runtime.academia_bot import Clique, Tela
from quiron.servicos.assessoria import pos_reuniao, treino

COMANDOS = {"pos", "treino"}
RE_CLIENTE = re.compile(r"\bCLI-\w+\b", re.I)
AJUDA_POS = ("Use /pos CLI-012 e depois mande o áudio (ou o texto) do que aconteceu na reunião: o que foi falado, "
             "decidido e combinado, com prazos. Fale o CÓDIGO do cliente, nunca o nome.")


class AssessoriaBot:
    def __init__(self) -> None:
        self.esperando_pos: dict[int, str] = {}  # chat → cliente aguardando o áudio/texto da reunião

    # ------------------------------------------------------------ comandos
    async def comando(self, nome: str, args: str, chat: int) -> list[Tela]:
        args = (args or "").strip()
        if nome == "pos":
            return await self._pos(args, chat)
        return await self._treino(args)

    async def _pos(self, args: str, chat: int) -> list[Tela]:
        if args.lower() in {"cancelar", "cancela"}:
            return [Tela("Ok, pós-reunião cancelado." if self.esperando_pos.pop(chat, None) else "Nada para cancelar.")]
        m = RE_CLIENTE.search(args)
        if not m:
            return [Tela(AJUDA_POS)]
        cliente = m.group(0).upper()
        resto = (args[:m.start()] + args[m.end():]).strip(" :-—")
        if len(resto) >= 15:
            return await self._processar(cliente, resto)
        self.esperando_pos[chat] = cliente
        return [Tela(f"🎙️ Pode mandar o áudio (ou o texto) da reunião com {cliente}. Diga o que foi falado, decidido e "
                     "combinado, com os prazos. /pos cancelar desiste.")]

    async def _processar(self, cliente: str, texto: str) -> list[Tela]:
        try:
            r = await asyncio.to_thread(pos_reuniao.processar, cliente, texto)
        except ValueError as e:
            return [Tela(f"Não registrei: {e}")]
        botoes = []
        if r.ficha:
            botoes.append(("📇 Aplicar na ficha", f"as:ficha:{r.cliente}:{r.id}"))
        if any(t.agendamento for t in r.tarefas):
            botoes.append(("↩️ Desfazer lembretes", f"as:desf:{r.cliente}:{r.id}"))
        return [Tela(r.markdown(), [botoes] if botoes else [])]

    async def _treino(self, args: str) -> list[Tela]:
        a = args.lower()
        try:
            if a in {"opcoes", "opções", "ajuda"}:
                return [Tela(treino.opcoes())]
            if a in {"evolucao", "evolução", "historico", "histórico"}:
                return [Tela(treino.evolucao())]
            if a in {"fim", "encerrar", "feedback", "terminar"}:
                _, texto = await asyncio.to_thread(treino.encerrar)
                return [Tela(texto)]
            if a in {"cancelar", "sair"}:
                s = treino.ativa()
                if not s:
                    return [Tela("Nenhum treino ativo.")]
                s.encerrada_em = "cancelado"
                treino._gravar(s)
                return [Tela(f"Treino #{s.id} cancelado (sem feedback).")]
            _, texto = await asyncio.to_thread(treino.iniciar, args)
            return [Tela(texto)]
        except treino.TreinoInvalido as e:
            return [Tela(str(e))]
        except CerebroIndisponivel:
            return [Tela("Sem IA no momento para interpretar o cliente (cota dos modelos grátis?). Tente daqui a pouco.")]

    # ------------------------------------------------------------ mensagens sem comando
    async def texto_livre(self, chat: int, texto: str) -> list[Tela] | None:
        """Se estiver esperando o pós-reunião ou houver treino ativo, a mensagem é para cá; senão None (vai ao agente)."""
        if chat in self.esperando_pos:
            return await self._processar(self.esperando_pos.pop(chat), texto)
        if treino.ativa() is not None:
            try:
                return [Tela(await asyncio.to_thread(treino.responder, texto))]
            except CerebroIndisponivel:
                return [Tela("O cliente simulado ficou sem IA agora (cota). Repita daqui a pouco ou /treino fim.")]
        return None

    # ------------------------------------------------------------ botões
    async def clique(self, dado: str) -> Clique:
        partes = dado.split(":")
        if len(partes) != 4:
            return Clique(novas=[Tela("Botão inválido.")])
        _, acao, cliente, ident = partes
        try:
            if acao == "ficha":
                return Clique(novas=[Tela(await asyncio.to_thread(pos_reuniao.aplicar_na_ficha, cliente, ident))])
            if acao == "desf":
                from quiron.runtime.agendador import Agendador

                r = pos_reuniao.carregar(cliente, ident)
                ag = Agendador()
                n = sum(ag.cancelar(t.agendamento) for t in r.tarefas if t.agendamento)
                return Clique(novas=[Tela(f"↩️ {n} lembrete(s) da reunião cancelados (o registro da reunião fica guardado).")])
        except ValueError as e:
            return Clique(novas=[Tela(str(e))])
        return Clique(novas=[Tela("Botão inválido.")])
