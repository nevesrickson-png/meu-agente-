"""Canal Telegram do runtime "bot próprio" (python-telegram-bot, long polling: não abre porta nenhuma).

Só responde aos IDs em TELEGRAM_ALLOWED_USER_IDS. Guarda as últimas trocas de cada conversa em `dados/conversas.db`.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any

from quiron.nucleo.config import carregar_config, pasta_dados
from quiron.runtime.agente import Agente
from quiron.runtime.ferramentas_mcp import ConexaoMCP

LIMITE_TELEGRAM = 4000  # o Telegram aceita até 4096 caracteres por mensagem
TURNOS_DE_MEMORIA = 6  # pares pergunta/resposta lembrados por conversa


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


class Memoria:
    def __init__(self):
        caminho = pasta_dados() / "conversas.db"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho)
        self.con.execute("CREATE TABLE IF NOT EXISTS conversa (chat INTEGER PRIMARY KEY, historico TEXT)")

    def ler(self, chat: int) -> list[dict[str, Any]]:
        linha = self.con.execute("SELECT historico FROM conversa WHERE chat = ?", (chat,)).fetchone()
        return json.loads(linha[0]) if linha else []

    def guardar(self, chat: int, pergunta: str, resposta: str) -> None:
        hist = self.ler(chat) + [{"role": "user", "content": pergunta}, {"role": "assistant", "content": resposta}]
        with self.con:
            self.con.execute("INSERT OR REPLACE INTO conversa VALUES (?, ?)", (chat, json.dumps(hist[-2 * TURNOS_DE_MEMORIA:], ensure_ascii=False)))

    def apagar(self, chat: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM conversa WHERE chat = ?", (chat,))


class BotQuiron:
    """Lógica do bot separada da biblioteca do Telegram (facilita testar)."""

    def __init__(self, agente: Agente, memoria: Memoria, permitidos: set[int]):
        self.agente, self.memoria, self.permitidos = agente, memoria, permitidos

    async def tratar(self, usuario: int, chat: int, texto: str) -> list[str]:
        if usuario not in self.permitidos:
            logging.warning("mensagem ignorada de usuário não autorizado: %s", usuario)
            return []  # silêncio: não revela que o bot existe
        texto = (texto or "").strip()
        if texto in {"/start", "/ajuda"}:
            return ["Quíron no ar. Pergunte livremente ou use: /briefing, /noticia <tema>, /estudar <tema>, /novo (esquece a conversa)."]
        if texto == "/novo":
            self.memoria.apagar(chat)
            return ["Conversa reiniciada."]
        if texto.startswith("/"):
            comando, _, resto = texto[1:].partition(" ")
            texto = {"briefing": "Faça meu briefing.", "noticia": f"O que está saindo sobre {resto}?",
                     "estudar": f"Me ensine sobre {resto} usando a biblioteca.", "pilula": "Minha pílula de estudo do dia."}.get(comando, texto)
        reg = await self.agente.responder(texto, self.memoria.ler(chat))
        if not reg.erro:
            self.memoria.guardar(chat, texto, reg.resposta)
        return dividir(reg.resposta or "(sem resposta)")


async def _rodar() -> None:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.ext import Application, ContextTypes, MessageHandler, filters

    carregar_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").split(" #")[0].strip()
    permitidos = ids_permitidos()
    if not token or not permitidos:
        raise SystemExit("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USER_IDS no .env (veja o LEIA-ME).")

    async with ConexaoMCP() as conexao:
        if conexao.falhas:
            logging.warning("servidores MCP com problema: %s", conexao.falhas)
        bot = BotQuiron(Agente(conexao), Memoria(), permitidos)

        async def ao_receber(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.effective_message
            if not msg or not update.effective_user:
                return
            await contexto.bot.send_chat_action(msg.chat_id, ChatAction.TYPING)
            for parte in await bot.tratar(update.effective_user.id, msg.chat_id, msg.text or ""):
                await msg.reply_text(parte, disable_web_page_preview=True)

        app = Application.builder().token(token).build()
        app.add_handler(MessageHandler(filters.TEXT, ao_receber))
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            print(f"Quíron no Telegram (bot próprio). Ferramentas: {len(conexao.ferramentas)}. Ctrl+C para parar.")
            import asyncio

            await asyncio.Event().wait()


def main() -> None:
    """`uv run quiron-telegram` — liga o bot próprio no Telegram."""
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(_rodar())
    except KeyboardInterrupt:
        pass
