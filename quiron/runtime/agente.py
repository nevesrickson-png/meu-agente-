"""Laço do agente do Quíron (runtime próprio): o melhor de Hermes, Claude Code e OpenClaw — ver docs/08-AGENTE-QUIRON.md.

Contexto montado do workspace (SOUL/USUARIO/MEMORIA, ideia do OpenClaw) + índice de skills (Claude Code/Hermes) +
ferramentas MCP do Quíron + ferramentas internas (memória, busca em conversas, agenda, propor skill — Hermes) +
permissões por ferramenta e hooks de compliance (Claude Code) + compactação da conversa.
Independente de canal: Telegram, linha de comando e comparativo usam a mesma classe `Agente`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from quiron.nucleo import cerebro
from quiron.nucleo.config import PASTA_AGENTE, Config, carregar_config
from quiron.runtime import permissoes
from quiron.runtime.agendador import Agendador
from quiron.runtime.ferramentas_internas import DEFINICOES, PASTA_SKILLS, FerramentasInternas
from quiron.runtime.ferramentas_mcp import ConexaoMCP
from quiron.runtime.memoria import Memoria
from quiron.runtime.memoria_longa import INATIVIDADE_EPISODIO, MAX_MSGS_EPISODIO, Escriba, MemoriaLonga
from quiron.runtime.workspace import Workspace

MAX_PASSOS = 8  # limite de idas e vindas com ferramentas por pergunta
BRT = ZoneInfo("America/Sao_Paulo")
FERRAMENTA_SKILL = DEFINICOES[0]  # compatibilidade


def indice_skills() -> str:
    linhas = []
    for arq in sorted(PASTA_SKILLS.glob("*.md")):
        quando = re.search(r"\*\*Quando usar:\*\*\s*(.+)", arq.read_text(encoding="utf-8"))
        linhas.append(f"- `{arq.stem}`: {quando.group(1).strip() if quando else ''}")
    return "\n".join(linhas)


PROMPT_OFFLINE = (
    "Você é o Quíron, assistente do Rickson (assessor de investimentos), rodando OFFLINE no PC dele com um modelo local.\n"
    "Regras:\n"
    "1. Para livros, fichas de clientes, tarefas e contas, CHAME A FERRAMENTA e responda só com o que ela devolver.\n"
    "2. Ao citar um livro, copie o título e o autor exatamente como aparecem no resultado (📚 Livro — Autor, p. X).\n"
    "3. Se a ferramenta não trouxer a resposta, diga que não encontrou. Não invente nada.\n"
    "4. Clientes só pelo código CLI-XXX. Dados de mercado aqui podem estar desatualizados.\n"
    "5. Responda em português do Brasil, em até 6 frases."
)


def prompt_sistema(agora: datetime | None = None, workspace: Workspace | None = None, memoria: str | None = None) -> str:
    from quiron.nucleo import offline

    agora = agora or datetime.now(BRT)
    if offline.ativo():  # modelo pequeno: prompt curto e direto (com a memória enxuta)
        extra = f"\n\nO que você sabe do Rickson:\n{memoria[:1200]}" if memoria else ""
        return f"{PROMPT_OFFLINE}\n\nAgora: {agora:%d/%m/%Y %H:%M}.{extra}"
    ws = workspace
    persona = ws.ler("SOUL.md") if ws else (PASTA_AGENTE / "persona.md").read_text(encoding="utf-8")
    partes = [persona, f"## Agora\n{agora:%A, %d/%m/%Y %H:%M} (horário de Brasília)."]
    if ws:
        partes.append(f"## Sobre o Rickson\n{ws.ler('USUARIO.md')}")
        if memoria is not None:
            if memoria:
                partes.append("## Sua memória de longo prazo (use com naturalidade; não liste isso a ele sem motivo)\n" + memoria)
        else:
            fatos = ws.fatos()
            if fatos:
                partes.append("## O que você já sabe (memória de longo prazo)\n" + "\n".join(f"- {f}" for f in fatos[-60:]))
    partes += [
        "## Como trabalhar\n"
        "- Use as ferramentas para qualquer dado (mercado, notícias, livros). Nunca responda número de memória.\n"
        "- Antes de responder um pedido coberto por uma skill, chame `ler_skill` e siga as instruções.\n"
        "- Você tem memória persistente: o que é durável nas conversas é guardado sozinho. Use `lembrar` quando ele pedir "
        "explicitamente ou quando algo for claramente importante; `buscar_conversas` para recuperar o que foi dito antes. "
        "Nunca guarde dado identificável de cliente (só CLI-XXX).\n"
        "- Lembretes e rotinas: use `agendar`. Só diga que agendou depois que a ferramenta confirmar.\n"
        "- Ações que pedem aprovação ficam pendentes: diga que pediu a aprovação dele, sem fingir que já fez.\n"
        "- Respostas curtas, para ler no celular. Português do Brasil.",
        f"## Skills disponíveis\n{indice_skills()}",
    ]
    return "\n\n".join(partes)


@dataclass
class Registro:
    """O que aconteceu numa resposta (usado no comparativo e nos logs)."""

    pergunta: str
    resposta: str = ""
    ferramentas: list[str] = field(default_factory=list)
    modelos: list[str] = field(default_factory=list)
    segundos: float = 0.0
    erro: str = ""
    tokens: int = 0
    pendencias: list[permissoes.Pendencia] = field(default_factory=list)


class Agente:
    def __init__(self, conexao: ConexaoMCP, config: Config | None = None, *, workspace: Workspace | None = None,
                 memoria: Memoria | None = None, agendador: Agendador | None = None, aprovacoes: permissoes.Aprovacoes | None = None,
                 longa: MemoriaLonga | None = None, em_segundo_plano: bool = True):
        self.conexao = conexao
        self.config = config or carregar_config()
        self.workspace = workspace or Workspace.padrao()
        self.memoria = memoria or Memoria()
        self.agendador = agendador or Agendador()
        self.aprovacoes = aprovacoes or permissoes.Aprovacoes()
        self.longa = longa or MemoriaLonga()
        self.escriba = Escriba(self.longa, config=self.config)
        self.em_segundo_plano = em_segundo_plano  # testes rodam o escriba na hora
        self._fechando: set[int] = set()
        self.internas = FerramentasInternas(self.workspace, self.memoria, self.agendador, self.longa)

    def ferramentas(self) -> list[dict[str, Any]]:
        from quiron.nucleo import offline

        internas = DEFINICOES
        if offline.ativo():  # modelo pequeno: só as internas listadas em config/offline.yaml
            permitidas = set(offline.config().get("ferramentas_internas") or [])
            internas = [d for d in DEFINICOES if d["function"]["name"] in permitidas]
        todas = [*internas, *self.conexao.ferramentas]
        return [f for f in todas if permissoes.politica(f["function"]["name"]) != "bloqueado"]

    async def executar_ferramenta(self, nome: str, args: dict[str, Any]) -> str:
        if nome in self.internas.nomes:
            return await asyncio.to_thread(self.internas.executar, nome, args)
        return await self.conexao.chamar(nome, args)

    async def responder(self, pergunta: str, historico: list[dict[str, Any]] | None = None, *, chat: int | None = None,
                        skills: list[str] | None = None) -> Registro:
        reg = Registro(pergunta)
        inicio = time.time()
        if historico is None and chat is not None:
            self.fechar_se_ocioso(chat)
            historico = self.memoria.historico(chat)
        try:
            lembranca = await asyncio.to_thread(self.longa.contexto, pergunta)
        except Exception:  # noqa: BLE001 — memória com problema nunca impede a resposta
            logging.exception("memória longa indisponível")
            lembranca = None
        explicito = self.escriba.lembrete_explicito(pergunta) if chat is not None else None
        sistema = prompt_sistema(workspace=self.workspace, memoria=lembranca)
        if explicito:
            sistema += f"\n\n(Memória: {explicito}. Confirme a ele em poucas palavras.)"
        for s in skills or []:  # skill pré-carregada (ideia do Hermes `-s`): o modelo não precisa pedir
            texto = self.internas.executar("ler_skill", {"nome": s})
            if not texto.startswith("Skill '"):
                sistema += f"\n\n## Skill já carregada para este pedido: {s}\n{texto}"
        mensagens: list[dict[str, Any]] = [{"role": "system", "content": sistema},
                                           *(historico or []), {"role": "user", "content": pergunta}]
        try:
            from quiron.nucleo import offline

            for _ in range(int(offline.config().get("passos_agente", MAX_PASSOS)) if offline.ativo() else MAX_PASSOS):
                turno = await asyncio.to_thread(cerebro.conversar, mensagens, self.ferramentas(), config=self.config)
                reg.modelos.append(turno.modelo)
                reg.tokens += getattr(turno, "tokens", 0)
                mensagens.append(turno.mensagem)
                if not turno.chamadas:
                    reg.resposta = turno.texto.strip()
                    break
                for c in turno.chamadas:
                    reg.ferramentas.append(c["nome"])
                    resultado = await self._com_permissao(c["nome"], c["argumentos"], reg)
                    mensagens.append({"role": "tool", "tool_call_id": c["id"], "name": c["nome"], "content": resultado[:12000]})
            else:
                reg.resposta = "Não consegui concluir em poucas etapas. Pode reformular ou dividir o pedido?"
        except cerebro.CerebroIndisponivel as e:
            reg.erro = str(e)
            reg.resposta = "O cérebro está indisponível agora (limite gratuito ou chave). Tente de novo em alguns minutos."
        if not reg.erro:
            reg.resposta = permissoes.aplicar_compliance(pergunta, reg.resposta)
        reg.segundos = round(time.time() - inicio, 1)
        if chat is not None and not reg.erro:
            self.memoria.guardar(chat, "user", pergunta)
            self.memoria.guardar(chat, "assistant", reg.resposta)
            await asyncio.to_thread(self._compactar, chat)
            self._depois_de_responder(chat, pergunta, reg.resposta, bool(explicito))
        return reg

    # ------------------------------------------------------------ memória longa (escriba em segundo plano)
    def _rodar(self, chave: int, funcao, *args) -> None:
        """Escriba fora do caminho da resposta (o Rickson não espera); um por conversa de cada vez."""
        if chave in self._fechando:
            return

        def alvo() -> None:
            try:
                funcao(*args)
            except Exception:  # noqa: BLE001
                logging.exception("falha no escriba da memória")
            finally:
                self._fechando.discard(chave)

        self._fechando.add(chave)
        if self.em_segundo_plano:
            threading.Thread(target=alvo, name="escriba-memoria", daemon=True).start()
        else:
            alvo()

    def fechar_episodio(self, chat: int, forcar: bool = False) -> None:
        msgs = self.memoria.mensagens_desde(chat, self.longa.ultimo_id_episodio(chat))
        if msgs:
            self.escriba.fechar(chat, msgs, forcar=forcar)

    def fechar_se_ocioso(self, chat: int, agora: datetime | None = None) -> bool:
        """Conversa parada há 30 min (ou longa demais) vira episódio + fatos extraídos."""
        msgs = self.memoria.mensagens_desde(chat, self.longa.ultimo_id_episodio(chat))
        if not msgs:
            return False
        ultima = datetime.fromisoformat(msgs[-1][1])
        agora = agora or datetime.now(ultima.tzinfo)
        if agora - ultima >= INATIVIDADE_EPISODIO or len(msgs) >= MAX_MSGS_EPISODIO:
            self._rodar(chat, self.fechar_episodio, chat)
            return True
        return False

    def _depois_de_responder(self, chat: int, pergunta: str, resposta: str, explicito: bool) -> None:
        if not explicito and self.escriba.tem_pista(pergunta):
            self._rodar(-abs(chat) - 1_000_000, self.escriba.extrair_troca, pergunta, resposta)
        n = len(self.memoria.mensagens_desde(chat, self.longa.ultimo_id_episodio(chat)))
        if n >= MAX_MSGS_EPISODIO:
            self._rodar(chat, self.fechar_episodio, chat)

    def novo_assunto(self, chat: int) -> None:
        """/novo: a conversa atual vira episódio (nada se perde) e o contexto recomeça."""
        self._rodar(chat, self.fechar_episodio, chat, True)
        self.memoria.reiniciar(chat)

    async def _com_permissao(self, nome: str, args: dict[str, Any], reg: Registro) -> str:
        regra = permissoes.politica(nome)
        if regra == "bloqueado":
            return "BLOQUEADO: esta ferramenta está proibida pela configuração do Rickson."
        if regra == "confirmar":
            p = self.aprovacoes.criar(nome, args, self.internas.resumo(nome, args) if nome in self.internas.nomes else f"{nome} {args}")
            reg.pendencias.append(p)
            return f"AGUARDANDO APROVAÇÃO #{p.id}: o Rickson recebeu um botão para aprovar “{p.resumo}”. Não diga que já foi feito."
        return await self.executar_ferramenta(nome, args)

    async def executar_aprovada(self, p: permissoes.Pendencia) -> str:
        return await self.executar_ferramenta(p.ferramenta, p.argumentos)

    def _compactar(self, chat: int) -> None:
        cfg = permissoes.config().get("memoria") or {}

        def resumir(anterior: str, trocas: str) -> str:
            pedido = (f"Resumo anterior:\n{anterior}\n\nNovas trocas:\n{trocas}\n\n" if anterior else f"Trocas:\n{trocas}\n\n") + \
                     "Atualize o resumo desta conversa entre o Rickson e o Quíron em até 12 tópicos curtos: decisões, números citados " \
                     "(com fonte), pedidos em aberto e preferências. Português do Brasil."
            return cerebro.perguntar(pedido, config=self.config, max_tokens=600).texto.strip()

        try:
            self.memoria.compactar(chat, int(cfg.get("turnos_recentes", 8)) * 2, int(cfg.get("resumir_acima_de", 16)) * 2, resumir)
        except cerebro.CerebroIndisponivel:
            pass  # tenta de novo na próxima mensagem


async def _pergunta_unica(pergunta: str) -> Registro:
    async with ConexaoMCP() as conexao:
        return await Agente(conexao).responder(pergunta)


def main() -> None:
    """`uv run quiron-agente -q "faça meu briefing"` — o agente no terminal (sem Telegram)."""
    import argparse
    import json

    p = argparse.ArgumentParser(description="Agente Quíron (runtime próprio)")
    p.add_argument("-q", "--pergunta", required=True)
    p.add_argument("--json", action="store_true", help="saída em JSON (resposta, ferramentas, tempo)")
    a = p.parse_args()
    reg = asyncio.run(_pergunta_unica(a.pergunta))
    if a.json:
        print(json.dumps({k: v for k, v in reg.__dict__.items() if k != "pendencias"}, ensure_ascii=False))
    else:
        print(reg.resposta)
        print(f"\n— {reg.segundos}s · ferramentas: {', '.join(reg.ferramentas) or 'nenhuma'} · modelo: {', '.join(sorted(set(reg.modelos)))}")
        if reg.erro:
            print(reg.erro)
