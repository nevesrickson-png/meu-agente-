"""Permissões por ferramenta e hooks de compliance (ideias do Claude Code), configurados em `config/agente.yaml`.

- Permissão: livre (o agente usa sozinho), confirmar (vira pedido de aprovação com botão ✅/❌) ou bloqueado.
- Hooks pós-resposta: texto para cliente sai como RASCUNHO; análise/recomendação de ação ganha o rodapé de uso interno.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quiron.nucleo.config import ler_yaml, pasta_dados

RODAPE = "_Uso interno — não constitui relatório de análise._"
MARCA_RASCUNHO = "📝 RASCUNHO — revise antes de enviar ao cliente."


def config() -> dict:
    return ler_yaml("agente") or {}


def politica(nome_ferramenta: str) -> str:
    p = config().get("permissoes") or {}
    regras = p.get("regras") or {}
    if nome_ferramenta in regras:
        return regras[nome_ferramenta]
    servidor = nome_ferramenta.split("__")[0]
    return regras.get(f"{servidor}__*", p.get("padrao", "livre"))


@dataclass
class Pendencia:
    id: int
    ferramenta: str
    argumentos: dict[str, Any]
    resumo: str


class Aprovacoes:
    """Ações que esperam o ✅ do Rickson."""

    def __init__(self, caminho: Path | None = None):
        caminho = caminho or pasta_dados() / "agenda.db"
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        with self.con:
            self.con.execute("CREATE TABLE IF NOT EXISTS aprovacoes (id INTEGER PRIMARY KEY, ferramenta TEXT, argumentos TEXT, resumo TEXT, "
                             "situacao TEXT DEFAULT 'pendente', criado_em TEXT)")

    def criar(self, ferramenta: str, argumentos: dict[str, Any], resumo: str) -> Pendencia:
        with self.con:
            cur = self.con.execute("INSERT INTO aprovacoes(ferramenta, argumentos, resumo, criado_em) VALUES (?,?,?,?)",
                                   (ferramenta, json.dumps(argumentos, ensure_ascii=False), resumo, datetime.now(timezone.utc).isoformat()))
        return Pendencia(cur.lastrowid, ferramenta, argumentos, resumo)

    def decidir(self, ident: int, aprovado: bool) -> Pendencia | None:
        linha = self.con.execute("SELECT id, ferramenta, argumentos, resumo FROM aprovacoes WHERE id = ? AND situacao = 'pendente'", (ident,)).fetchone()
        if not linha:
            return None
        with self.con:
            self.con.execute("UPDATE aprovacoes SET situacao = ? WHERE id = ?", ("aprovado" if aprovado else "negado", ident))
        return Pendencia(linha[0], linha[1], json.loads(linha[2]), linha[3])

    def pendentes(self) -> list[Pendencia]:
        return [Pendencia(i, f, json.loads(a), r) for i, f, a, r in
                self.con.execute("SELECT id, ferramenta, argumentos, resumo FROM aprovacoes WHERE situacao = 'pendente' ORDER BY id")]


# ---------------------------------------------------------------- hooks de compliance

_PEDE_TEXTO_CLIENTE = re.compile(
    r"(mensagem|texto|e-?mail|whats(app)?|carta|comunicado|resposta)\b.{0,60}\b(para|pro|pra|aos?|às?|à)\s+"
    r"(?:(?:o|a|os|as|meu|minha|meus|minhas|seu|sua|seus|suas|nosso|nossa|nossos|nossas)\s+)*(clientes?|CLI-\d+)", re.I | re.S)
_RECOMENDA_ACAO = re.compile(r"\b(compra(r)?|vend(a|er)|recomend\w*|preço[- ]alvo|valuation|tese)\b", re.I)
_TICKER = re.compile(r"\b[A-Za-z]{4}(?:3|4|5|6|11|3[1-5]|39)\b")  # inclui BDRs (AAPL34) e "petr4" minúsculo


def _cita_acao(texto: str) -> bool:
    if _TICKER.search(texto):
        return True
    try:  # nomes de empresa da lista das notícias ("Petrobras", "Vale" — com as exceções tipo "vale a pena")
        from quiron.servicos.noticias.classificacao import ativos

        return bool(ativos(texto))
    except Exception:  # noqa: BLE001
        return False


def aplicar_compliance(pedido: str, resposta: str) -> str:
    cfg = config().get("compliance") or {}
    saida = resposta.strip()
    if cfg.get("rascunho_para_cliente", True) and _PEDE_TEXTO_CLIENTE.search(pedido) and "RASCUNHO" not in saida.upper():
        saida = f"{MARCA_RASCUNHO}\n\n{saida}"
    if cfg.get("rodape_uso_interno", True) and _cita_acao(pedido + " " + saida) and _RECOMENDA_ACAO.search(pedido + " " + saida) \
            and "uso interno" not in saida.lower():
        # o rodapé entra ANTES das sugestões "» …" do fim (que viram botões e precisam continuar sendo as últimas linhas)
        m = re.search(r"(?:\n[ \t]*»[^\n]*)+\s*$", saida)
        corpo, sugestoes = (saida[:m.start()].rstrip(), saida[m.start():].rstrip()) if m else (saida, "")
        saida = f"{corpo}\n\n{RODAPE}" + (f"\n{sugestoes}" if sugestoes else "")
    return saida
