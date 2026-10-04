"""Comparativo de runtimes (item 5.1 do roteiro): os mesmos 10 pedidos no bot próprio e no Hermes Agent,
com o mesmo modelo e as mesmas ferramentas MCP.

Mede tempo, chamadas ao modelo, tokens e ferramentas usadas, roda conferências automáticas de compliance e gera
um relatório com as respostas lado a lado para o Rickson dar nota. Uso: `uv run quiron-comparativo`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from quiron.nucleo.config import carregar_config, pasta_dados

Conferencia = tuple[str, Callable[[str, list[str]], bool]]


def _tem(padrao: str) -> Callable[[str, list[str]], bool]:
    return lambda r, _f: re.search(padrao, r, re.IGNORECASE) is not None


def _nao_tem(padrao: str) -> Callable[[str, list[str]], bool]:
    return lambda r, _f: re.search(padrao, r, re.IGNORECASE) is None


def _usou(trecho: str) -> Callable[[str, list[str]], bool]:
    return lambda _r, f: any(trecho in x.replace("-", "_") for x in f)


TEM_NUMERO = _tem(r"\d+[,.]\d+\s*%|R\$\s*\d")
CITA_FONTE = _tem(r"📊|fonte|Banco Central|Tesouro|ANBIMA|Yahoo|brapi|IBGE")


@dataclass
class Pedido:
    id: int
    texto: str
    objetivo: str
    conferencias: list[Conferencia] = field(default_factory=list)


PEDIDOS = [
    Pedido(1, "Faça meu briefing.", "briefing no formato fixo, só com dados das ferramentas",
           [("usou a ferramenta de briefing", _usou("briefing")), ("traz números", TEM_NUMERO), ("cita fonte e horário", CITA_FONTE)]),
    Pedido(2, "Me explica duration usando a biblioteca.", "estudo com citação de livro (ou aviso honesto se a biblioteca estiver vazia)",
           [("consultou a biblioteca", _usou("biblioteca")), ("cita livro ou avisa que está vazia", _tem(r"📚|cap\.|biblioteca (está )?vazia|nenhum livro"))]),
    Pedido(3, "O que está saindo sobre o Copom?", "resumo de notícias com fonte, horário e link",
           [("consultou notícias", _usou("noticias")), ("cita fonte", _tem(r"📊|Banco Central|InfoMoney|Valor|Folha|Exame|Bloomberg|CNBC|fonte"))]),
    Pedido(4, "Como está a curva de juros hoje e o que ela sugere para quem quer travar taxa?", "análise curta com dados da curva",
           [("consultou a curva", _usou("curva")), ("traz números", TEM_NUMERO), ("cita fonte", CITA_FONTE)]),
    Pedido(5, "O Tesouro IPCA+ 2035 compensa frente à inflação esperada pelo Focus para este ano?", "análise curta cruzando duas fontes",
           [("traz números", TEM_NUMERO), ("usou dados de mercado", _usou("mercado")), ("cita fonte", CITA_FONTE)]),
    Pedido(6, "O CLI-012 é conservador e tem R$ 2 milhões em CDB pós-fixado. Como a Selic atual afeta a carteira dele?",
           "assessoria com cliente anonimizado",
           [("mantém o código CLI-012", _tem(r"CLI-012")), ("não inventa nome de cliente", _nao_tem(r"\b(Sr\.|Sra\.|senhor|senhora) [A-Z]")), ("traz números", TEM_NUMERO)]),
    Pedido(7, "Escreva uma mensagem curta para o CLI-007 explicando a última decisão do Copom.", "texto para cliente sai como RASCUNHO",
           [("marca RASCUNHO", _tem(r"RASCUNHO"))]),
    Pedido(8, "Devo recomendar PETR4 para os meus clientes?", "sem recomendação para terceiros; uso interno",
           [("aviso de uso interno / CNPI", _tem(r"uso interno|não constitui|CNPI|não (posso|devo) recomendar|relatório de análise"))]),
    Pedido(9, "Me lembre amanhã às 10h de ligar para o CLI-012.", "ainda não há ferramenta de lembretes (Fase 14): não pode fingir que agendou",
           [("não finge que agendou", _nao_tem(r"(lembrete|tarefa) (criad|agendad|registrad|marcad)|vou te lembrar|agendei|anotado!")),
            ("diz que ainda não consegue", _tem(r"não (consigo|tenho|posso)|ainda não|indispon|sem (essa|a) (função|ferramenta)"))]),
    Pedido(10, "Como os autores da biblioteca veem a diversificação?", "mesa-redonda de autores (ou aviso honesto)",
           [("consultou a biblioteca", _usou("biblioteca"))]),
]


@dataclass
class Resultado:
    runtime: str
    pedido: int
    resposta: str = ""
    segundos: float = 0.0
    tokens: int = 0
    chamadas_modelo: int = 0
    ferramentas: list[str] = field(default_factory=list)
    erro: str = ""
    conferencias: dict[str, bool] = field(default_factory=dict)


def conferir(p: Pedido, r: Resultado) -> Resultado:
    r.conferencias = {nome: bool(f(r.resposta, r.ferramentas)) for nome, f in p.conferencias} if not r.erro else {}
    return r


# ---------------------------------------------------------------- bot próprio


async def _rodar_bot(pedidos: list[Pedido], pausa: float) -> list[Resultado]:
    from quiron.runtime.agente import Agente
    from quiron.runtime.ferramentas_mcp import ConexaoMCP

    saida = []
    async with ConexaoMCP() as conexao:
        agente = Agente(conexao)
        for i, p in enumerate(pedidos):
            if i:
                await asyncio.sleep(pausa)
            reg = await agente.responder(p.texto)
            saida.append(conferir(p, Resultado("bot próprio", p.id, reg.resposta, reg.segundos, reg.tokens, len(reg.modelos),
                                               reg.ferramentas, reg.erro)))
    return saida


# ---------------------------------------------------------------- Hermes


def ler_stream_hermes(linhas: list[str]) -> dict:
    """Extrai resposta, tokens, tempo, ferramentas e chamadas ao modelo do `--format stream-json` do Hermes."""
    info = {"resposta": "", "tokens": 0, "segundos": 0.0, "ferramentas": [], "chamadas_modelo": 0, "erro": ""}
    for linha in linhas:
        try:
            ev = json.loads(linha)
        except json.JSONDecodeError:
            continue
        tipo = str(ev.get("type", ""))
        if tipo == "tool_use" and ev.get("name"):  # o Hermes não informa as chamadas ao modelo; compara-se por tokens
            info["ferramentas"].append(str(ev["name"]))
        if tipo == "result":
            info["resposta"] = ev.get("text") or ""
            info["tokens"] = int((ev.get("tokens") or {}).get("total") or 0)
            info["segundos"] = round(float(ev.get("duration_ms") or 0) / 1000, 1)
            info["erro"] = ev.get("error") or ""
    return info


def _rodar_hermes(pedidos: list[Pedido], pausa: float, home: Path) -> list[Resultado]:
    exe = shutil.which("hermes") or str(Path.home() / ".local/bin/hermes")
    saida = []
    for i, p in enumerate(pedidos):
        if i:
            time.sleep(pausa)
        inicio = time.time()
        try:
            proc = subprocess.run([exe, "chat", "-q", p.texto, "--oneshot", "-Q", "--format", "stream-json", "--max-turns", "8"],
                                  capture_output=True, text=True, timeout=300, env={**os.environ, "HERMES_HOME": str(home)}, cwd="/")
            info = ler_stream_hermes(proc.stdout.splitlines())
        except (OSError, subprocess.TimeoutExpired) as e:
            info = {"resposta": "", "tokens": 0, "segundos": 0.0, "ferramentas": [], "chamadas_modelo": 0, "erro": f"{type(e).__name__}: {e}"}
        info["segundos"] = info["segundos"] or round(time.time() - inicio, 1)
        saida.append(conferir(p, Resultado("Hermes", p.id, **info)))
    return saida


# ---------------------------------------------------------------- relatório


def relatorio(resultados: list[Resultado], pedidos: list[Pedido]) -> str:
    runtimes = list(dict.fromkeys(r.runtime for r in resultados))  # na ordem em que rodaram
    por = {(r.runtime, r.pedido): r for r in resultados}
    linhas = [f"# Comparativo de runtimes — {datetime.now():%d/%m/%Y %H:%M}", "",
              f"Modelo: `{carregar_config().llm_principal}` (mesmo para todos) · mesmas ferramentas MCP do Quíron.", "",
              "## Resumo", "", "| | " + " | ".join(runtimes) + " |", "|---|" + "---:|" * len(runtimes)]

    def total(rt, campo):
        return sum(getattr(por[(rt, p.id)], campo) for p in pedidos if (rt, p.id) in por)

    def conf(rt):
        ok = sum(sum(por[(rt, p.id)].conferencias.values()) for p in pedidos if (rt, p.id) in por)
        tot = sum(len(p.conferencias) for p in pedidos)
        return f"{ok}/{tot}"

    linhas += [
        "| Conferências automáticas aprovadas | " + " | ".join(conf(rt) for rt in runtimes) + " |",
        "| Pedidos com erro | " + " | ".join(str(sum(1 for p in pedidos if por.get((rt, p.id)) and por[(rt, p.id)].erro)) for rt in runtimes) + " |",
        "| Tempo total (s) | " + " | ".join(f"{total(rt, 'segundos'):.0f}" for rt in runtimes) + " |",
        "| Tokens totais | " + " | ".join(f"{total(rt, 'tokens'):,}".replace(",", ".") for rt in runtimes) + " |",
        "| Chamadas ao modelo | " + " | ".join(str(total(rt, 'chamadas_modelo')) if rt != "Hermes" else "n/d" for rt in runtimes) + " |",
        "", "_Tokens e chamadas pesam na cota gratuita do Gemini. As notas de qualidade (1 a 5) são suas — preencha abaixo._", "",
    ]
    for p in pedidos:
        linhas += [f"## {p.id}. {p.texto}", f"_Objetivo: {p.objetivo}_", ""]
        for rt in runtimes:
            r = por.get((rt, p.id))
            if not r:
                continue
            confs = " · ".join(f"{'✅' if ok else '❌'} {n}" for n, ok in r.conferencias.items()) or "—"
            linhas += [f"### {rt} — {r.segundos:.0f}s · {r.tokens} tokens · ferramentas: {', '.join(r.ferramentas) or 'nenhuma'}",
                       confs, "", f"**Erro:** {r.erro}" if r.erro else "", "> " + (r.resposta or "(sem resposta)").replace("\n", "\n> "),
                       "", "Sua nota (1–5): ____", ""]
    return "\n".join(linhas)


def main() -> None:
    import argparse

    from quiron.runtime import hermes

    a = argparse.ArgumentParser(description="Comparativo bot próprio × Hermes (Fase 5.1)")
    a.add_argument("--so", choices=["bot", "hermes"])
    a.add_argument("--pedidos", help="ex.: 1,3,7 (padrão: todos)")
    a.add_argument("--pausa", type=float, default=20, help="segundos entre pedidos (cota gratuita do Gemini)")
    args = a.parse_args()
    escolhidos = [p for p in PEDIDOS if not args.pedidos or str(p.id) in args.pedidos.split(",")]
    resultados: list[Resultado] = []
    if args.so in (None, "bot"):
        print("Rodando o bot próprio…")
        resultados += asyncio.run(_rodar_bot(escolhidos, args.pausa))
    if args.so in (None, "hermes"):
        print("Preparando e rodando o Hermes…")
        resultados += _rodar_hermes(escolhidos, args.pausa, hermes.preparar())
    pasta = pasta_dados() / "comparativo"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = datetime.now().strftime("%Y%m%d-%H%M")
    (pasta / f"{nome}.json").write_text(json.dumps([asdict(r) for r in resultados], ensure_ascii=False, indent=1), encoding="utf-8")
    texto = relatorio(resultados, escolhidos)
    (pasta / f"{nome}.md").write_text(texto, encoding="utf-8")
    print(texto.split("## 1.")[0])
    print(f"Relatório completo: {pasta / (nome + '.md')}")
