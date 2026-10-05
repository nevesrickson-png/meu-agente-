"""Conteúdo no Telegram, direto (o cérebro só escreve; revisão, créditos e disclaimer são Python):
/pauta [tema] · /roteiro <formato> <tema|#ideia> · /fio <tema> · /ideia <texto> | salvar <nº> | <nº> publicado|descartada ·
/ideias [busca] · /conferir <seu texto>."""

from __future__ import annotations

import asyncio
import re

from quiron.nucleo.cerebro import CerebroIndisponivel
from quiron.runtime.academia_bot import Tela
from quiron.servicos.conteudo import gerador, ideias, revisao

COMANDOS = {"pauta", "roteiro", "fio", "ideia", "ideias", "conferir"}


class ConteudoBot:
    def __init__(self) -> None:
        self.ultimas_pautas: list[gerador.Pauta] = []

    async def comando(self, nome: str, args: str) -> list[Tela]:
        try:
            return await asyncio.to_thread(self._comando, nome, (args or "").strip())
        except ValueError as e:
            return [Tela(f"⚠️ {e}")]
        except CerebroIndisponivel:
            return [Tela("Sem IA no momento (cota dos modelos grátis?). Tente daqui a pouco.")]

    def _comando(self, nome: str, a: str) -> list[Tela]:
        formatos = list(revisao.config()["formatos"])
        if nome == "pauta":
            self.ultimas_pautas, origem = gerador.gerar_pautas(a)
            return [Tela(gerador.texto_pautas(self.ultimas_pautas, origem)[:4000])]
        if nome in {"roteiro", "fio"}:
            if nome == "fio":
                formato, tema = "fio", a
            else:
                partes = a.split(maxsplit=1)
                if not partes or partes[0].lower() not in formatos:
                    return [Tela(f"Use /roteiro <formato> <tema> — formatos: {', '.join(formatos)}. Ex.: /roteiro reels Tesouro Selic x poupança "
                                 "· /roteiro carrossel #3 (ideia do banco)")]
                formato, tema = partes[0].lower(), (partes[1] if len(partes) > 1 else "")
            peca = gerador.gerar_peca(tema, formato)
            return [Tela(peca.entrega()[:4000])]
        if nome == "ideia":
            if m := re.fullmatch(r"salvar\s+(\d+)", a, re.I):
                n = int(m[1])
                if not 1 <= n <= len(self.ultimas_pautas):
                    return [Tela("Gere pautas antes com /pauta e use o número da lista.")]
                p = self.ultimas_pautas[n - 1]
                return [Tela("💡 Guardada: " + ideias.criar(p.titulo, p.angulo, p.formato, p.fontes).descrever())]
            if m := re.fullmatch(r"#?(\d+)\s+(ideia|rascunho|publicado|descartada|descartar)", a, re.I):
                situacao = "descartada" if m[2].lower() == "descartar" else m[2].lower()
                return [Tela(ideias.atualizar(int(m[1]), situacao=situacao).descrever())]
            if not a:
                return [Tela("Use /ideia <sua ideia> · /ideia salvar <nº da pauta> · /ideia <nº> publicado|descartada")]
            return [Tela("💡 Guardada: " + ideias.criar(a).descrever())]
        if nome == "ideias":
            itens = ideias.listar(a)
            return [Tela("\n".join(i.descrever() for i in itens) or "Banco de ideias vazio. Use /ideia ou /pauta.")]
        if nome == "conferir":
            if len(a) < 20:
                return [Tela("Cole o texto depois de /conferir (dica: comece com o tema entre colchetes, ex.: [poupança] seu texto).")]
            tema = ""
            if m := re.match(r"\[([^\]]{3,60})\]\s*", a):
                tema, a = m[1], a[m.end():]
            return [Tela(gerador.conferir_texto(a, tema)[:4000])]
        return [Tela("Comando desconhecido.")]
