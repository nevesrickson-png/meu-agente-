"""Prepara o runtime Hermes Agent para o Quíron (usado no comparativo da Fase 5 e, se escolhido, em produção).

Gera uma pasta HERMES_HOME própria (não mexe no ~/.hermes padrão) com:
- SOUL.md = persona do Quíron (agente/persona.md) + regras de trabalho;
- skills/<nome>/SKILL.md = as skills de agente/skills/ (texto completo, formato de skill do Hermes);
- config.yaml = modelo Gemini (mesmo do bot próprio), servidores MCP do Quíron e ferramentas perigosas DESLIGADAS
  (terminal, arquivos, navegador, computador, código…): o Hermes só usa as ferramentas do Quíron;
- .env = chaves copiadas do .env do projeto (nunca vai para o Git).

Uso: `uv run quiron-hermes-preparar` e depois `HERMES_HOME=<pasta> hermes chat -q "faça meu briefing"`.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import yaml

from quiron.nucleo.config import PASTA_AGENTE, RAIZ, carregar_config, pasta_dados
from quiron.runtime.ferramentas_mcp import ler_mcp_json

# Conjuntos de ferramentas nativas do Hermes que ficam desligados (compliance: o agente não executa comandos,
# não mexe em arquivos, não navega sozinho e não fala com outros sistemas além das ferramentas do Quíron).
DESLIGADOS = ["terminal", "file", "browser", "computer_use", "code_execution", "x_search", "image_gen", "video_gen",
              "connections", "project", "bot_room", "cronjob", "tts", "vision", "video"]


def pasta_padrao() -> Path:
    return pasta_dados() / "hermes"


def _modelo_hermes(modelo_litellm: str) -> tuple[str, str]:
    """'gemini/gemini-flash-latest' → ('gemini', 'gemini-flash-latest')."""
    provedor, _, nome = modelo_litellm.partition("/")
    return provedor, nome or provedor


def soul() -> str:
    persona = (PASTA_AGENTE / "persona.md").read_text(encoding="utf-8")
    return (
        f"{persona}\n\n## Como trabalhar\n"
        "- Use as ferramentas do Quíron (mcp_quiron_*) para qualquer dado de mercado, notícia ou livro; nunca responda número de memória.\n"
        "- Antes de um pedido coberto por uma skill do Quíron (briefing, notícias, estudo, debate, pílula), carregue a skill e siga-a.\n"
        "- Respostas curtas para ler no celular, em português do Brasil, com horário de Brasília.\n"
    )


def skills_hermes(destino: Path) -> list[str]:
    nomes = []
    for arq in sorted((PASTA_AGENTE / "skills").glob("*.md")):
        texto = arq.read_text(encoding="utf-8")
        quando = re.search(r"\*\*Quando usar:\*\*\s*(.+)", texto)
        descricao = f"Quíron — {quando.group(1).strip() if quando else arq.stem}"
        pasta = destino / f"quiron-{arq.stem}"
        pasta.mkdir(parents=True, exist_ok=True)
        cabecalho = yaml.safe_dump({"name": f"quiron-{arq.stem}", "description": descricao[:300]}, allow_unicode=True, sort_keys=False).strip()
        (pasta / "SKILL.md").write_text(f"---\n{cabecalho}\n---\n\n{texto}", encoding="utf-8")
        nomes.append(f"quiron-{arq.stem}")
    return nomes


def config_hermes() -> dict:
    cfg = carregar_config()
    provedor, nome = _modelo_hermes(cfg.llm_principal)
    modelo = {"provider": provedor, "default": nome}
    if provedor == "gemini":
        modelo["base_url"] = "https://generativelanguage.googleapis.com/v1beta"
    servidores = {}
    for nome_srv, s in ler_mcp_json().items():
        args = list(s.get("args", []))
        if s["command"] == "uv" and "--directory" not in args:  # o Hermes não roda dentro da pasta do projeto
            args = [args[0], "--directory", str(RAIZ), *args[1:]]
        servidores[nome_srv] = {"command": shutil.which(s["command"]) or s["command"], "args": args}
    return {
        "model": modelo,
        "agent": {"disabled_toolsets": DESLIGADOS},
        "skills": {"write_approval": True},  # o Hermes não reescreve skills sozinho sem aprovação
        "mcp_servers": servidores,
    }


def env_hermes() -> str:
    carregar_config()
    pares = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", ""),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_ALLOWED_USERS": os.environ.get("TELEGRAM_ALLOWED_USER_IDS", ""),
    }
    return "".join(f"{k}={v.split(' #')[0].strip()}\n" for k, v in pares.items() if v.strip())


def preparar(destino: Path | None = None) -> Path:
    destino = destino or pasta_padrao()
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "SOUL.md").write_text(soul(), encoding="utf-8")
    pasta_skills = destino / "skills"
    for antiga in pasta_skills.glob("quiron-*"):
        shutil.rmtree(antiga)
    skills_hermes(pasta_skills)
    arq_cfg = destino / "config.yaml"
    atual = yaml.safe_load(arq_cfg.read_text(encoding="utf-8")) if arq_cfg.exists() else {}
    atual = atual or {}
    atual.update(config_hermes())  # preserva o resto do que o Hermes já tiver gravado
    arq_cfg.write_text(yaml.safe_dump(atual, allow_unicode=True, sort_keys=False), encoding="utf-8")
    arq_env = destino / ".env"
    arq_env.write_text(env_hermes(), encoding="utf-8")
    try:
        arq_env.chmod(0o600)
    except OSError:
        pass
    return destino


def main() -> None:
    d = preparar()
    print(f"Hermes do Quíron preparado em {d}\nTeste: HERMES_HOME={d} hermes chat -q \"faça meu briefing\"")
