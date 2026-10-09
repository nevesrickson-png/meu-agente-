"""Carreira no Telegram, direto (sem o laço do agente): /carreira, /diario, /portfolio, /entrevista, /radar, /cartas.

O registro de tese usa o cérebro só para estruturar o texto (com plano B por regras); revisão, radar e plano são Python.
A entrevista ativa captura as mensagens seguintes (como o treino da Fase 13)."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path

from quiron.nucleo.cerebro import CerebroIndisponivel
from quiron.runtime.academia_bot import Tela
from quiron.servicos.carreira import diario, entrevista, plano, portfolio, radar

COMANDOS = {"carreira", "diario", "portfolio", "entrevista", "radar", "cartas"}
AJUDA_DIARIO = ("Diário de teses:\n/diario <tese> — ex.: /diario WEGE3 vai superar o Ibovespa em 6 meses porque… confiança 70%; "
                "se a margem cair abaixo de 20%, a tese morre\n/diario lista · /diario revisar [nº] · /diario <nº> acertou|parcial|errou|abandonada "
                "<aprendizado> · /diario adiar <nº> 3 meses · /diario placar")


class CarreiraBot:
    def __init__(self) -> None:
        self.ultimo_pdf: Path | None = None

    async def comando(self, nome: str, args: str) -> list[Tela]:
        try:
            return await asyncio.to_thread(self._comando, nome, (args or "").strip())
        except (ValueError, diario.TeseInvalida, entrevista.EntrevistaInvalida) as e:
            return [Tela(f"⚠️ {e}")]
        except CerebroIndisponivel:
            return [Tela("Sem IA no momento (cota dos modelos grátis?). Tente daqui a pouco.")]

    def _comando(self, nome: str, a: str) -> list[Tela]:
        if nome == "carreira":
            if m := re.fullmatch(r"prova\s+(\S+)\s+(\d{4}-\d{2}-\d{2})", a, re.I):
                return [Tela(plano.registrar_prova(m[1], date.fromisoformat(m[2])))]
            if m := re.fullmatch(r"(aprovado|reprovado)\s+(\S+)", a, re.I):
                return [Tela(plano.registrar_prova(m[2], None, m[1].lower()))]
            if m := re.fullmatch(r"avaliar\s+(.+?)\s+(\d{1,2})", a, re.I):
                return [Tela(plano.avaliar(m[1], int(m[2])))]
            return [Tela(plano.montar())]
        if nome == "diario":
            return [Tela(self._diario(a))]
        if nome == "portfolio":
            if m := re.fullmatch(r"add\s+#?(\d+)\s*(.*)", a, re.I):
                return [Tela(portfolio.adicionar(int(m[1]), m[2]))]
            if m := re.fullmatch(r"(?:tirar|remover)\s+#?(\d+)", a, re.I):
                return [Tela("Removido." if portfolio.remover(int(m[1])) else "Não estava no portfólio.")]
            if a.lower() == "pdf":
                self.ultimo_pdf = portfolio.gerar_pdf()
                return [Tela(f"📄 Portfólio gerado: {self.ultimo_pdf}")]
            return [Tela(portfolio.listar_texto())]
        if nome == "entrevista":
            al = a.lower()
            if al in {"opcoes", "opções", "ajuda"}:
                return [Tela(entrevista.opcoes())]
            if al in {"fim", "encerrar", "feedback"}:
                return [Tela(entrevista.encerrar()[1])]
            return [Tela(entrevista.iniciar(a)[1])]
        if nome == "cartas" and a.lower() in {"novas", "novidades", "nova"}:
            from quiron.servicos.cartas import consultas as cartas

            return [Tela(cartas.novidades())]
        if nome == "cartas":  # /cartas · /cartas 30 · /cartas Verde · /cartas gestoras · /cartas novas
            from quiron.servicos.cartas import consultas as cartas

            if a.lower() in {"gestoras", "situacao", "situação", "status"}:
                return [Tela(cartas.situacao())]
            if a.isdigit():
                return [Tela(cartas.listar(dias=min(int(a), 365)))]
            return [Tela(cartas.listar(gestora=a or None))]
        if nome == "radar":
            dias = int(m[0]) if (m := re.search(r"\d+", a)) else 14
            return [Tela(radar.relatorio(dias, so_novos=a.lower().startswith("novidade")))]
        return [Tela("Comando desconhecido.")]

    def _diario(self, a: str) -> str:
        al = a.lower()
        if not a:
            return AJUDA_DIARIO
        if al in {"lista", "listar", "abertas"}:
            return "\n".join(t.resumo() for t in diario.listar("aberta")) or "Nenhuma tese aberta."
        if al in {"todas"}:
            return "\n".join(t.resumo() for t in diario.listar("todas")) or "Nenhuma tese."
        if al in {"placar", "track record", "estatisticas"}:
            return diario.texto_estatisticas()
        if m := re.fullmatch(r"revisar(?:\s+#?(\d+))?", al):
            return diario.revisar(int(m[1])) if m[1] else diario.revisao_de_teses(7)
        if m := re.fullmatch(r"adiar\s+#?(\d+)\s+(.+)", a, re.I):
            return "⏰ " + diario.adiar(int(m[1]), m[2]).resumo()
        if m := re.fullmatch(r"#?(\d+)\s+(acertou|parcial|errou|abandonada)\s*(.*)", a, re.I):
            t = diario.resolver(int(m[1]), m[2], m[3])
            return f"Fechada: {t.resumo()}\n\n{diario.texto_estatisticas()}"
        if re.fullmatch(r"#?\d+", a):
            return diario.descrever(diario.obter(int(a.lstrip("#"))))
        return "📓 Tese registrada:\n" + diario.descrever(diario.registrar(a))

    async def texto_livre(self, texto: str) -> list[Tela] | None:
        if entrevista.ativa() is None:
            return None
        try:
            return [Tela(await asyncio.to_thread(entrevista.responder, texto))]
        except CerebroIndisponivel:
            return [Tela("O entrevistador ficou sem IA agora (cota). Repita daqui a pouco ou /entrevista fim.")]
