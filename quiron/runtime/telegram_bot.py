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
from quiron.runtime.academia_bot import COMANDOS as COMANDOS_ACADEMIA
from quiron.runtime.academia_bot import AcademiaBot, Tela
from quiron.runtime.agendador import BRT
from quiron.runtime.agente import Agente
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.workspace import carregar_comandos

LIMITE_TELEGRAM = 4000  # o Telegram aceita até 4096 caracteres por mensagem


def ids_permitidos() -> set[int]:
    carregar_config()
    bruto = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(" #")[0]
    itens = [x.strip() for x in bruto.replace(";", ",").split(",") if x.strip()]
    invalidos = [x for x in itens if not x.isdigit()]
    if invalidos:
        logging.warning("TELEGRAM_ALLOWED_USER_IDS tem %s, mas precisa ser o NÚMERO do seu ID (ex.: 7592218870), "
                        "não o @usuário. Descubra o número falando com @userinfobot no Telegram.", ", ".join(invalidos))
    return {int(x) for x in itens if x.isdigit()}


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
    linhas: list[list[tuple[str, str]]] = field(default_factory=list)  # várias linhas de botões (Academia)

    def teclado(self) -> list[list[tuple[str, str]]]:
        return self.linhas or ([self.botoes] if self.botoes else [])


class BotQuiron:
    """Lógica do bot separada da biblioteca do Telegram (facilita testar)."""

    def __init__(self, agente: Agente, permitidos: set[int]):
        self.agente, self.permitidos = agente, permitidos
        self.comandos = carregar_comandos()
        self.academia = AcademiaBot()

    def autorizado(self, usuario: int) -> bool:
        if usuario not in self.permitidos:
            logging.warning("mensagem ignorada de usuário não autorizado: %s", usuario)
            return False
        return True

    def ajuda(self) -> str:
        linhas = ["Quíron no ar. Pergunte livremente, mande áudio ou use:"]
        linhas += [f"/{c.nome} — {c.descricao}" for c in self.comandos.values()]
        linhas += ["", "🎓 Academia (20 campos + certificações): /academia painel · /area [nome] · "
                   "/questoes [área] [módulo|tema] · /simulado [área] [mini|40|completo] · /flashcards · /diagnostico · "
                   "/plano [horas]", ""]
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
        skills: list[str] = []
        if texto.startswith("/"):
            nome, _, args = texto[1:].partition(" ")
            if nome.split("@")[0].lower() in COMANDOS_ACADEMIA:
                telas = await self.academia.comando(nome.split("@")[0].lower(), args)
                return [self._saida(t) for t in telas]
            cmd = self.comandos.get(nome.split("@")[0].lower())
            if not cmd:
                return [Saida(f"Comando desconhecido. {self.ajuda()}")]
            texto = cmd.montar(args)
            skills = [cmd.skill] if cmd.skill else []
        reg = await self.agente.responder(texto, chat=chat, skills=skills)
        saidas = [Saida(p) for p in dividir(reg.resposta or "(sem resposta)")]
        for p in reg.pendencias:
            saidas.append(Saida(f"🔐 Aprovação #{p.id}: {p.resumo}", [("✅ Aprovar", f"aprovar:{p.id}"), ("❌ Negar", f"negar:{p.id}")]))
        return saidas

    @staticmethod
    def _saida(t: Tela) -> Saida:
        return Saida(t.texto[:LIMITE_TELEGRAM], linhas=t.linhas)

    async def clicar_academia(self, usuario: int, dado: str) -> tuple[str | None, list[Saida]]:
        if not self.autorizado(usuario):
            return None, []
        c = await self.academia.clique(dado)
        return c.editar, [self._saida(t) for t in c.novas]

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

    def skills_para(self, texto: str) -> list[str]:
        """Pedido igual ao de um comando (ex.: 'Faça meu briefing.') já leva a skill do comando."""
        return [c.skill for c in self.comandos.values() if c.skill and c.modelo.strip() == texto.strip()]

    async def tratar_audio(self, usuario: int, chat: int, conteudo: bytes, nome: str = "voz.ogg") -> list[Saida]:
        if not self.autorizado(usuario):
            return []
        from quiron.runtime import audio

        try:
            texto = await asyncio.to_thread(audio.transcrever, conteudo, nome)
        except audio.AudioIndisponivel as e:
            return [Saida(f"🎙️ {e}")]
        return [Saida(f"🎙️ “{texto}”"), *await self.tratar(usuario, chat, texto)]

    async def tratar_arquivo(self, usuario: int, chat: int, conteudo: bytes, nome: str, legenda: str = "",
                             imagem: bool = False) -> list[Saida]:
        """Carteira por print (OCR local) ou planilha (xlsx/csv): lê aqui, guarda (CART-…) e passa só o resumo ao agente."""
        if not self.autorizado(usuario):
            return []
        from quiron.servicos.carteira import arquivo, leitura

        if not imagem and not nome.lower().endswith((".xlsx", ".xlsm", ".csv")):
            return [Saida("Por enquanto leio carteira em print (foto), planilha .xlsx ou .csv. PDF de livro vai pelo Acervo do Terminal.")]
        try:
            if imagem:
                c = await asyncio.to_thread(leitura.ler_print, conteudo)
            else:
                c = await asyncio.to_thread(leitura.ler_planilha, conteudo, nome)
            c = await asyncio.to_thread(leitura.avaliar, c)
        except (ValueError, RuntimeError) as e:
            return [Saida(f"Não consegui ler a carteira: {e}")]
        if not c.posicoes:
            return [Saida("Não achei posições com valor nesse arquivo. Tente uma planilha com colunas Ativo e Valor.")]
        ident = arquivo.salvar(c)
        resumo = arquivo.descrever(c, ident)
        saidas = [Saida(f"📥 Li a carteira ({'print' if imagem else nome}):\n{resumo}"[:LIMITE_TELEGRAM])]
        if imagem:
            saidas.append(Saida("🔒 Dica: recorte o nome do cliente antes de mandar print (use só CLI-XXX)."))
        pedido = legenda.strip() or "Confira a leitura comigo e, se estiver certa, faça o diagnóstico completo."
        texto = (f"O Rickson enviou uma carteira, já lida e guardada como {ident} (use carteira_id='{ident}' na "
                 f"análise carteira_diagnostico; não retranscreva as posições):\n{resumo}\n\nPedido: {pedido}")
        reg = await self.agente.responder(texto, chat=chat, skills=["analise"])
        saidas += [Saida(p) for p in dividir(reg.resposta or "(sem resposta)")]
        for p in reg.pendencias:
            saidas.append(Saida(f"🔐 Aprovação #{p.id}: {p.resumo}", [("✅ Aprovar", f"aprovar:{p.id}"), ("❌ Negar", f"negar:{p.id}")]))
        return saidas

    def garantir_rotinas_padrao(self) -> list[str]:
        """Cria as rotinas de config/agente.yaml (ex.: briefing das 7h30) se ainda não existirem."""
        from quiron.runtime import permissoes

        existentes = {(a.texto, a.recorrencia) for a in self.agente.agendador.listar()}
        criadas = []
        for r in permissoes.config().get("rotinas_padrao") or []:
            chave = (str(r["texto"]).strip(), str(r["recorrencia"]).strip().lower())
            if chave not in existentes:
                self.agente.agendador.criar(chave[0], r.get("tipo", "tarefa"), chave[1], None)
                criadas.append(chave[0])
        return criadas

    async def agenda_vencida(self, agora: datetime | None = None) -> list[str]:
        """Lembretes/tarefas na hora. Lembretes pedidos pelo Rickson sempre saem; contam no limite diário."""
        saidas = []
        for a in self.agente.agendador.vencidos(agora):
            if a.tipo == "lembrete":
                texto = f"⏰ Lembrete: {a.texto}"
            else:
                reg = await self.agente.responder(a.texto, skills=self.skills_para(a.texto))
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

    os.environ["QUIRON_ORIGEM"] = "telegram"  # análises pedidas por aqui são entregues no Telegram quando ficam prontas
    async with ConexaoMCP() as conexao:
        if conexao.falhas:
            logging.warning("servidores MCP com problema: %s", conexao.falhas)
        bot = BotQuiron(Agente(conexao), permitidos)
        app = Application.builder().token(token).build()

        async def enviar(chat: int, s: Saida) -> None:
            linhas = s.teclado()
            teclado = InlineKeyboardMarkup([[InlineKeyboardButton(r, callback_data=d) for r, d in linha] for linha in linhas]) \
                if linhas else None
            await app.bot.send_message(chat, s.texto, reply_markup=teclado, disable_web_page_preview=True)

        async def digitando(chat: int) -> None:
            while True:  # o "digitando…" do Telegram dura 5 s: renova até a resposta sair
                try:
                    await app.bot.send_chat_action(chat, ChatAction.TYPING)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(4)

        async def ao_receber(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.effective_message
            if not msg or not update.effective_user:
                return
            if update.effective_user.id not in permitidos:
                logging.warning("ignorei mensagem do ID %s (@%s): não está em TELEGRAM_ALLOWED_USER_IDS",
                                update.effective_user.id, update.effective_user.username or "-")
                return
            sinal = asyncio.create_task(digitando(msg.chat_id))
            try:
                if msg.voice or msg.audio:
                    arquivo = await (msg.voice or msg.audio).get_file()
                    conteudo = bytes(await arquivo.download_as_bytearray())
                    saidas = await bot.tratar_audio(update.effective_user.id, msg.chat_id, conteudo,
                                                    "voz.ogg" if msg.voice else (msg.audio.file_name or "audio.mp3"))
                elif msg.photo or msg.document:
                    origem = msg.photo[-1] if msg.photo else msg.document
                    if getattr(origem, "file_size", 0) and origem.file_size > 20_000_000:
                        saidas = [Saida("Arquivo grande demais para o Telegram entregar ao bot (limite de 20 MB).")]
                    else:
                        arquivo = await origem.get_file()
                        conteudo = bytes(await arquivo.download_as_bytearray())
                        imagem = bool(msg.photo) or (msg.document.mime_type or "").startswith("image/")
                        nome = "print.jpg" if msg.photo else (msg.document.file_name or "arquivo")
                        saidas = await bot.tratar_arquivo(update.effective_user.id, msg.chat_id, conteudo, nome,
                                                          msg.caption or "", imagem)
                else:
                    saidas = await bot.tratar(update.effective_user.id, msg.chat_id, msg.text or "")
            finally:
                sinal.cancel()
            for s in saidas:
                await enviar(msg.chat_id, s)

        async def ao_clicar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            q = update.callback_query
            await q.answer()
            if (q.data or "").startswith("ac:"):
                sinal = asyncio.create_task(digitando(q.message.chat_id))
                try:
                    editar, saidas = await bot.clicar_academia(q.from_user.id, q.data)
                finally:
                    sinal.cancel()
                try:
                    if editar:
                        await q.edit_message_text(editar[:LIMITE_TELEGRAM], reply_markup=None)
                    else:
                        await q.edit_message_reply_markup(None)
                except Exception:  # noqa: BLE001 — mensagem antiga ou igual: segue o fluxo
                    pass
                for s in saidas:
                    await enviar(q.message.chat_id, s)
                return
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

        async def laco_preaquecer() -> None:
            """Às 7h10 busca os dados do briefing para o das 7h30 sair rápido (cache das fontes)."""
            from quiron.servicos.mercado import painel

            feito = None
            while True:
                agora = datetime.now(BRT)
                if agora.strftime("%H:%M") >= "07:10" and agora.strftime("%H:%M") < "07:30" and feito != agora.date():
                    feito = agora.date()
                    try:
                        await asyncio.to_thread(painel.briefing)
                    except Exception:  # noqa: BLE001
                        logging.exception("falha ao pré-carregar o briefing")
                await asyncio.sleep(60)

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

        async def laco_analises() -> None:
            """Entrega as análises prontas (resumo + PDF + planilha) pedidas pelo Telegram."""
            from quiron.servicos.analise.fila import fila

            while True:
                try:
                    f = fila()
                    for t in f.a_entregar("telegram"):
                        if t.situacao == "erro":
                            await app.bot.send_message(dono, f"⚠️ A análise #{t.id} falhou: {t.erro[:500]}")
                        else:
                            rel = f.relatorio(t.id)
                            texto = rel.resumo_curto() if rel else f"📑 {t.titulo}\n{t.resumo}"
                            await app.bot.send_message(dono, f"✅ Análise #{t.id} pronta\n{texto}"[:LIMITE_TELEGRAM])
                            for tipo_arq, caminho in t.arquivos().items():
                                if tipo_arq in {"pdf", "planilha"}:
                                    with caminho.open("rb") as arq:
                                        await app.bot.send_document(dono, arq, filename=f"quiron-{t.id:04d}-{caminho.name}")
                        f.marcar_entregue(t.id)
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha ao entregar análises")
                await asyncio.sleep(10)

        async def laco_academia() -> None:
            """De madrugada, aumenta o banco de questões aos poucos (dentro dos limites grátis)."""
            from quiron.servicos.academia import estudo

            while True:
                cfg = estudo.config_geracao()
                try:
                    novas = await asyncio.to_thread(estudo.lote_noturno, bot.academia.banco, datetime.now(BRT).strftime("%H:%M"), cfg)
                    if novas:
                        logging.info("academia: +%d questões no banco", len(novas))
                except Exception:  # noqa: BLE001
                    logging.exception("falha na geração noturna de questões")
                await asyncio.sleep(max(5, int(cfg.get("intervalo_min", 12))) * 60)

        for criada in bot.garantir_rotinas_padrao():
            logging.info("rotina padrão criada: %s", criada)
        app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO | filters.Document.ALL,
                                       ao_receber))
        app.add_handler(CallbackQueryHandler(ao_clicar))
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            tarefas = [asyncio.create_task(laco_agenda()), asyncio.create_task(laco_batimento()), asyncio.create_task(laco_preaquecer()),
                       asyncio.create_task(laco_academia()), asyncio.create_task(laco_analises())]
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
