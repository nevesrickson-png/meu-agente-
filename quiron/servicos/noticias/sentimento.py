"""Sentimento por léxico (português e inglês do mercado), calculado em Python.

Não é "inteligência": conta palavras positivas e negativas do jargão de mercado, com tratamento simples de negação.
Serve para medir o tom de muitos títulos/posts de uma vez; a interpretação fica com o agente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quiron.servicos.biblioteca.trechos import chave

POSITIVAS = set(
    """alta altas sobe subiu sobem dispara disparou valoriza valorizou valorizacao ganho ganhos lucro lucros recorde
    recordes otimismo otimista melhora melhorou crescimento cresce cresceu forte supera superou acima recupera
    recuperacao alivio avanca avancou positivo positiva corte cortes queda_juros upgrade eleva elevou compra
    rally gain gains rise rises rose surge surged soar beat beats record strong growth upbeat bullish optimism
    recovery rebound upgrade upgraded""".split()
)
NEGATIVAS = set(
    """queda quedas cai caiu caem despenca despencou desvaloriza desvalorizou perda perdas prejuizo crise
    pessimismo pessimista piora piorou recessao fraco fraca abaixo risco riscos tensao temor temores medo
    rebaixa rebaixamento calote default inadimplencia recuperacao_judicial negativo negativa alerta pressao
    incerteza volatilidade fuga inflacao_alta fall falls fell drop drops dropped plunge plunged slump loss losses
    alta_juros weak miss misses recession fear fears crisis downgrade downgraded bearish selloff sell-off risk risks""".split()
)
# radicais (≥ 5 letras) para pegar as variações: "despencam", "valorização", "pressionado"…
RADICAIS_POSITIVOS = ("dispar", "valoriz", "otimis", "recuper", "cresc", "avanc", "melhor", "supera", "recorde", "alivi", "impuls",
                      "rally", "surge", "soar", "rebound", "bullish")
RADICAIS_NEGATIVOS = ("despenc", "desvaloriz", "prejuiz", "pessim", "recess", "rebaix", "inadimpl", "pression", "incert",
                      "volatil", "turbul", "tombo", "derrub", "afund", "plung", "slump", "bearish", "selloff", "downgrad")
NEGACOES = {"nao", "sem", "nem", "nunca", "not", "never"}  # "no" fica de fora: em português é "em + o" ("juros no Brasil")
# expressões de duas palavras normalizadas antes da contagem
_EXPRESSOES = {"recuperacao judicial": "recuperacao_judicial", "queda dos juros": "queda_juros", "queda da selic": "queda_juros",
               "corte de juros": "queda_juros", "inflacao alta": "inflacao_alta",
               "reduz a taxa selic": "queda_juros", "corta a selic": "queda_juros", "corta juros": "queda_juros",
               "eleva a taxa selic": "alta_juros", "eleva a selic": "alta_juros", "sobe juros": "alta_juros",
               "alta dos juros": "alta_juros", "alta da selic": "alta_juros"}


@dataclass
class Tom:
    nota: float  # -1 (muito negativo) a +1 (muito positivo)
    positivas: int
    negativas: int

    @property
    def rotulo(self) -> str:
        if self.positivas + self.negativas == 0:
            return "neutro"
        return "positivo" if self.nota > 0.15 else "negativo" if self.nota < -0.15 else "misto"


def tom(texto: str) -> Tom:
    t = chave(texto)
    for exp, troca in _EXPRESSOES.items():
        t = t.replace(exp, troca)
    palavras = re.findall(r"[a-z_\-]+", t)
    pos = neg = 0
    for i, p in enumerate(palavras):
        sinal = 1 if p in POSITIVAS else -1 if p in NEGATIVAS else 0
        if not sinal and len(p) >= 5:
            sinal = 1 if p.startswith(RADICAIS_POSITIVOS) else -1 if p.startswith(RADICAIS_NEGATIVOS) else 0
        if not sinal:
            continue
        if any(w in NEGACOES for w in palavras[max(0, i - 2) : i]):
            sinal = -sinal
        if sinal > 0:
            pos += 1
        else:
            neg += 1
    total = pos + neg
    return Tom((pos - neg) / total if total else 0.0, pos, neg)


def tom_medio(textos: list[str]) -> Tom:
    toms = [tom(t) for t in textos]
    pos = sum(x.positivas for x in toms)
    neg = sum(x.negativas for x in toms)
    return Tom((pos - neg) / (pos + neg) if pos + neg else 0.0, pos, neg)
