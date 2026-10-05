"""Canal Telegram do agente do Quíron (python-telegram-bot, long polling: não abre porta nenhuma).

- Só responde aos IDs em TELEGRAM_ALLOWED_USER_IDS (estranhos: silêncio).
- Comandos de barra vêm de `agente/comandos/*.md` (+ /novo, /agenda, /memoria, /ajuda).
- Ações sensíveis chegam com botões ✅/❌ (permissões em config/agente.yaml).
- Laços em segundo plano: agenda (lembretes e tarefas na hora) e batimento proativo.
"""

from __future__ import annotations

import asyncio
import contextvars
import difflib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from quiron.nucleo.config import carregar_config
from quiron.runtime import batimento
from quiron.runtime.academia_bot import COMANDOS as COMANDOS_ACADEMIA
from quiron.runtime.academia_bot import AcademiaBot, Tela
from quiron.runtime.assessoria_bot import COMANDOS as COMANDOS_ASSESSORIA
from quiron.runtime.assessoria_bot import AssessoriaBot
from quiron.runtime.organizacao_bot import COMANDOS as COMANDOS_ORGANIZACAO
from quiron.runtime.organizacao_bot import OrganizacaoBot, botoes_tarefa
from quiron.runtime.carreira_bot import COMANDOS as COMANDOS_CARREIRA
from quiron.runtime.carreira_bot import CarreiraBot
from quiron.runtime.conteudo_bot import COMANDOS as COMANDOS_CONTEUDO
from quiron.runtime.conteudo_bot import ConteudoBot
from quiron.runtime.agendador import BRT
from quiron.runtime.agente import Agente
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.roteamento import descrever_ferramenta, rotear
from quiron.runtime.workspace import carregar_comandos

# Estado de CADA mensagem (o laço da agenda pode rodar um /revisao enquanto outra mensagem espera a IA: atributos do
# objeto se misturariam; ContextVar é separado por tarefa assíncrona).
_ESTADO: contextvars.ContextVar[dict] = contextvars.ContextVar("estado_mensagem")
TEMPO_MAXIMO_RESPOSTA_S = 420  # uma resposta travada não pode prender o bot (as mensagens são atendidas em fila)
LIMITE_TELEGRAM = 4000  # o Telegram aceita até 4096 caracteres por mensagem
INATIVIDADE_MODO_S = 3 * 3600  # treino/entrevista/pós-reunião parados há mais que isso se encerram sozinhos
SAIR = {"/sair", "sair", "/cancelar"}
ATALHOS = [[("📊 Briefing", "qa:/briefing"), ("☀️ Meu dia", "qa:/hoje"), ("📈 Simular", "qa:/simular")],
           [("🎓 Estudar", "qa:/academia"), ("🧠 Memória", "qa:/memoria"), ("❓ Ajuda", "qa:/ajuda")]]
IDADE_MAXIMA_S = 6 * 3600  # mensagens recebidas com o bot desligado: responde as de até 6 h; mais antigas são ignoradas
INICIO = ("Olá! Sou o Quíron. Pode perguntar livremente, mandar áudio, foto ou planilha.\n\n"
          "Para começar: /briefing (mercado agora) · /hoje (seu dia) · /academia (estudo) · /tarefa amanhã às 10h …\n"
          "Todos os comandos: /ajuda · Toque em “/” ao lado do campo de mensagem para ver o menu.")


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


def para_html(texto: str) -> str:
    """Markdown que os modelos escrevem → HTML que o Telegram entende (negrito, itálico, código, links, títulos,
    listas e tabelas alinhadas). Tudo escapado antes: texto do modelo nunca vira HTML de verdade."""
    import html as _html

    blocos: list[str] = []

    def guardar(conteudo: str) -> str:
        blocos.append(conteudo)
        return f"\x00{len(blocos) - 1}\x00"

    t = texto or ""
    t = re.sub(r"```[a-zA-Z0-9_-]*\n?(.*?)```", lambda m: guardar(f"<pre>{_html.escape(m.group(1).strip())}</pre>"), t, flags=re.S)
    linhas, saida, tabela = t.split("\n"), [], []

    def fechar_tabela() -> None:
        if tabela:
            celulas = [[c.strip() for c in l.strip().strip("|").split("|")] for l in tabela
                       if not re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", l)]
            larg = [max(len(re.sub(r"\*\*|__", "", r[i])) if i < len(r) else 0 for r in celulas) for i in range(max(map(len, celulas)))]
            corpo = "\n".join("  ".join(re.sub(r"\*\*|__", "", c).ljust(larg[i]) for i, c in enumerate(r)).rstrip() for r in celulas)
            saida.append(guardar(f"<pre>{_html.escape(corpo)}</pre>"))
            tabela.clear()

    for linha in linhas:
        if re.match(r"\s*\|.*\|\s*$", linha):
            tabela.append(linha)
            continue
        fechar_tabela()
        saida.append(linha)
    fechar_tabela()
    t = _html.escape("\n".join(saida), quote=False)
    t = re.sub(r"`([^`\n]+)`", lambda m: guardar(f"<code>{m.group(1)}</code>"), t)
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", lambda m: guardar(f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>'), t)
    t = re.sub(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", r"<b>\1</b>", t, flags=re.M)
    t = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"^(\s*)[-*•]\s+", r"\1• ", t, flags=re.M)
    t = re.sub(r"^\s*(?:---+|\*\*\*+)\s*$", "──────────", t, flags=re.M)
    return re.sub(r"\x00(\d+)\x00", lambda m: blocos[int(m.group(1))], t)


@dataclass
class Saida:
    """Uma mensagem a enviar; `botoes` = [(rótulo, dado do botão)]."""

    texto: str
    botoes: list[tuple[str, str]] = field(default_factory=list)
    linhas: list[list[tuple[str, str]]] = field(default_factory=list)  # várias linhas de botões (Academia)
    arquivo: str = ""  # caminho de um arquivo para mandar junto (ex.: PDF do portfólio)

    def teclado(self) -> list[list[tuple[str, str]]]:
        return self.linhas or ([self.botoes] if self.botoes else [])


def separar_sugestoes(texto: str, maximo: int = 3) -> tuple[str, list[str]]:
    """Linhas finais "» …" da resposta viram botões de próximo passo; o resto é o texto."""
    linhas = (texto or "").rstrip().splitlines()
    sugestoes: list[str] = []
    while linhas and (linhas[-1].strip().startswith(("»", "&raquo;")) or not linhas[-1].strip()):
        item = linhas.pop().strip().lstrip("»").replace("&raquo;", "").strip(" *_`")
        if item:
            sugestoes.insert(0, item[:120])
    return "\n".join(linhas).rstrip(), sugestoes[:maximo]


class BotQuiron:
    """Lógica do bot separada da biblioteca do Telegram (facilita testar)."""

    def __init__(self, agente: Agente, permitidos: set[int]):
        self.agente, self.permitidos = agente, permitidos
        self.comandos = carregar_comandos()
        self.academia = AcademiaBot()
        self.assessoria = AssessoriaBot()
        self.organizacao = OrganizacaoBot()
        self.carreira = CarreiraBot()
        self.conteudo = ConteudoBot()
        self._ultima_captura = 0.0  # última mensagem capturada por treino/entrevista (para encerrar por inatividade)
        self._pos_desde: dict[int, float] = {}
        self.sugestoes: dict[str, str] = {}  # id do botão "ms:<id>" → texto da sugestão
        self._ultima_tarefa: dict[int, tuple[int, float]] = {}  # chat → (nº da tarefa recém-criada/mexida, quando)

    # ------------------------------------------------------------ modos que capturam mensagens (treino, entrevista, /pos)
    def _modos_abertos(self, chat: int) -> list[str]:
        from quiron.servicos.assessoria import treino
        from quiron.servicos.carreira import entrevista

        abertos = []
        if chat in self.assessoria.esperando_pos:
            abertos.append(f"pós-reunião de {self.assessoria.esperando_pos[chat]}")
        if treino.ativa() is not None:
            abertos.append("treino com cliente simulado")
        if entrevista.ativa() is not None:
            abertos.append("simulação de entrevista")
        return abertos

    def _fechar_modos(self, chat: int) -> list[str]:
        from quiron.servicos.assessoria import treino
        from quiron.servicos.carreira import entrevista

        fechados = []
        if self.assessoria.esperando_pos.pop(chat, None):
            fechados.append("pós-reunião")
        if treino.abandonar():
            fechados.append("treino")
        if entrevista.abandonar():
            fechados.append("entrevista")
        self._pos_desde.pop(chat, None)
        return fechados

    def _expirar_modos(self, chat: int) -> str:
        """Modo esquecido aberto não pode sequestrar as conversas: depois de 3 h parado, encerra e avisa."""
        from quiron.servicos.assessoria import treino
        from quiron.servicos.carreira import entrevista

        agora = time.time()
        fechados = []
        if chat in self.assessoria.esperando_pos and agora - self._pos_desde.get(chat, 0) > INATIVIDADE_MODO_S:
            fechados.append(f"pós-reunião de {self.assessoria.esperando_pos.pop(chat)}")
        for nome, mod in (("treino", treino), ("entrevista", entrevista)):
            s = mod.ativa()
            if s is None:
                continue
            try:
                inicio = datetime.fromisoformat(s.iniciada_em).timestamp()
            except ValueError:
                inicio = 0.0
            if agora - max(inicio, self._ultima_captura) > INATIVIDADE_MODO_S:
                mod.abandonar()
                fechados.append(nome)
        return f"ℹ️ Encerrei por inatividade: {', '.join(fechados)} (sem feedback). Voltamos à conversa normal.\n\n" if fechados else ""

    def autorizado(self, usuario: int) -> bool:
        if usuario not in self.permitidos:
            logging.warning("mensagem ignorada de usuário não autorizado: %s", usuario)
            return False
        return True

    def ajuda(self) -> str:
        linhas = ["Quíron no ar. Fale normalmente (ou mande áudio): “me lembra amanhã às 10h de ligar pro CLI-012”, "
                  "“terminei a 3”, “o que tenho hoje?”, “me dá uma questão de renda fixa”. Ou use:"]
        linhas += [f"/{c.nome} — {c.descricao}" for c in self.comandos.values()]
        linhas += ["", "🎓 Academia (20 campos + certificações): /academia painel · /area [nome] · "
                   "/questoes [área] [módulo|tema] · /simulado [área] [mini|40|completo] · /flashcards · /diagnostico · "
                   "/plano [horas]", "",
                   "🤝 Assessoria: /pos CLI-XXX (depois mande o áudio da reunião → resumo e lembretes) · "
                   "/treino [personagem] [cenário] [dificuldade] · /treino fim (feedback) · /treino opcoes · /treino evolucao", "",
                   "🗂️ Organização: /tarefa amanhã às 10h ligar para o CLI-012 · /tarefas · /feito 3 · /adiar 3 sexta · /hoje · "
                   "/nota texto #tag · /notas [busca] · /meta estudar 5 horas por semana · /meta 1 +2 · /metas · /revisao · "
                   "/evento quinta às 15h reunião (Google Agenda)", "",
                   "🧭 Carreira: /carreira (plano) · /diario <tese> · /diario revisar · /portfolio · /entrevista [cargo] · "
                   "/radar [dias] (normas da CVM, Receita, BC e Câmara)", "",
                   "✍️ Conteúdo: /pauta [tema] · /roteiro reels|youtube|carrossel|fio|artigo <tema> · /fio <tema> · /ideia · /ideias · "
                   "/conferir <seu texto> (sai como RASCUNHO, com disclaimer e fontes)", "",
                   "📈 Patrimônio: /simular <sua situação em palavras> ou /simular CLI-012 — quanto investir por mês, quando dá para "
                   "parar de trabalhar, em quanto tempo chega à meta, imóvel × aplicações (3 cenários + gráfico)", ""]
        linhas += ["🧠 Memória: eu aprendo sozinho com as conversas · /memoria (ver) · /memoria conversas · /memoria buscar <tema> · "
                   "/memoria esquecer <nº> · /memoria mudar <nº> <texto> · /memoria hoje (tudo o que aconteceu no dia) · "
                   "/memoria exportar · /lembrar <fato>", "",
                   "/agenda — lembretes e rotinas", "/novo — novo assunto (a conversa anterior fica guardada)"]
        return "\n".join(linhas)

    async def tratar(self, usuario: int, chat: int, texto: str, progresso=None) -> list[Saida]:
        """Responde e grava tudo no registro completo da memória (o agente grava o próprio caminho dele).
        `progresso(nome)` recebe as ferramentas que a IA vai usar (para o "⏳ consultando…")."""
        estado = {"via_agente": False, "direto": False, "progresso": progresso}
        marca = _ESTADO.set(estado)
        try:
            saidas = await self._tratar(usuario, chat, texto)
        finally:
            _ESTADO.reset(marca)
        if saidas and not estado["via_agente"] and usuario in self.permitidos:
            longa = self.agente.longa
            longa.registrar("telegram", chat, "comando" if (texto or "").strip().startswith("/") else "entrada", (texto or "").strip())
            for s in saidas:
                longa.registrar("telegram", chat, "resposta_comando", s.texto, {"arquivo": s.arquivo} if s.arquivo else None)
            if estado["direto"]:  # continuidade: "e passa para sexta" depois de um /tarefa precisa saber do que se fala
                try:
                    resposta = "\n\n".join(s.texto for s in saidas)[:1500]
                    self.agente.memoria.guardar(chat, "user", (texto or "").strip())
                    self.agente.memoria.guardar(chat, "assistant", resposta)
                except Exception:  # noqa: BLE001
                    logging.exception("não guardei a troca direta no contexto")
        return saidas

    @staticmethod
    def _marcar(chave: str) -> None:
        estado = _ESTADO.get(None)
        if estado is not None:
            estado[chave] = True

    def com_sugestoes(self, saidas: list[Saida]) -> list[Saida]:
        """Sugestões "» …" no fim da resposta da IA viram botões (ms:<id>) na última mensagem."""
        if not saidas or saidas[-1].teclado():
            return saidas
        texto, itens = separar_sugestoes(saidas[-1].texto)
        if not itens:
            return saidas
        botoes = []
        for item in itens:
            self._contador_sugestoes = getattr(self, "_contador_sugestoes", int(time.time()) % 100000) + 1
            chave = f"{self._contador_sugestoes:x}"
            self.sugestoes[chave] = item
            rotulo = item if len(item) <= 55 else item[:55].rsplit(" ", 1)[0] + "…"  # corta em palavra inteira
            botoes.append([(f"» {rotulo}", f"ms:{chave}")])
        while len(self.sugestoes) > 300:  # guarda só as recentes
            self.sugestoes.pop(next(iter(self.sugestoes)))
        saidas[-1].texto = texto or saidas[-1].texto
        saidas[-1].linhas = botoes
        return saidas

    async def clicar_sugestao(self, usuario: int, chat: int, dado: str, progresso=None) -> list[Saida]:
        texto = self.sugestoes.get(dado.removeprefix("ms:"))
        if texto is None:
            return [Saida("Essa sugestão expirou (o bot foi reiniciado). Escreva o pedido normalmente.")] if self.autorizado(usuario) else []
        return await self.tratar(usuario, chat, texto, progresso)

    def registrar_proativo(self, chat: int, texto: str, origem: str) -> None:
        """Mensagens que o Quíron manda sozinho (lembretes, rotinas, alertas, análises prontas, batimento)."""
        self.agente.longa.registrar("telegram", chat, "proativo", texto, {"origem": origem})

    async def _tratar(self, usuario: int, chat: int, texto: str) -> list[Saida]:
        if not self.autorizado(usuario):
            return []  # silêncio: não revela que o bot existe
        texto = (texto or "").strip()
        if texto == "/start":
            return [Saida(INICIO, linhas=ATALHOS)]
        if texto in {"/ajuda", "/help"}:
            return [Saida(self.ajuda())]
        if texto.lower() in SAIR:
            fechados = self._fechar_modos(chat)
            return [Saida(f"✅ Encerrado: {', '.join(fechados)}. Voltamos à conversa normal." if fechados
                          else "Nada aberto: já estamos na conversa normal.")]
        if texto == "/novo":
            self.agente.novo_assunto(chat)
            return [Saida("Novo assunto. A conversa anterior foi guardada na memória (resumo + o que era importante).")]
        if texto == "/agenda":
            itens = self.agente.agendador.listar()
            return [Saida("\n".join(a.descrever() for a in itens) if itens else "Nada agendado. Ex.: “todo dia útil às 7h30 me manda o briefing”.")]
        if texto.split(" ", 1)[0].split("@")[0].lower() in {"/simular", "/simulador", "/patrimonio"}:
            self._marcar("direto")
            return await asyncio.to_thread(self.comando_simular, texto.partition(" ")[2])
        if texto.split(" ", 1)[0].split("@")[0] in {"/memoria", "/memória", "/lembrar"}:
            if texto.split(" ", 1)[-1].strip().lower() in {"exportar", "baixar"}:
                arq = await asyncio.to_thread(self.agente.longa.exportar)
                return [Saida(f"📦 Memória completa exportada ({arq.stat().st_size / 1e6:.1f} MB): fatos, conversas resumidas e o "
                              "registro de tudo. O arquivo é seu — guarde em lugar seguro.", arquivo=str(arq))]
            return [Saida(await asyncio.to_thread(self.comando_memoria, texto))]
        skills: list[str] = []
        aviso = self._expirar_modos(chat)
        if not texto.startswith("/"):
            telas = await self.assessoria.texto_livre(chat, texto)  # pós-reunião aguardando ou treino ativo
            if telas is None:
                telas = await self.carreira.texto_livre(texto)  # entrevista ativa
            if telas is not None:
                self._ultima_captura = time.time()
                if chat not in self.assessoria.esperando_pos:
                    self._pos_desde.pop(chat, None)
                saidas = [self._saida(t) for t in telas]
                if (abertos := self._modos_abertos(chat)) and saidas:
                    saidas[-1].texto += f"\n\n— {abertos[0]} em andamento · /sair volta ao Quíron"
                return saidas
            ultima = self._ultima_tarefa.get(chat)
            if rota := rotear(texto, ultima[0] if ultima and time.time() - ultima[1] < 1800 else None):  # fala normal que pede uma função direta ("terminei a 3", "o que tenho hoje?")
                saidas = await self._tratar(usuario, chat, f"/{rota[0]} {rota[1]}".strip())
                if saidas and aviso:
                    saidas[0].texto = aviso + saidas[0].texto
                return saidas
        if texto.startswith("/"):
            nome, _, args = texto[1:].partition(" ")
            self._preparar_modo(chat, nome.split("@")[0].lower(), args.strip().lower())
            n = nome.split("@")[0].lower()
            direto = None
            if n in COMANDOS_CONTEUDO:
                direto = [self._saida(t) for t in await self.conteudo.comando(n, args)]
            elif n in COMANDOS_CARREIRA:
                self.carreira.ultimo_pdf = None
                direto = [self._saida(t) for t in await self.carreira.comando(n, args)]
                if n == "portfolio" and self.carreira.ultimo_pdf:
                    direto[-1].arquivo = str(self.carreira.ultimo_pdf)
            elif n in COMANDOS_ORGANIZACAO:
                direto = [self._saida(t) for t in await self.organizacao.comando(n, args)]
            elif n in COMANDOS_ASSESSORIA:
                direto = [self._saida(t) for t in await self.assessoria.comando(n, args, chat)]
            elif n in COMANDOS_ACADEMIA:
                direto = [self._saida(t) for t in await self.academia.comando(n, args)]
            if direto is not None:
                if n in {"tarefa", "adiar"} and direto and (m := re.search(r"#(\d+)", direto[0].texto)):
                    self._ultima_tarefa[chat] = (int(m[1]), time.time())
                elif n == "feito":
                    self._ultima_tarefa.pop(chat, None)
                self._registrar_evento(n, args, direto)
                self._marcar("direto")
                return direto
            cmd = self.comandos.get(nome.split("@")[0].lower())
            if not cmd:
                return [Saida(self.desconhecido(nome.split("@")[0].lower()))]
            texto = cmd.montar(args)
            skills = [cmd.skill] if cmd.skill else []
        self._marcar("via_agente")
        reg = await self.agente.responder(texto, chat=chat, skills=skills, progresso=_ESTADO.get({}).get("progresso"))
        saidas = self.com_sugestoes([Saida(p) for p in dividir(aviso + (reg.resposta or "(sem resposta)"))])
        for p in reg.pendencias:
            saidas.append(Saida(f"🔐 Aprovação #{p.id}: {p.resumo}", [("✅ Aprovar", f"aprovar:{p.id}"), ("❌ Negar", f"negar:{p.id}")]))
        return saidas

    # ------------------------------------------------------------ simulador de patrimônio
    def comando_simular(self, args: str) -> list[Saida]:
        from quiron.nucleo.config import pasta_dados
        from quiron.servicos.planejamento import simulador

        ajuda = ("📈 Simulador de patrimônio — escreva do seu jeito, por exemplo:\n"
                 "/simular tenho 40 anos, 500 mil investidos, invisto 5 mil por mês, quero chegar a 5 milhões e viver com 20 mil, moderado\n"
                 "/simular CLI-012 (usa a ficha do cliente) · /simular imóvel de 800 mil em 20 anos\n"
                 "Respondo: quanto investir por mês, quando dá para parar de trabalhar, em quanto tempo chega à meta e imóvel × "
                 "aplicações — com 3 cenários, a chance de chegar lá e o gráfico.")
        args = (args or "").strip()
        cliente = (re.search(r"\bCLI-\d+\b", args, re.I) or [None])[0]
        dados = simulador.ler_frase(args)
        if not args or (not cliente and not any(dados.get(k) for k in ("patrimonio", "aporte_mensal", "meta", "renda_desejada", "imovel_valor"))):
            return [Saida(ajuda)]
        try:
            e = simulador.de_ficha(cliente.upper(), **dados) if cliente else simulador.Entrada.de_dict(dados)
            sim = simulador.simular(e)
        except (ValueError, TypeError) as erro:
            return [Saida(f"⚠️ Não simulei: {erro}\n\n{ajuda}")]
        png = pasta_dados() / "simulacoes" / f"simulacao-{datetime.now():%Y%m%d-%H%M%S}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        try:
            simulador.grafico_png(sim, png)
        except Exception:  # noqa: BLE001 — sem gráfico, o texto basta
            logging.exception("gráfico da simulação")
            return [Saida(simulador.texto(sim))]
        return [Saida(simulador.texto(sim), arquivo=str(png))]

    # ------------------------------------------------------------ memória persistente
    def comando_memoria(self, texto: str) -> str:
        from quiron.runtime.memoria_longa import CATEGORIAS

        longa = self.agente.longa
        cmd, _, a = texto.strip().partition(" ")
        a = a.strip()
        if cmd.split("@")[0] == "/lembrar":
            return longa.adicionar(a, "geral", 4, "dito")[0] if a else "Use /lembrar <o que guardar> (ex.: /lembrar prefiro respostas curtas)."
        al = a.lower()
        if al.startswith("buscar ") or al.startswith("procurar "):
            achado = longa.buscar(a.split(" ", 1)[1])
            return "🔎 Na memória:\n" + achado if achado else "Nada na memória sobre isso."
        if m := re.fullmatch(r"(?:esquecer|apagar|tirar)\s+(.+)", a, re.I):
            return longa.esquecer(m[1])
        if m := re.fullmatch(r"(?:mudar|corrigir|editar)\s+#?(\d+)\s+(.+)", a, re.I | re.S):
            return longa.atualizar(int(m[1]), m[2].strip())
        if al in {"conversas", "episodios", "episódios", "historico", "histórico"}:
            eps = longa.episodios(10)
            return "🗂️ Últimas conversas guardadas:\n" + "\n".join(f"• {e.linha()}" for e in eps) if eps else "Nenhuma conversa resumida ainda."
        if al in {"hoje", "dia"} or (m := re.fullmatch(r"(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", al)):
            from zoneinfo import ZoneInfo

            hoje = datetime.now(ZoneInfo("America/Sao_Paulo"))
            dia = hoje
            if al not in {"hoje", "dia"}:
                ano = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else hoje.year
                try:
                    dia = hoje.replace(year=ano, month=int(m[2]), day=int(m[1]))
                except ValueError:
                    return "Data inválida. Use /memoria hoje ou /memoria 05/10."
            return f"📜 Registro de {dia:%d/%m/%Y}:\n" + longa.linha_do_tempo(dia)
        if al in {"copia", "cópia", "backup"}:
            pasta = longa.fazer_copia()
            return f"💾 Cópia de segurança feita em {pasta}. (Todo dia às 3h ela é feita sozinha; guardo as 30 mais recentes.)"
        if al in {"estado", "status", "saude", "saúde"}:
            r = longa.resumo()
            return (f"🧠 Memória: {r['fatos']} fato(s) ativos, {r['arquivados']} arquivado(s), {r['episodios']} conversa(s) resumida(s), "
                    f"{r['registros']} registro(s) no total · banco {r['tamanho_mb']} MB · integridade: {longa.verificar_integridade()} · "
                    f"última cópia: {r['ultima_copia'] or 'ainda nenhuma'}")
        if al in {"consolidar", "organizar"}:
            r = longa.consolidar()
            return f"🧹 Memória organizada: {r['juntados']} repetido(s) juntado(s), {r['arquivados']} detalhe(s) antigo(s) arquivado(s)."
        longa.importar_edicoes_md()
        fatos = longa.fatos()
        if not fatos:
            return ("Ainda não guardei nada. Eu aprendo sozinho com as conversas; para guardar algo agora: "
                    "/lembrar <fato> ou “lembre que …”.")
        linhas = ["🧠 O que eu sei sobre você (★ = importância):"]
        for cat, titulo in CATEGORIAS.items():
            itens = [f for f in fatos if f.categoria == cat]
            if itens:
                linhas.append(f"\n{titulo}")
                linhas += [f"#{f.id} {'★' * f.importancia} {f.texto}" for f in itens]
        r = longa.resumo()
        linhas.append(f"\n{r['fatos']} fato(s) · {r['episodios']} conversa(s) resumida(s). "
                      "/memoria conversas · /memoria hoje · /memoria 05/10 · /memoria buscar <tema> · /memoria esquecer <nº> · "
                      "/memoria mudar <nº> <texto> · /memoria estado · /memoria exportar · /lembrar <fato>")
        return "\n".join(linhas)

    def _registrar_evento(self, nome: str, args: str, saidas: list[Saida]) -> None:
        """O que ele faz pelos comandos diretos entra na memória (listagens não, só ações)."""
        so_leitura = {"tarefas", "notas", "metas", "ideias", "hoje", "revisao", "carreira", "portfolio", "academia",
                      "diagnostico", "plano", "area", "flashcards", "radar", "pauta", "questoes"}
        if (nome in so_leitura and not args.strip()) or not saidas:
            return
        primeira = next((l for l in saidas[0].texto.splitlines() if l.strip()), "")[:160]
        try:
            self.agente.longa.registrar_evento(nome, f"/{nome} {args.strip()[:80]} → {primeira}".replace("  ", " "))
        except Exception:  # noqa: BLE001
            logging.exception("não registrei o evento na memória")

    def _preparar_modo(self, chat: int, nome: str, args: str) -> None:
        """Começar um modo de conversa fecha o outro (senão as respostas iriam para o modo errado)."""
        from quiron.servicos.assessoria import treino
        from quiron.servicos.carreira import entrevista

        controle = {"fim", "encerrar", "feedback", "terminar", "opcoes", "opções", "ajuda", "evolucao", "evolução",
                    "historico", "histórico", "cancelar", "sair"}
        if nome == "treino" and args not in controle:
            entrevista.abandonar()
            self.assessoria.esperando_pos.pop(chat, None)
        elif nome == "entrevista" and args not in controle:
            treino.abandonar()
            self.assessoria.esperando_pos.pop(chat, None)
        elif nome == "pos" and args and args not in {"cancelar", "cancela"}:
            treino.abandonar()
            entrevista.abandonar()
            self._pos_desde[chat] = time.time()

    def nomes_comandos(self) -> list[str]:
        fixos = ["start", "ajuda", "simular", "novo", "agenda", "memoria", "lembrar", "sair"]
        return fixos + sorted(set(self.comandos) | COMANDOS_ACADEMIA | COMANDOS_ASSESSORIA | COMANDOS_ORGANIZACAO
                              | COMANDOS_CARREIRA | COMANDOS_CONTEUDO)

    def desconhecido(self, nome: str) -> str:
        parecidos = difflib.get_close_matches(nome, self.nomes_comandos(), n=3, cutoff=0.6)
        dica = f" Você quis dizer {' ou '.join('/' + p for p in parecidos)}?" if parecidos else ""
        return f"Não conheço o comando /{nome}.{dica} Veja todos em /ajuda (ou escreva sem a barra que eu entendo)."

    def menu_telegram(self) -> list[tuple[str, str]]:
        """Itens do menu “/” do Telegram (até 100; descrição até 256 caracteres)."""
        descricoes = {"start": "Começar", "ajuda": "Todos os comandos", "novo": "Começar a conversa do zero",
                      "agenda": "Lembretes e rotinas", "memoria": "O que eu sei sobre você (ver, buscar, corrigir)",
                      "lembrar": "Guardar algo na memória",
                      "simular": "Simular patrimônio: quanto investir, quando parar, meta, imóvel",
                      "sair": "Sair do treino/entrevista/pós-reunião", "academia": "Painel de estudo",
                      "area": "Trocar a área de estudo", "questoes": "Questões de prova", "simulado": "Simulado",
                      "flashcards": "Revisar flashcards", "diagnostico": "Diagnóstico da prova", "plano": "Plano de estudo",
                      "pos": "Pós-reunião: /pos CLI-XXX e mande o áudio", "treino": "Treino com cliente simulado",
                      "tarefa": "Nova tarefa (ex.: amanhã às 10h …)", "tarefas": "Minhas tarefas", "feito": "Concluir tarefa",
                      "adiar": "Adiar tarefa", "hoje": "Meu dia", "nota": "Anotar", "notas": "Minhas notas", "meta": "Nova meta",
                      "metas": "Minhas metas", "revisao": "Revisão da semana", "evento": "Evento no Google Agenda",
                      "carreira": "Plano de carreira", "diario": "Diário de teses", "portfolio": "Portfólio de análises",
                      "entrevista": "Simular entrevista", "radar": "Normas novas (CVM, Receita, BC)", "pauta": "Ideias de conteúdo",
                      "roteiro": "Roteiro/carrossel/artigo", "fio": "Fio para redes", "ideia": "Guardar ideia",
                      "ideias": "Banco de ideias", "conferir": "Conferir um texto seu (compliance)"}
        itens = []
        for n in self.nomes_comandos():
            d = descricoes.get(n) or (self.comandos[n].descricao if n in self.comandos else n)
            if re.fullmatch(r"[a-z0-9_]{1,32}", n):
                itens.append((n, d[:256]))
        return itens[:100]

    @staticmethod
    def _saida(t: Tela) -> Saida:
        return Saida(t.texto, linhas=t.linhas)  # o envio divide textos longos (nada é cortado)

    async def clicar_academia(self, usuario: int, dado: str) -> tuple[str | None, list[Saida]]:
        if not self.autorizado(usuario):
            return None, []
        c = await self.academia.clique(dado)
        return c.editar, [self._saida(t) for t in c.novas]

    async def clicar_assessoria(self, usuario: int, dado: str) -> list[Saida]:
        if not self.autorizado(usuario):
            return []
        c = await self.assessoria.clique(dado)
        return [self._saida(t) for t in c.novas]

    async def clicar_organizacao(self, usuario: int, dado: str) -> tuple[str | None, list[Saida]]:
        if not self.autorizado(usuario):
            return None, []
        c = await self.organizacao.clique(dado)
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

    async def tratar_audio(self, usuario: int, chat: int, conteudo: bytes, nome: str = "voz.ogg", progresso=None) -> list[Saida]:
        if not self.autorizado(usuario):
            return []
        from quiron.runtime import audio

        try:
            texto = await asyncio.to_thread(audio.transcrever, conteudo, nome)
        except audio.AudioIndisponivel as e:
            return [Saida(f"🎙️ {e}")]
        self.agente.longa.registrar("telegram", chat, "audio", texto, {"arquivo": nome, "bytes": len(conteudo)})
        return [Saida(f"🎙️ “{texto}”"), *await self.tratar(usuario, chat, texto, progresso)]

    async def tratar_arquivo(self, usuario: int, chat: int, conteudo: bytes, nome: str, legenda: str = "",
                             imagem: bool = False) -> list[Saida]:
        """Carteira por print (OCR local) ou planilha (xlsx/csv): lê aqui, guarda (CART-…) e passa só o resumo ao agente."""
        if not self.autorizado(usuario):
            return []
        from quiron.servicos.carteira import arquivo, leitura

        self.agente.longa.registrar("telegram", chat, "arquivo", f"{'print' if imagem else nome}" + (f" — {legenda}" if legenda else ""),
                                    {"arquivo": nome, "bytes": len(conteudo), "imagem": imagem})

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
        saidas = [Saida(f"📥 Li a carteira ({'print' if imagem else nome}):\n{resumo}")]
        if imagem:
            saidas.append(Saida("🔒 Dica: recorte o nome do cliente antes de mandar print (use só CLI-XXX)."))
        pedido = legenda.strip() or "Confira a leitura comigo e, se estiver certa, faça o diagnóstico completo."
        texto = (f"O Rickson enviou uma carteira, já lida e guardada como {ident} (use carteira_id='{ident}' na "
                 f"análise carteira_diagnostico; não retranscreva as posições):\n{resumo}\n\nPedido: {pedido}")
        reg = await self.agente.responder(texto, chat=chat, skills=["analise"])
        saidas += self.com_sugestoes([Saida(p) for p in dividir(reg.resposta or "(sem resposta)")])
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

    async def agenda_vencida(self, agora: datetime | None = None) -> list[Saida]:
        """Lembretes/tarefas na hora. Lembretes pedidos pelo Rickson sempre saem; contam no limite diário.
        Lembrete de tarefa vem com botões (Feito / +1h / Amanhã); rotina que é um comando ("/revisao") roda direto."""
        from quiron.servicos.organizacao import tarefas

        saidas: list[Saida] = []
        for a in self.agente.agendador.vencidos(agora):
            if a.tipo == "lembrete":
                t = tarefas.por_lembrete(a.id)
                if t and not t.concluida_em:
                    saidas.append(Saida(f"⏰ Lembrete: {t.texto}" + (f" ({t.hora})" if t.hora else ""), linhas=botoes_tarefa(t)))
                else:
                    saidas.append(Saida(f"⏰ Lembrete: {re.sub(r'^\[T\d+\] ', '', a.texto)}"))
            elif a.texto.startswith("/") and self.permitidos:
                saidas += await self.tratar(next(iter(self.permitidos)), next(iter(self.permitidos)), a.texto)
            else:
                reg = await self.agente.responder(a.texto, skills=self.skills_para(a.texto))
                saidas += [Saida(p) for p in dividir(reg.resposta or "(sem resposta)")]
            self.agente.agendador.registrar_envio(f"agenda #{a.id}", agora)
            self.agente.workspace.anotar_diario(f"Agenda #{a.id} enviada: {a.texto[:120]}", agora)
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
            if s.arquivo:
                from pathlib import Path

                with Path(s.arquivo).open("rb") as f:
                    if s.arquivo.lower().endswith((".png", ".jpg", ".jpeg")):
                        await app.bot.send_photo(chat, f)
                    else:
                        await app.bot.send_document(chat, f, filename=Path(s.arquivo).name)
            partes = dividir(s.texto) or [""]
            for i, parte in enumerate(partes):  # botões só na última parte
                botoes = teclado if i == len(partes) - 1 else None
                try:  # formatado (negrito, listas, tabelas); se o Telegram recusar o HTML, vai em texto simples
                    await app.bot.send_message(chat, para_html(parte), parse_mode="HTML", reply_markup=botoes,
                                               disable_web_page_preview=True)
                except Exception as e:  # noqa: BLE001
                    if "parse" not in str(e).lower() and "entit" not in str(e).lower() and "tag" not in str(e).lower():
                        raise
                    await app.bot.send_message(chat, parte, reply_markup=botoes, disable_web_page_preview=True)

        async def digitando(chat: int) -> None:
            while True:  # o "digitando…" do Telegram dura 5 s: renova até a resposta sair
                try:
                    await app.bot.send_chat_action(chat, ChatAction.TYPING)
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(4)

        class Andamento:
            """Mensagem "⏳ consultando…" que mostra o que a IA está fazendo e some quando a resposta chega."""

            def __init__(self, chat: int):
                self.chat, self.msg, self.vistos = chat, None, []

            async def __call__(self, nome: str) -> None:
                desc = descrever_ferramenta(nome)
                if desc in self.vistos:
                    return
                self.vistos.append(desc)
                texto = "⏳ Consultando " + ", ".join(self.vistos) + "…"
                if self.msg is None:
                    self.msg = await app.bot.send_message(self.chat, texto)
                else:
                    await self.msg.edit_text(texto)

            async def apagar(self) -> None:
                if self.msg is not None:
                    try:
                        await self.msg.delete()
                    except Exception:  # noqa: BLE001
                        pass

        async def ao_receber(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            msg = update.effective_message
            if not msg or not update.effective_user:
                return
            if update.effective_user.id not in permitidos:
                logging.warning("ignorei mensagem do ID %s (@%s): não está em TELEGRAM_ALLOWED_USER_IDS",
                                update.effective_user.id, update.effective_user.username or "-")
                return
            if msg.date and (datetime.now(msg.date.tzinfo) - msg.date).total_seconds() > IDADE_MAXIMA_S:
                logging.info("ignorei mensagem antiga (%s) recebida depois de o bot ficar desligado", msg.date)
                return
            sinal = asyncio.create_task(digitando(msg.chat_id))
            andamento = Andamento(msg.chat_id)
            try:
                if msg.voice or msg.audio:
                    arquivo = await (msg.voice or msg.audio).get_file()
                    conteudo = bytes(await arquivo.download_as_bytearray())
                    saidas = await asyncio.wait_for(bot.tratar_audio(update.effective_user.id, msg.chat_id, conteudo,
                                                    "voz.ogg" if msg.voice else (msg.audio.file_name or "audio.mp3"), andamento),
                                                    TEMPO_MAXIMO_RESPOSTA_S)
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
                    saidas = await asyncio.wait_for(bot.tratar(update.effective_user.id, msg.chat_id, msg.text or "", andamento),
                                                    TEMPO_MAXIMO_RESPOSTA_S)
            except TimeoutError:
                logging.error("resposta passou de %s s e foi interrompida", TEMPO_MAXIMO_RESPOSTA_S)
                saidas = [Saida("⌛ Isso demorou demais e eu interrompi para não travar o bot. Tente de novo, de forma mais "
                                "específica, ou peça como análise (ex.: /analise …), que roda em segundo plano.")]
            except Exception as e:  # noqa: BLE001 — nunca deixar o Rickson sem resposta
                logging.exception("erro ao tratar a mensagem")
                saidas = [Saida(f"⚠️ Deu um erro aqui ({type(e).__name__}). Já ficou registrado; tente de novo ou reformule. "
                                "Se repetir, veja Configurações → Registro do Telegram.")]
            finally:
                sinal.cancel()
                await andamento.apagar()
            for s in saidas:
                await enviar(msg.chat_id, s)

        async def ao_clicar(update: Update, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            q = update.callback_query
            if not q or not q.from_user or q.from_user.id not in permitidos:
                return  # botão tocado por outra pessoa (ex.: bot num grupo): nada acontece
            try:
                await q.answer()
            except Exception:  # noqa: BLE001 — botão antigo (o Telegram expira após alguns minutos): segue mesmo assim
                pass
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
            if (q.data or "").startswith(("qa:", "ms:")):  # botões rápidos do /start e sugestões de próximo passo
                sinal = asyncio.create_task(digitando(q.message.chat_id))
                andamento = Andamento(q.message.chat_id)
                try:
                    if q.data.startswith("ms:"):
                        try:  # tira os botões da mensagem antiga e mostra o que foi pedido
                            await q.edit_message_reply_markup(None)
                            await app.bot.send_message(q.message.chat_id, f"➡️ {bot.sugestoes.get(q.data[3:], '')}"[:LIMITE_TELEGRAM])
                        except Exception:  # noqa: BLE001
                            pass
                        saidas = await asyncio.wait_for(bot.clicar_sugestao(q.from_user.id, q.message.chat_id, q.data, andamento),
                                                        TEMPO_MAXIMO_RESPOSTA_S)
                    else:
                        saidas = await asyncio.wait_for(bot.tratar(q.from_user.id, q.message.chat_id, q.data[3:], andamento),
                                                        TEMPO_MAXIMO_RESPOSTA_S)
                except TimeoutError:
                    saidas = [Saida("⌛ Isso demorou demais e eu interrompi para não travar o bot. Tente de novo.")]
                except Exception as e:  # noqa: BLE001
                    logging.exception("erro no atalho")
                    saidas = [Saida(f"⚠️ Deu um erro aqui ({type(e).__name__}). Tente de novo.")]
                finally:
                    sinal.cancel()
                    await andamento.apagar()
                for s in saidas:
                    await enviar(q.message.chat_id, s)
                return
            if (q.data or "").startswith("or:"):
                editar, saidas = await bot.clicar_organizacao(q.from_user.id, q.data)
                try:
                    if editar:
                        await q.edit_message_text(editar[:LIMITE_TELEGRAM], reply_markup=None)
                    else:
                        await q.edit_message_reply_markup(None)
                except Exception:  # noqa: BLE001
                    pass
                for s in saidas:
                    await enviar(q.message.chat_id, s)
                return
            if (q.data or "").startswith("as:"):
                saidas = await bot.clicar_assessoria(q.from_user.id, q.data)
                try:
                    await q.edit_message_reply_markup(None)
                except Exception:  # noqa: BLE001
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
                    for s in await bot.agenda_vencida():
                        bot.registrar_proativo(dono, s.texto, "agenda")
                        await enviar(dono, s)
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha no laço da agenda")
                await asyncio.sleep(30)

        async def laco_alertas() -> None:
            """A cada 5 minutos avalia os alertas (preço, variação, notícia) e avisa os que dispararam."""
            from quiron.servicos import alertas

            while True:
                try:
                    if alertas.listar():
                        for a in await asyncio.to_thread(alertas.avaliar):
                            bot.registrar_proativo(dono, alertas.mensagem(a), "alerta")
                            await app.bot.send_message(dono, alertas.mensagem(a))
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha no laço de alertas")
                await asyncio.sleep(300)

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
                        bot.registrar_proativo(dono, texto, "batimento")
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
                            bot.registrar_proativo(dono, f"⚠️ A análise #{t.id} falhou: {t.erro[:500]}", "analise")
                            await app.bot.send_message(dono, f"⚠️ A análise #{t.id} falhou: {t.erro[:500]}")
                        else:
                            rel = f.relatorio(t.id)
                            texto = rel.resumo_curto() if rel else f"📑 {t.titulo}\n{t.resumo}"
                            bot.registrar_proativo(dono, f"✅ Análise #{t.id} pronta\n{texto}", "analise")
                            await enviar(dono, Saida(f"✅ Análise #{t.id} pronta\n{texto}"))
                            for tipo_arq, caminho in t.arquivos().items():
                                if tipo_arq in {"pdf", "planilha"}:
                                    with caminho.open("rb") as arq:
                                        await app.bot.send_document(dono, arq, filename=f"quiron-{t.id:04d}-{caminho.name}")
                        f.marcar_entregue(t.id)
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha ao entregar análises")
                await asyncio.sleep(10)

        async def laco_memoria() -> None:
            """A cada 5 min: conversa parada há 30 min vira episódio + fatos. Às 3h: organiza a memória (junta e arquiva)."""
            consolidado = None
            while True:
                await asyncio.sleep(300)
                try:
                    for chat, _, _ in bot.agente.memoria.ultimas_por_chat():
                        bot.agente.fechar_se_ocioso(chat)
                    agora = datetime.now(BRT)
                    if agora.hour == 3 and consolidado != agora.date():
                        consolidado = agora.date()
                        r = await asyncio.to_thread(bot.agente.longa.consolidar)
                        logging.info("memória organizada: %s", r)
                        integridade = await asyncio.to_thread(bot.agente.longa.verificar_integridade)
                        if integridade != "ok":
                            await app.bot.send_message(dono, f"⚠️ A memória do Quíron acusou um problema ({integridade[:200]}). "
                                                             "Nada foi apagado; use /memoria estado e fale comigo no Claude Code.")
                        pasta = await asyncio.to_thread(bot.agente.longa.fazer_copia)
                        logging.info("cópia da memória: %s", pasta)
                except Exception:  # noqa: BLE001 — o laço nunca morre
                    logging.exception("falha no laço da memória")

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

        async def ao_errar(update: object, contexto: ContextTypes.DEFAULT_TYPE) -> None:
            logging.error("erro no Telegram: %s", contexto.error, exc_info=contexto.error)

        app.add_error_handler(ao_errar)
        async with app:
            await app.start()
            try:  # menu “/” do Telegram com os comandos
                from telegram import BotCommand

                await app.bot.set_my_commands([BotCommand(n, d) for n, d in bot.menu_telegram()])
            except Exception:  # noqa: BLE001
                logging.exception("não consegui atualizar o menu de comandos")
            # mensagens mandadas enquanto o bot reiniciava não se perdem (as muito antigas são ignoradas em ao_receber)
            await app.updater.start_polling(drop_pending_updates=False)
            tarefas = [asyncio.create_task(laco_agenda()), asyncio.create_task(laco_batimento()), asyncio.create_task(laco_preaquecer()),
                       asyncio.create_task(laco_academia()), asyncio.create_task(laco_analises()),
                       asyncio.create_task(laco_alertas()), asyncio.create_task(laco_memoria())]
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


if __name__ == "__main__":
    main()
