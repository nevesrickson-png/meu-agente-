"""Modo offline (Fase 16): `QUIRON_MODO=offline` (o atalho "Quiron Offline" liga).

- Cérebro: só o modelo local do Ollama (`config/offline.yaml`) — nada vai para Gemini/Groq.
- Rede: `http.obter` não sai para a internet; usa o último dado guardado (marcado DESATUALIZADO).
- Agente: só os servidores MCP leves e as ferramentas listadas em `config/offline.yaml`.
- O cofre de clientes reais (nomes) só abre neste modo (`servicos/offline/cofre.py`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from quiron.nucleo.config import ler_yaml


def ativo() -> bool:
    return os.environ.get("QUIRON_MODO", "").split(" #")[0].strip().lower() == "offline"


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    return ler_yaml("offline") or {}


def modelo() -> str:
    return os.environ.get("LLM_LOCAL_OFFLINE") or config().get("modelo", "ollama_chat/qwen2.5:3b")


def ollama_url() -> str:
    return (os.environ.get("OLLAMA_URL") or config().get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")


def e_local(nome_modelo: str) -> bool:
    return nome_modelo.split("/", 1)[0] in {"ollama", "ollama_chat"}


def extras_modelo(nome_modelo: str) -> dict[str, Any]:
    """Parâmetros do LiteLLM para modelos locais (endereço do Ollama e tamanho do contexto)."""
    if not e_local(nome_modelo):
        return {}
    return {"api_base": ollama_url(), "num_ctx": int(config().get("contexto_tokens", 8192))}


def servidores() -> dict[str, list[str]]:
    return {k: list(v or []) for k, v in (config().get("servidores") or {}).items()}


def preparar_ambiente() -> None:
    """Desliga downloads automáticos (modelo de embeddings) quando offline."""
    if ativo():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
