"""Canal Telegram do agente do Quíron (python-telegram-bot, long polling: não abre porta nenhuma).

- Só responde aos IDs em TELEGRAM_ALLOWED_USER_IDS (estranhos: silêncio).
- Comandos de barra vêm de `agente/comandos/*.md` (+ /novo, /agenda, /memoria, /ajuda).
- Ações sensíveis chegam com botões ✅/❌ (permissões em config/agente.yaml).
- Laços em segundo plano: agenda (lembretes e tarefas na hora) e batimento proativo.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

from quiron.nucleo.config import carregar_config
from quiron.runtime import batimento
from quiron.runtime.agendador import BRT
from quiron.runtime.agente import Agente
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.workspace import carregar_comandos

LIMITE_TELEGRAM = 4000  # o Telegram aceita até 4096 caracteres por mensagem


def ids_permitidos() -> set[int]:
    carregar_config()
    bruto = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(" #")[0]
    return {int(x) for x in bruto.replace(";", ",").split(",") if x.strip().isdigit()}


def dividir(texto: str, limite: int = LIMITE_TELEGRAM) -> list[str]:
    """Quebra respostas longas em pedaços, de preferência em fim de parágrafo/linha."""
    partes = []
    while len(texto) > limite:
        corte = texto.rfind("\n\n", 0, limite)
        corte = corte if corte > limite // 2 else texto.rfind("\n", 0, limite)
        corte = corte if corte > limite // 2 else limite
        partes.append(texto[:corte].rstrip())
        texto = texto[corte:].lstrip()
    return partes + ([texto] if texto else [])


@dataclass
class Saida:
    """Uma mensagem a enviar; `botoes` = [(rótulo, dado do botão)]."""

    texto: str
    botoes: list[tuple[str, str]] = field(default_factory=list)


class BotQuiron:
    """Lógica do bot separada da biblioteca do Telegram (facilita testar)."""

    def __init__(self, agente: Agente, permitidos: set[int]):
        self.agente, self.permitidos = agente, permitidos
        self.comandos = carregar_comandos()

    def autorizado(self, usuario: int) -> bool:
        if usuario not in self.permitidos:
            logging.warning("mensagem ignorada de usuário não autorizado: %s", usuario)
            return False
        return True

    def ajuda(self) -> str:
        linhas = ["Quíron no ar. Pergunte livremente, mande áudio (em breve) ou use:"]
        linhas += [f"/{c.nome} — {c.descricao}" for c in self.comandos.values()]
        linhas += ["/agenda — lembretes e rotinas", "/memoria — o que eu sei sobre você", "/novo — começar a conversa do zero"]
        return "\n".join(linhas)

    async def tratar(self, usuario: int, chat: int, texto: str) -> list[Saida]:
        if not self.autorizado(usuario):
            return []  # silêncio: não revela que o bot existe
        texto = (texto or "").strip()
        if texto in {"/start", "/ajuda", "/help"}:
            return [Saida(self.ajuda())]
        if texto == "/novo":
            self.agente.memoria.reiniciar(chat)
            return [Saida("Conversa reiniciada (o histórico continua pesquisável).")]
        if texto == "/agenda":
            itens = self.agente.agendador.listar()
            return [Saida("\n".join(a.descrever() for a in itens) if itens else "Nada agendado. Ex.: “todo dia útil às 7h30 me manda o briefing”.")]
        if texto == "/memoria":
            fatos = self.agente.workspace.fatos()
            return [Saida("O que eu sei sobre você:\n" + "\n".join(f"• {f}" for f in fatos) if fatos else "Ainda não guardei nada. Diga “lembre que…”.")]
        if texto.startswith("/"):
            nome, _, args = texto[1:].partition(" ")
            cmd = self.comandos.get(nome.split("@")[0].lower())
            if not cmd:
                return [Saida(f"Comando desconhecido. {self.ajuda()}")]
            texto = cmd.montar(args)
        reg = await self.agente.responder(texto, chat=chat)
        saidas = [Saida(p) for p in dividir(reg.resposta or "(sem resposta)")]
        for p in reg.pendencias:
            saidas.append(Saida(f"🔐 Aprovação #{p.id}: {p.resumo}", [("✅ Aprovar", f"aprovar:{p.id}"), ("❌ Negar", f"negar:{p.id}")]))
        return saidas

    async def decidir(self, usuario: int, dado: str) -> str:
        if not self.autorizado(usuario):
            return ""
        acao, _, ident = dado.partition(":")
        if not ident.isdigit():
            return "Botão inválido."
        p = self.agente.aprovacoes.decidir(int(ident), acao == "aprovar")
        if not p:
            return "Esse pedido já foi decidido ou não existe."
        if acao != "aprovar":
            return f"❌ Negado: {p.resumo}"
        resultado = await self.agente.executar_aprovada(p)
        return f"✅ Aprovado e feito: {p.resumo}\n{resultado[:3000]}"

    async def agenda_vencida(self, agora: datetime | None = None) -> list[str]:
        """Lembretes/tarefas na hora. Lembretes pedidos pelo Rickson sempre saem; contam no limite diário."""
        saidas = []
        for a in self.agente.agendador.vencidos(agora):
            if a.tipo == "lembrete":
                texto = f"⏰ Lembrete: {a.texto}"
            else:
                reg = await self.agente.responder(a.texto)
                texto = reg.resposta
            self.agente.agendador.registrar_envio(f"agenda #{a.id}", agora)
            self.agente.workspace.anotar_diario(f"Agenda #{a.id} enviada: {a.texto[:120]}", agora)
            saidas.append(texto)
        return saidas


async def _rodar() -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.constants import ChatAction
    from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

    carregar_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").split(" #")[0].strip()
    permitidos = ids_permitidos()
    if not token or not permitidos:
        raise SystemExit("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_IDS no .env (veja o LEIA-ME).")
    dono = sorted(permitidos)[0]  # mensagens proativas vão para o primeiro ID da lista

    async with ConexaoMCP() as conexao:
        if conexao.falhas:
            logging.warning("servidores MCP com problema: %s", conexao.falhas)
        bot = BotQuiron(Agente(conexao), permitidos)
        app = Application.builder().token(token).build()

        async def enviar(chat: int, s: Saida) -> None:
            teclado = InlineKeyboardMarkup([[InlineKeyboardButton(r, callback_data=d) for r, d in s.botoes]]) if s.botoes else None
            await app.bot.send_message(chat, s.texto, reply_markup=teclado, disable_web_page_preview=True)

        async def ao_receber(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.effective_message
            if not msg or not update.effective_user:
                return
            await contexto.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
            for s in await bot.tratar(update.effective_user.id, msg.chat_id, msg.text or ""):
                await enviar(msg.chat_id, s)

        async def ao_clicar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            q = update.callback_query
            await q.answer()
            texto = await bot.decidir(q.from_user.id, q.data or "")
            if texto:
                await q.edit_message_reply_markup(None)
                for parte in dividir(texto):
                    await app.bot.send_message(q.message.chat_id, parte)

        async def laco_agenda() -> None:
            while True:
                try:
                    for texto in await bot.agenda_vencida():
                        for parte in dividir(texto):
                            await app.bot.send_message(dono, parte)
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha no laço da agenda")
                await asyncio.sleep(30)

        async def laco_batimento() -> None:
            while True:
                cfg = batimento.ConfigBatimento.ler()
                await asyncio.sleep(max(15, cfg.intervalo_min) * 60)
                try:
                    texto = await batimento.bater(bot.agente, datetime.now(BRT))
                    if texto:
                        for parte in dividir(texto):
                            await app.bot.send_message(dono, parte)
                except Exception:  # noqa: BLE001
                    logging.exception("falha no batimento")

        app.add_handler(MessageHandler(filters.TEXT, ao_receber))
        app.add_handler(CallbackQueryHandler(ao_clicar))
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            tarefas = [asyncio.create_task(laco_agenda()), asyncio.create_task(laco_batimento())]
            print(f"Quíron no Telegram. Ferramentas MCP: {len(conexao.ferramentas)}. Ctrl+C para parar.")
            try:
                await asyncio.Event().wait()
            finally:
                for t in tarefas:
                    t.cancel()


def main() -> None:
    """`uv run quiron-telegram` — liga o agente do Quíron no Telegram."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(_rodar())
    except KeyboardInterrupt:
        pass
