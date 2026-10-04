"""Configuração central do Quíron.

Lê o `.env` da raiz do projeto e os arquivos YAML de `config/`.
Nenhum outro módulo deve ler variáveis de ambiente diretamente: tudo passa por aqui.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
PASTA_CONFIG = RAIZ / "config"
PASTA_DADOS = RAIZ / "dados"
PASTA_AGENTE = RAIZ / "agente"


def pasta_biblioteca() -> Path:
    """Pasta da biblioteca (QUIRON_BIBLIOTECA no ambiente permite apontar outra, ex.: nos testes)."""
    return Path(os.environ.get("QUIRON_BIBLIOTECA") or RAIZ / "biblioteca")


def pasta_dados() -> Path:
    return Path(os.environ.get("QUIRON_DADOS") or PASTA_DADOS)


def _texto(nome: str, padrao: str = "") -> str:
    """Lê uma variável de ambiente, ignorando comentários colados ao valor."""
    valor = os.environ.get(nome, padrao) or padrao
    return valor.split(" #")[0].strip()


@dataclass(frozen=True)
class Config:
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_principal: str = "gemini/gemini-flash-latest"
    llm_reserva: str = "groq/openai/gpt-oss-120b"
    llm_local: str = "ollama/qwen2.5:3b"
    fuso_horario: str = "America/Sao_Paulo"
    host_atual: str = "pc"
    runtime_agente: str = "a_definir"
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def modelos(self) -> list[str]:
        """Ordem de tentativa do cérebro: principal → reserva (sem repetir, sem vazios)."""
        ordem: list[str] = []
        for m in (self.llm_principal, self.llm_reserva):
            if m and m not in ordem:
                ordem.append(m)
        return ordem

    def tem_chave_para(self, modelo: str) -> bool:
        provedor = modelo.split("/", 1)[0]
        if provedor == "gemini":
            return bool(self.gemini_api_key)
        if provedor == "groq":
            return bool(self.groq_api_key)
        return True  # ollama e outros locais não precisam de chave


@lru_cache(maxsize=1)
def carregar_config(arquivo_env: str | None = None) -> Config:
    load_dotenv(arquivo_env or RAIZ / ".env", override=False)
    return Config(
        gemini_api_key=_texto("GEMINI_API_KEY"),
        groq_api_key=_texto("GROQ_API_KEY"),
        llm_principal=_texto("LLM_PRINCIPAL", Config.llm_principal),
        llm_reserva=_texto("LLM_RESERVA", Config.llm_reserva),
        llm_local=_texto("LLM_LOCAL", Config.llm_local),
        fuso_horario=_texto("FUSO_HORARIO", Config.fuso_horario),
        host_atual=_texto("HOST_ATUAL", Config.host_atual),
        runtime_agente=_texto("RUNTIME_AGENTE", Config.runtime_agente),
    )


def ler_yaml(nome: str) -> Any:
    """Lê `config/<nome>` (com ou sem a extensão .yaml)."""
    caminho = PASTA_CONFIG / (nome if nome.endswith(".yaml") else f"{nome}.yaml")
    with caminho.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
