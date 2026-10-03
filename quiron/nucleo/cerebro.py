"""Cérebro trocável: TODA chamada a modelo de linguagem do código próprio passa por aqui.

- Ordem de tentativa vem do `.env`: LLM_PRINCIPAL (Gemini grátis) → LLM_RESERVA (Groq grátis).
  Trocar de modelo = mudar o `.env`; nenhum outro arquivo muda.
- Antes de enviar, o texto passa pelo anonimizador (compliance: nada identificável sai do PC).
  A resposta volta com os valores originais restaurados, só em memória.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from quiron.nucleo.anonimizador import Anonimizador, carregar_nomes_protegidos
from quiron.nucleo.config import RAIZ, Config, carregar_config

ARQUIVO_NOMES_PROTEGIDOS = RAIZ / "segredos" / "nomes_protegidos.txt"


class CerebroIndisponivel(RuntimeError):
    """Nenhum modelo configurado respondeu."""


@dataclass
class Resposta:
    texto: str
    modelo: str
    enviado: list[dict[str, str]]  # mensagens exatamente como saíram (já anonimizadas)
    falhas: list[str] = field(default_factory=list)


def _litellm():
    import litellm

    litellm.suppress_debug_info = True
    litellm.telemetry = False
    return litellm


def _chave(config: Config, modelo: str) -> str | None:
    provedor = modelo.split("/", 1)[0]
    return {"gemini": config.gemini_api_key, "groq": config.groq_api_key}.get(provedor) or None


def perguntar(
    pergunta: str,
    *,
    sistema: str | None = None,
    config: Config | None = None,
    nomes_protegidos: list[str] | None = None,
    temperatura: float = 0.3,
    max_tokens: int | None = None,
    **extras: Any,
) -> Resposta:
    """Envia uma pergunta ao cérebro, anonimizando antes e restaurando depois.

    `extras` vai direto para o LiteLLM (ex.: `mock_response` nos testes).
    """
    config = config or carregar_config()
    if nomes_protegidos is None:
        nomes_protegidos = carregar_nomes_protegidos(ARQUIVO_NOMES_PROTEGIDOS)
    anon = Anonimizador(nomes_protegidos)

    mensagens: list[dict[str, str]] = []
    if sistema:
        mensagens.append({"role": "system", "content": anon.anonimizar(sistema)})
    mensagens.append({"role": "user", "content": anon.anonimizar(pergunta)})

    llm = _litellm()
    falhas: list[str] = []
    for modelo in config.modelos:
        if not config.tem_chave_para(modelo) and "mock_response" not in extras:
            falhas.append(f"{modelo}: sem chave no .env")
            continue
        try:
            r = llm.completion(
                model=modelo,
                messages=mensagens,
                api_key=_chave(config, modelo),
                temperature=temperatura,
                max_tokens=max_tokens,
                num_retries=1,
                timeout=60,
                **extras,
            )
            texto = r.choices[0].message.content or ""
            return Resposta(anon.desanonimizar(texto), modelo, mensagens, falhas)
        except Exception as e:  # noqa: BLE001 — qualquer falha passa para o próximo modelo
            falhas.append(f"{modelo}: {type(e).__name__}: {str(e)[:200]}")
    raise CerebroIndisponivel("Nenhum modelo respondeu.\n" + "\n".join(falhas))


def testar_conexao(config: Config | None = None) -> list[tuple[str, bool, str]]:
    """Testa cada modelo configurado separadamente. Retorna (modelo, ok, detalhe)."""
    config = config or carregar_config()
    resultados = []
    for modelo in config.modelos:
        if not config.tem_chave_para(modelo):
            resultados.append((modelo, False, "sem chave no .env"))
            continue
        um_so = Config(**{**config.__dict__, "llm_principal": modelo, "llm_reserva": ""})
        try:
            r = perguntar("Responda apenas com a palavra OK.", config=um_so, nomes_protegidos=[], max_tokens=10)
            resultados.append((modelo, True, r.texto.strip()[:40]))
        except CerebroIndisponivel as e:
            resultados.append((modelo, False, str(e).splitlines()[-1]))
    return resultados


def testar_conexao_cli() -> None:
    """`uv run quiron-testar-cerebro` — confere as chaves do .env."""
    print("Testando o cérebro do Quíron...\n")
    resultados = testar_conexao()
    for modelo, ok, detalhe in resultados:
        print(f"  {'✅' if ok else '❌'} {modelo}: {detalhe}")
    algum = any(ok for _, ok, _ in resultados)
    print("\nPronto: o cérebro está funcionando." if algum else "\nNenhum modelo respondeu. Confira o .env.")
    sys.exit(0 if algum else 1)
