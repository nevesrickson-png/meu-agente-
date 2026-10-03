"""Leitura de `config/regras_mercado.yaml` com aviso de verificação.

Cada bloco tem `verificado_em`. Sem data → "não verificado". Mais de 90 dias → "verificar de novo".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from quiron.nucleo.config import ler_yaml

PRAZO_DIAS = 90


@dataclass(frozen=True)
class SituacaoBloco:
    bloco: str
    verificado_em: date | None
    dias: int | None
    ok: bool
    aviso: str


def carregar_regras() -> dict[str, Any]:
    return ler_yaml("regras_mercado") or {}


def situacao(regras: dict[str, Any] | None = None, hoje: date | None = None) -> list[SituacaoBloco]:
    regras = carregar_regras() if regras is None else regras
    hoje = hoje or date.today()
    resultado = []
    for bloco, conteudo in regras.items():
        if not isinstance(conteudo, dict):
            continue
        valor = conteudo.get("verificado_em")
        if isinstance(valor, str) and valor.strip():
            valor = date.fromisoformat(valor.strip())
        if not isinstance(valor, date):
            resultado.append(SituacaoBloco(bloco, None, None, False, f"{bloco}: NÃO verificado — confira antes de usar"))
            continue
        dias = (hoje - valor).days
        if dias > PRAZO_DIAS:
            aviso = f"{bloco}: verificado há {dias} dias (mais de {PRAZO_DIAS}) — confira de novo"
            resultado.append(SituacaoBloco(bloco, valor, dias, False, aviso))
        else:
            resultado.append(SituacaoBloco(bloco, valor, dias, True, f"{bloco}: verificado há {dias} dias"))
    return resultado


def avisos(regras: dict[str, Any] | None = None, hoje: date | None = None) -> list[str]:
    """Só os blocos que precisam de atenção."""
    return [s.aviso for s in situacao(regras, hoje) if not s.ok]
