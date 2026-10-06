"""Cérebro trocável: TODA chamada a modelo de linguagem do código próprio passa por aqui.

- Ordem de tentativa vem do `.env`: LLM_PRINCIPAL (Gemini grátis) → LLM_RESERVA (Groq grátis).
  Trocar de modelo = mudar o `.env`; nenhum outro arquivo muda.
- O Rickson não digita dados identificáveis de clientes (clientes só como CLI-XXX), então o texto vai como está.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field, replace
from typing import Any

from quiron.nucleo import offline, privacidade
from quiron.nucleo.config import Config, carregar_config


class CerebroIndisponivel(RuntimeError):
    """Nenhum modelo configurado respondeu."""


@dataclass
class Resposta:
    texto: str
    modelo: str
    enviado: list[dict[str, str]]  # mensagens exatamente como foram enviadas
    falhas: list[str] = field(default_factory=list)


def _litellm():
    import litellm

    litellm.suppress_debug_info = True
    litellm.telemetry = False
    return litellm


# Modelo que respondeu "cota esgotada" fica de molho até a cota voltar (não perde tempo tentando de novo).
_PAUSA: dict[str, float] = {}


def _pausar_se_cota(modelo: str, erro: Exception) -> None:
    texto = str(erro)
    if not any(x in texto for x in ("429", "RateLimit", "RESOURCE_EXHAUSTED", "quota")):
        return
    segundos = 60.0
    if "PerDay" in texto:  # cota diária do GEMINI (antes do retryDelay: ele manda "17s" mesmo na cota diária)
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        agora = datetime.now(ZoneInfo("America/Los_Angeles"))  # a cota diária do Gemini volta à meia-noite do Pacífico
        segundos = ((agora + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0) - agora).total_seconds()
        _PAUSA[modelo] = time.time() + min(segundos, 24 * 3600)
        return
    if m := re.search(r'retryDelay"?\s*:\s*"?(\d+)s', texto):
        segundos = float(m.group(1))
    elif m := re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", texto):
        h, mi, se = (float(x or 0) for x in m.groups())
        segundos = h * 3600 + mi * 60 + se or 60.0
    elif "per day" in texto.lower():  # outro provedor com cota diária e sem prazo dito
        segundos = 3600.0
    _PAUSA[modelo] = time.time() + min(segundos, 12 * 3600)


def _em_pausa(modelo: str) -> bool:
    return _PAUSA.get(modelo, 0) > time.time()


def _chave(config: Config, modelo: str) -> str | None:
    provedor = modelo.split("/", 1)[0]
    return {"gemini": config.gemini_api_key, "groq": config.groq_api_key}.get(provedor) or None


def perguntar(
    pergunta: str,
    *,
    sistema: str | None = None,
    config: Config | None = None,
    temperatura: float = 0.3,
    max_tokens: int | None = None,
    **extras: Any,
) -> Resposta:
    """Envia uma pergunta ao cérebro, tentando os modelos na ordem do `.env`.

    `extras` vai direto para o LiteLLM (ex.: `mock_response` nos testes).
    """
    config = config or carregar_config()
    mensagens: list[dict[str, str]] = []
    if sistema:
        mensagens.append({"role": "system", "content": sistema})
    mensagens.append({"role": "user", "content": pergunta})

    llm = _litellm()
    falhas: list[str] = []
    for modelo in config.modelos:
        if not config.tem_chave_para(modelo) and "mock_response" not in extras:
            falhas.append(f"{modelo}: sem chave no .env")
            continue
        if _em_pausa(modelo) and "mock_response" not in extras:
            falhas.append(f"{modelo}: cota esgotada (em pausa)")
            continue
        try:
            r = llm.completion(
                model=modelo,
                messages=mensagens if offline.e_local(modelo) else privacidade.mascarar_mensagens(mensagens),
                api_key=_chave(config, modelo),
                temperature=temperatura,
                max_tokens=max_tokens,
                num_retries=1,
                timeout=180 if offline.e_local(modelo) else 60,
                **{**offline.extras_modelo(modelo), **extras},
            )
            texto = r.choices[0].message.content or ""
            return Resposta(texto, modelo, mensagens, falhas)
        except Exception as e:  # noqa: BLE001 — qualquer falha passa para o próximo modelo
            _pausar_se_cota(modelo, e)
            falhas.append(f"{modelo}: {type(e).__name__}: {str(e)[:200]}")
    raise CerebroIndisponivel("Nenhum modelo respondeu.\n" + "\n".join(falhas))


@dataclass
class Turno:
    """Resposta de um passo da conversa: texto final ou pedidos de ferramenta."""

    texto: str
    chamadas: list[dict[str, Any]]  # [{"id", "nome", "argumentos" (dict)}]
    mensagem: dict[str, Any]  # mensagem do assistente pronta para voltar ao histórico
    modelo: str
    falhas: list[str] = field(default_factory=list)
    tokens: int = 0


def conversar(
    mensagens: list[dict[str, Any]],
    ferramentas: list[dict[str, Any]] | None = None,
    *,
    config: Config | None = None,
    temperatura: float = 0.3,
    **extras: Any,
) -> Turno:
    """Um passo de conversa com ferramentas (formato OpenAI, que o LiteLLM traduz para Gemini/Groq).

    Usado pelos runtimes do agente. Mesma ordem de modelos e troca automática de `perguntar`.
    """
    import json

    config = config or carregar_config()
    llm = _litellm()
    falhas: list[str] = []
    for modelo in config.modelos:
        if not config.tem_chave_para(modelo) and "mock_response" not in extras:
            falhas.append(f"{modelo}: sem chave no .env")
            continue
        if _em_pausa(modelo) and "mock_response" not in extras:
            falhas.append(f"{modelo}: cota esgotada (em pausa)")
            continue
        try:
            r = llm.completion(  # na nuvem, telefone/CPF/e-mail saem mascarados (histórico, ferramentas, escriba…)
                model=modelo, messages=mensagens if offline.e_local(modelo) else privacidade.mascarar_mensagens(mensagens),
                tools=ferramentas or None, api_key=_chave(config, modelo),
                temperature=temperatura, num_retries=2, timeout=300 if offline.e_local(modelo) else 90,
                **{**offline.extras_modelo(modelo), **extras},
            )
            msg = r.choices[0].message
            chamadas = []
            for c in msg.tool_calls or []:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                chamadas.append({"id": c.id, "nome": c.function.name, "argumentos": args})
            # Devolve a mensagem original do provedor ao histórico: o Gemini 3 exige receber de volta as
            # "assinaturas de pensamento" que vêm junto das chamadas de ferramenta.
            try:
                mensagem: dict[str, Any] = msg.model_dump(exclude_none=True)
            except Exception:  # noqa: BLE001
                mensagem = {}
            mensagem["role"] = "assistant"
            mensagem.setdefault("content", msg.content or "")
            if chamadas and not mensagem.get("tool_calls"):
                mensagem["tool_calls"] = [
                    {"id": c["id"], "type": "function", "function": {"name": c["nome"], "arguments": json.dumps(c["argumentos"], ensure_ascii=False)}}
                    for c in chamadas
                ]
            uso = getattr(r, "usage", None)
            return Turno(msg.content or "", chamadas, mensagem, modelo, falhas, int(getattr(uso, "total_tokens", 0) or 0))
        except Exception as e:  # noqa: BLE001
            _pausar_se_cota(modelo, e)
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
        um_so = replace(config, ordem=(modelo,))
        try:
            r = perguntar("Responda apenas com a palavra OK.", config=um_so, max_tokens=10)
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
