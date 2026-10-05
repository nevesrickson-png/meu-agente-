"""Aceite da Fase 13 com IA e áudio de verdade (precisa de GROQ_API_KEY/GEMINI_API_KEY e internet): `uv run pytest -m online`.

1) Um áudio pós-reunião (sintetizado com espeak-ng, em português) é transcrito pelo Whisper do Groq e vira resumo,
   tarefas com prazo e lembretes.
2) Um treino com cliente simulado gera feedback útil (nota por critério, objetivo oculto, reescritas)."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from quiron.runtime.agendador import BRT, Agendador

pytestmark = pytest.mark.online
FALA = ("Acabei de sair da reunião com o cliente CLI zero doze. Ele tem cinquenta e dois anos e é médico. "
        "Vendeu a participação na clínica e quer se aposentar aos sessenta. Ficou chateado porque o fundo multimercado "
        "perdeu do CDI. Combinamos que eu vou enviar a proposta de alocação até sexta-feira. Ele ficou de me mandar a "
        "declaração de imposto de renda amanhã. Também preciso estudar a portabilidade do PGBL dele. "
        "A próxima reunião ficou para o dia vinte às dez horas.")


@pytest.fixture
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIRON_DADOS", str(tmp_path))
    return tmp_path


@pytest.mark.skipif(not shutil.which("espeak-ng") or not shutil.which("ffmpeg"), reason="precisa de espeak-ng e ffmpeg")
def test_aceite_audio_pos_reuniao_vira_resumo_e_tarefas(dados, tmp_path):
    from quiron.runtime import audio
    from quiron.servicos.assessoria import pos_reuniao

    wav, ogg = tmp_path / "fala.wav", tmp_path / "fala.ogg"
    subprocess.run(["espeak-ng", "-v", "pt-br", "-s", "150", "-w", str(wav), FALA], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", str(ogg)], check=True)
    texto = audio.transcrever(ogg.read_bytes(), "voz.ogg")
    assert "proposta" in texto.lower() and "imposto" in texto.lower()

    # a voz sintética diz "CLI zero doze": o /pos já sabe o cliente pelo comando
    agora = datetime.now(BRT)
    r = pos_reuniao.processar("CLI-012", texto, agora=agora)
    destino = Path(os.environ.get("QUIRON_CAPTURAS", dados))
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "pos-reuniao-aceite.md").write_text(f"TRANSCRIÇÃO:\n{texto}\n\n{r.markdown()}", encoding="utf-8")
    assert r.origem == "ia" and len(r.resumo) >= 2
    textos = " ".join(t.texto.lower() for t in r.tarefas)
    assert "proposta" in textos and ("imposto" in textos or "declara" in textos) and ("portab" in textos or "pgbl" in textos)
    combinadas = [t for t in r.tarefas if t.combinado]
    assert len(combinadas) >= 2  # sexta-feira e amanhã calculadas em Python
    assert r.proximo_contato.endswith("-20") or r.proximo_contato == ""
    assert len([a for a in Agendador().listar() if "CLI-012" in a.texto]) >= 3


def test_aceite_treino_gera_feedback_util(dados):
    from quiron.servicos.assessoria import treino

    s, abertura = treino.iniciar("medico_ocupado primeira_reuniao normal")
    assert "Dr. Henrique" in abertura
    for fala in ["Obrigado pelo tempo, Dr. Henrique. Vou direto: o que te fez topar essa conversa hoje?",
                 "Entendi. E como estão seus investimentos hoje? Me conta como você montou essa carteira.",
                 "E pensando na sua família, como você imagina a vida deles se algo acontecer com você?",
                 "Pode ficar tranquilo que com a minha carteira você vai ganhar com certeza uns 20% ao ano.",
                 "Faço assim: te mando um diagnóstico de uma página até sexta e marcamos 20 minutos na semana que vem?"]:
        assert treino.responder(fala).startswith("🗣️ Dr. Henrique:")
    s, texto = treino.encerrar()
    fb = s.feedback
    destino = Path(os.environ.get("QUIRON_CAPTURAS", dados))
    (destino / "treino-aceite.md").write_text("\n".join(f"{m['papel'].upper()}: {m['texto']}" for m in s.mensagens)
                                              + "\n\n" + texto, encoding="utf-8")
    assert fb["origem"] == "ia" and fb["nota_final"] is not None
    assert set(fb["criterios"]) >= {"rapport", "descoberta", "compliance", "fechamento"}
    assert fb["criterios"]["compliance"]["nota"] <= 3  # prometeu 20% "com certeza"
    assert fb["metricas"]["perguntas_abertas"] >= 2 and fb["metricas"]["proximo_passo"]
    assert fb.get("melhorar") and fb.get("reescritas")
