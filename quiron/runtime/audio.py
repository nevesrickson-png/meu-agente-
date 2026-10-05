"""Transcrição de áudio (mensagens de voz do Telegram) pelo Whisper gratuito do Groq."""

from __future__ import annotations

import os

import httpx

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELO = "whisper-large-v3-turbo"
LIMITE_BYTES = 24 * 1024 * 1024  # o Groq aceita até 25 MB por arquivo
# Vocabulário que o Whisper deve reconhecer (nomes próprios e jargão de mercado)
VOCABULARIO = ("Quíron, Selic, CDI, IPCA, IPCA+, Copom, Focus, Tesouro Direto, Ibovespa, CDB, LCI, LCA, CRI, CRA, "
               "debênture, PGBL, VGBL, portabilidade, multimercado, previdência, suitability, FII, duration, CLI-012, PETR4, VALE3, "
               "ITUB4, CFP, CNPI, briefing")


class AudioIndisponivel(RuntimeError):
    pass


def transcrever(conteudo: bytes, nome_arquivo: str = "voz.ogg", cliente: httpx.Client | None = None) -> str:
    chave = os.environ.get("GROQ_API_KEY", "").split(" #")[0].strip()
    if not chave:
        raise AudioIndisponivel("Para entender áudio, coloque GROQ_API_KEY no .env (chave gratuita em console.groq.com).")
    if len(conteudo) > LIMITE_BYTES:
        raise AudioIndisponivel("Áudio grande demais (máximo ~25 MB). Mande em partes.")
    c = cliente or httpx.Client(timeout=120)
    try:
        r = c.post(URL, headers={"Authorization": f"Bearer {chave}"},
                   data={"model": MODELO, "language": "pt", "response_format": "json", "temperature": "0", "prompt": VOCABULARIO},
                   files={"file": (nome_arquivo, conteudo)})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise AudioIndisponivel(f"Não consegui transcrever o áudio agora ({type(e).__name__}). Tente de novo ou escreva.") from e
    finally:
        if cliente is None:
            c.close()
    texto = (r.json().get("text") or "").strip()
    if not texto:
        raise AudioIndisponivel("Não entendi nada no áudio. Pode repetir?")
    return texto
