"""Ferramentas próprias do agente (não são MCP): skills, memória, busca em conversas, agenda e propor skill nova."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quiron.nucleo.config import PASTA_AGENTE
from quiron.runtime.agendador import BRT, Agendador, RecorrenciaInvalida
from quiron.runtime.memoria import Memoria
from quiron.runtime.workspace import Workspace

PASTA_SKILLS = PASTA_AGENTE / "skills"


def _f(nome: str, descricao: str, props: dict[str, Any] | None = None, obrig: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": nome, "description": descricao,
                                             "parameters": {"type": "object", "properties": props or {}, "required": obrig or []}}}


DEFINICOES = [
    _f("ler_skill", "Lê as instruções completas de uma skill do Quíron. Leia a skill indicada ANTES de responder pedidos desse tipo.",
       {"nome": {"type": "string"}}, ["nome"]),
    _f("lembrar", "Guarda na memória persistente um fato durável sobre o Rickson (perfil, preferência, objetivo, trabalho, estudo, "
                  "rotina, visão de mercado dele, cliente por CLI-XXX). Fato curto, em 3ª pessoa. Nunca dado identificável de cliente.",
       {"fato": {"type": "string"},
        "categoria": {"type": "string", "enum": ["perfil", "preferencia", "objetivo", "trabalho", "estudo", "cliente", "rotina",
                                                 "mercado", "geral"]},
        "importancia": {"type": "integer", "description": "1 a 5 (5 = essencial e permanente)"}}, ["fato"]),
    _f("esquecer", "Apaga da memória um fato pelo número (#12) ou os que contêm um trecho (pede aprovação do Rickson).",
       {"trecho": {"type": "string"}}, ["trecho"]),
    _f("buscar_conversas", "Procura na memória: fatos guardados, resumos de conversas anteriores e mensagens antigas "
                           "(ex.: 'o que falamos sobre CLI-012', 'qual era minha meta de estudo').",
       {"termo": {"type": "string"}}, ["termo"]),
    _f("agendar", "ROTINAS e pedidos que o Quíron executa na hora (para uma tarefa/lembrete pontual do Rickson, como 'amanhã às 10h "
                  "ligar para o CLI-012', use quiron_organizacao__criar_tarefa). tipo='lembrete' manda o texto na hora; tipo='tarefa' faz o pedido na hora "
                  "(ex.: 'Faça meu briefing.') e manda o resultado. recorrencia: 'uma vez' (informe quando_iso, horário de Brasília) | "
                  "'diario HH:MM' | 'dias_uteis HH:MM' | 'semanal <segunda..domingo> HH:MM' | 'mensal <1-28> HH:MM'.",
       {"texto": {"type": "string"}, "tipo": {"type": "string", "enum": ["lembrete", "tarefa"]},
        "recorrencia": {"type": "string"}, "quando_iso": {"type": "string", "description": "AAAA-MM-DDTHH:MM, só para 'uma vez'"}},
       ["texto", "tipo", "recorrencia"]),
    _f("listar_agenda", "Lista lembretes e tarefas agendados."),
    _f("cancelar_agendamento", "Cancela um agendamento pelo número (#id).", {"id": {"type": "integer"}}, ["id"]),
    _f("propor_skill", "Propõe uma skill nova do Quíron (instruções em Markdown para um tipo de pedido recorrente). "
                       "Só passa a valer depois que o Rickson aprovar.",
       {"nome": {"type": "string", "description": "minúsculas-com-hifen"}, "quando_usar": {"type": "string"},
        "instrucoes": {"type": "string"}}, ["nome", "quando_usar", "instrucoes"]),
]


@dataclass
class FerramentasInternas:
    workspace: Workspace
    memoria: Memoria
    agendador: Agendador
    longa: Any = None  # MemoriaLonga (memória persistente); sem ela, cai no MEMORIA.md antigo

    nomes = frozenset(d["function"]["name"] for d in DEFINICOES)

    def resumo(self, nome: str, a: dict[str, Any]) -> str:
        """Texto curto para o botão de aprovação."""
        if nome == "esquecer":
            return f"Apagar da memória os fatos com “{a.get('trecho', '')}”"
        if nome == "propor_skill":
            return f"Criar a skill nova “{a.get('nome', '')}” — {a.get('quando_usar', '')}"
        return f"{nome} {a}"

    def executar(self, nome: str, a: dict[str, Any]) -> str:
        if nome == "ler_skill":
            nome_skill = re.sub(r"[^a-z0-9\-]", "", str(a.get("nome", "")).lower().removeprefix("quiron-"))
            arq = PASTA_SKILLS / f"{nome_skill}.md"
            if not arq.exists():
                return f"Skill '{nome_skill}' não existe. Disponíveis: {', '.join(p.stem for p in PASTA_SKILLS.glob('*.md'))}"
            return arq.read_text(encoding="utf-8")
        if nome == "lembrar":
            if self.longa is None:
                return self.workspace.lembrar(str(a.get("fato", "")))
            return self.longa.adicionar(str(a.get("fato", "")), str(a.get("categoria") or "geral"),
                                        int(a.get("importancia") or 4), "dito")[0]
        if nome == "esquecer":
            return self.longa.esquecer(str(a.get("trecho", ""))) if self.longa is not None else \
                self.workspace.esquecer(str(a.get("trecho", "")))
        if nome == "buscar_conversas":
            termo = str(a.get("termo", ""))
            partes = []
            if self.longa is not None and (lembrado := self.longa.buscar(termo)):
                partes.append("Memória (fatos e conversas resumidas):\n" + lembrado)
            if self.longa is not None and (regs := self.longa.buscar_registros(termo, 6)):
                partes.append("Registro completo (comandos, avisos enviados, arquivos):\n" + "\n".join(
                    f"- {datetime.fromisoformat(r['quando']).astimezone(BRT):%d/%m/%Y %H:%M} [{r['tipo']}] {(r['conteudo'] or '')[:300]}"
                    for r in regs))
            achados = self.memoria.buscar(termo)
            if achados:
                partes.append("Mensagens antigas:\n" + "\n".join(
                    f"- {t.quando.astimezone(BRT):%d/%m/%Y %H:%M} {'Rickson' if t.papel == 'user' else 'Quíron'}: {t.texto[:300]}"
                    for t in achados))
            return "\n\n".join(partes) or "Nada encontrado na memória nem nas conversas anteriores."
        if nome == "agendar":
            try:
                quando = datetime.fromisoformat(a["quando_iso"]) if a.get("quando_iso") else None
                ag = self.agendador.criar(str(a.get("texto", "")), str(a.get("tipo", "lembrete")), str(a.get("recorrencia", "uma vez")), quando)
            except (ValueError, RecorrenciaInvalida) as e:
                return f"Não agendei: {e}"
            return f"Agendado: {ag.descrever()}"
        if nome == "listar_agenda":
            itens = self.agendador.listar()
            return "\n".join(a.descrever() for a in itens) if itens else "Nada agendado."
        if nome == "cancelar_agendamento":
            return "Cancelado." if self.agendador.cancelar(int(a.get("id", 0))) else "Não encontrei esse agendamento ativo."
        if nome == "propor_skill":
            nome_skill = re.sub(r"[^a-z0-9\-]", "", str(a.get("nome", "")).lower())
            if not nome_skill:
                return "Nome de skill inválido."
            arq = PASTA_SKILLS / f"{nome_skill}.md"
            if arq.exists():
                return f"Já existe a skill {nome_skill}; não sobrescrevo."
            arq.write_text(f"# Skill: {nome_skill}\n\n**Quando usar:** {a.get('quando_usar', '').strip()}\n\n{a.get('instrucoes', '').strip()}\n",
                           encoding="utf-8")
            return f"Skill {nome_skill} criada em agente/skills/{nome_skill}.md."
        return f"Ferramenta interna desconhecida: {nome}"
