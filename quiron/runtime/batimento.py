"""Batimento proativo (heartbeat, ideia do OpenClaw): de tempos em tempos o Quíron confere ROTINAS.md, a agenda e o
diário do dia e decide sozinho se vale mandar uma mensagem — respeitando o limite diário de mensagens automáticas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quiron.runtime import permissoes
from quiron.runtime.agendador import BRT

PROMPT = """[BATIMENTO AUTOMÁTICO — o Rickson NÃO escreveu esta mensagem]
Confira as rotinas abaixo. Use as ferramentas (notícias, alertas, cotações, agenda) para checar se alguma condição aconteceu.
Não repita avisos que já estão no diário de hoje. Se nada justificar incomodar o Rickson agora, responda exatamente: NADA
Se justificar, escreva a mensagem curta que ele vai receber (com fonte e horário dos dados).

## Rotinas
{rotinas}

## Diário de hoje (avisos já enviados)
{diario}
"""


@dataclass
class ConfigBatimento:
    ativo: bool = True
    intervalo_min: int = 120
    inicio: str = "07:00"
    fim: str = "22:00"

    @classmethod
    def ler(cls) -> "ConfigBatimento":
        c = permissoes.config().get("batimento") or {}
        horario = c.get("horario") or ["07:00", "22:00"]
        return cls(bool(c.get("ativo", True)), int(c.get("intervalo_min", 120)), str(horario[0]), str(horario[1]))

    def dentro_do_horario(self, agora: datetime) -> bool:
        hhmm = agora.astimezone(BRT).strftime("%H:%M")
        return self.inicio <= hhmm <= self.fim


async def bater(agente, agora: datetime | None = None) -> str | None:
    """Uma rodada do batimento. Devolve a mensagem a enviar ou None."""
    agora = (agora or datetime.now(BRT)).astimezone(BRT)
    cfg = ConfigBatimento.ler()
    if not cfg.ativo or not cfg.dentro_do_horario(agora) or not agente.agendador.pode_enviar(agora):
        return None
    rotinas = agente.workspace.ler("ROTINAS.md").strip()
    if not any(l.strip().startswith("-") for l in rotinas.splitlines()):
        return None  # sem rotinas, não gasta cota do modelo
    reg = await agente.responder(PROMPT.format(rotinas=rotinas, diario=agente.workspace.diario(agora) or "(nada ainda)"))
    texto = (reg.resposta or "").strip()
    if reg.erro or not texto or texto.upper().strip(" .!") == "NADA" or texto.upper().startswith("NADA"):
        return None
    agente.agendador.registrar_envio("batimento", agora)
    agente.workspace.anotar_diario(f"Aviso enviado (batimento): {texto[:200]}", agora)
    return texto
