"""Aceite da Fase 14 com o agente e o áudio de verdade (precisa de GEMINI/GROQ e internet): `uv run pytest -m online`.

"amanhã às 10h ligar para o CLI-012" (texto livre, sem comando) vira tarefa e o lembrete chega na hora, com botões.
Também por áudio (voz sintética em português → Whisper → mesma rota)."""

import asyncio
import shutil
import subprocess
from datetime import datetime, time, timedelta

import pytest

from quiron.runtime.agendador import BRT

pytestmark = pytest.mark.online


def _rodar(tmp_path, monkeypatch, acao):
    """Sobe os MCP de verdade, monta o bot e roda `acao(bot)` numa única corrotina (o MCP exige a mesma tarefa)."""
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    from quiron.nucleo.config import carregar_config
    from quiron.runtime.agente import Agente
    from quiron.runtime.ferramentas_mcp import ConexaoMCP
    from quiron.runtime.telegram_bot import BotQuiron

    async def principal():
        async with ConexaoMCP() as conexao:
            return await acao(BotQuiron(Agente(conexao, carregar_config()), {111}))

    return asyncio.run(principal())


async def _confere_lembrete(b, texto_esperado: str):
    from quiron.servicos.organizacao import tarefas

    pend = tarefas.listar()
    assert len(pend) == 1, [t.texto for t in pend]
    t = pend[0]
    assert texto_esperado.lower() in t.texto.lower() and t.hora == "10:00"
    amanha = (datetime.now(BRT) + timedelta(days=1)).date()
    assert t.prazo == amanha.isoformat()
    chegou = await b.agenda_vencida(datetime.combine(amanha, time(10, 0, 30), tzinfo=BRT))
    assert chegou and chegou[0].texto.startswith("⏰ Lembrete:") and texto_esperado.lower() in chegou[0].texto.lower()
    assert [r for linha in chegou[0].teclado() for r, _ in linha] == ["✅ Feito", "⏰ +1h", "📅 Amanhã"]


def test_aceite_texto_livre_vira_tarefa_e_lembrete_chega(tmp_path, monkeypatch):
    async def acao(b):
        saidas = await b.tratar(111, 111, "amanhã às 10h ligar para o CLI-012")
        print("\n".join(s.texto for s in saidas))
        await _confere_lembrete(b, "CLI-012")

    _rodar(tmp_path, monkeypatch, acao)


@pytest.mark.skipif(not shutil.which("espeak-ng") or not shutil.which("ffmpeg"), reason="precisa de espeak-ng e ffmpeg")
def test_aceite_audio_vira_tarefa(tmp_path, monkeypatch):
    wav, ogg = tmp_path / "f.wav", tmp_path / "f.ogg"
    subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "140", "-w", str(wav), "Amanhã às dez horas, ligar para o contador."], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", str(ogg)], check=True)

    async def acao(b):
        saidas = await b.tratar_audio(111, 111, ogg.read_bytes())
        print("\n".join(s.texto for s in saidas))
        await _confere_lembrete(b, "contador")

    _rodar(tmp_path, monkeypatch, acao)
