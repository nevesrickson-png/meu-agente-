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
    llm_local: str = "ollama_chat/qwen2.5:3b"
    # Modelos tentados entre o principal e a reserva. Cada modelo Gemini grátis tem cota diária própria
    # (o Flash mais novo dá só ~20 pedidos/dia), então uma fila de modelos grátis evita cair cedo no Groq.
    llm_alternativos: tuple[str, ...] = ()
    ordem: tuple[str, ...] = ()  # se preenchida, substitui a ordem (usado para "segunda opinião" e testes)
    fuso_horario: str = "America/Sao_Paulo"
    host_atual: str = "pc"
    runtime_agente: str = "a_definir"
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def modelos(self) -> list[str]:
        """Ordem de tentativa do cérebro: principal → reserva (sem repetir, sem vazios)."""
        if self.ordem:
            return list(dict.fromkeys(m for m in self.ordem if m))
        ordem: list[str] = []
        for m in (self.llm_principal, *self.llm_alternativos, self.llm_reserva):
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


# Conferido em 04/10/2026: cada um respondeu na camada grátis com cota própria (LLM_ALTERNATIVOS= vazio desliga).
ALTERNATIVOS_PADRAO = ("gemini/gemini-3.7-flash", "gemini/gemini-3.6-flash", "gemini/gemini-flash-lite-latest")


def _alternativos() -> tuple[str, ...]:
    bruto = os.environ.get("LLM_ALTERNATIVOS")  # ausente = padrão; vazio = nenhum
    texto = ",".join(ALTERNATIVOS_PADRAO) if bruto is None else bruto.split(" #")[0]
    return tuple(m.strip() for m in texto.split(",") if m.strip())


@lru_cache(maxsize=1)
def carregar_config(arquivo_env: str | None = None) -> Config:
    load_dotenv(arquivo_env or RAIZ / ".env", override=False)
    from quiron.nucleo import offline

    if offline.ativo():  # versão offline: só o modelo local, nada de nuvem
        offline.preparar_ambiente()
        return Config(llm_principal=offline.modelo(), llm_reserva="", llm_alternativos=(), llm_local=offline.modelo(),
                      ordem=(offline.modelo(),), fuso_horario=_texto("FUSO_HORARIO", Config.fuso_horario), host_atual="offline")
    return Config(
        gemini_api_key=_texto("GEMINI_API_KEY"),
        groq_api_key=_texto("GROQ_API_KEY"),
        llm_principal=_texto("LLM_PRINCIPAL", Config.llm_principal),
        llm_reserva=_texto("LLM_RESERVA", Config.llm_reserva),
        llm_alternativos=_alternativos(),
        llm_local=_texto("LLM_LOCAL", Config.llm_local),
        fuso_horario=_texto("FUSO_HORARIO", Config.fuso_horario),
        host_atual=_texto("HOST_ATUAL", Config.host_atual),
        runtime_agente=_texto("RUNTIME_AGENTE", Config.runtime_agente),
    )


def _mesclar(base: Any, ajuste: Any) -> Any:
    """Ajuste por cima da base: dicionários mesclados por chave (recursivo); o resto é trocado."""
    if isinstance(base, dict) and isinstance(ajuste, dict):
        return {**base, **{k: _mesclar(base.get(k), v) for k, v in ajuste.items()}}
    return ajuste


def arquivo_ajuste(nome: str) -> Path:
    """`dados/ajustes/<nome>.yaml`: o que o Rickson muda pela tela de Configurações. Fica fora do git (não é apagado
    quando o Quíron se atualiza) e vale por cima do arquivo padrão em `config/`."""
    return pasta_dados() / "ajustes" / (nome if nome.endswith(".yaml") else f"{nome}.yaml")


def ler_yaml(nome: str, *, com_ajustes: bool = True) -> Any:
    """Lê `config/<nome>` (com ou sem a extensão .yaml), com os ajustes da tela por cima."""
    caminho = PASTA_CONFIG / (nome if nome.endswith(".yaml") else f"{nome}.yaml")
    with caminho.open(encoding="utf-8") as f:
        base = yaml.safe_load(f)
    ajuste = arquivo_ajuste(nome) if com_ajustes else None
    if ajuste is not None and ajuste.exists():
        try:
            return _mesclar(base, yaml.safe_load(ajuste.read_text(encoding="utf-8")) or {})
        except (OSError, yaml.YAMLError):
            return base  # ajuste corrompido nunca derruba o Quíron
    return base


def escrever_ajuste(nome: str, dados: dict) -> Path:
    """Troca o arquivo de ajustes inteiro (vazio = apaga: volta tudo ao padrão)."""
    arq = arquivo_ajuste(nome)
    if not dados:
        arq.unlink(missing_ok=True)
        return arq
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(arq)
    return arq


def ler_ajuste(nome: str) -> dict:
    arq = arquivo_ajuste(nome)
    try:
        return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}) if arq.exists() else {}
    except (OSError, yaml.YAMLError):
        return {}


def salvar_ajuste(nome: str, parcial: dict) -> Path:
    """Mescla `parcial` no arquivo de ajustes (troca atômica)."""
    arq = arquivo_ajuste(nome)
    arq.parent.mkdir(parents=True, exist_ok=True)
    atual = {}
    if arq.exists():
        try:
            atual = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            atual = {}
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(_mesclar(atual, parcial), allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(arq)
    return arq
