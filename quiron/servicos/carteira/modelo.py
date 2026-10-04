"""Carteira: posições, classes de ativos, perfis de referência e premissas (Fase 8).

Cliente sempre como CLI-XXX. Uma posição tem valor em R$ (ou quantidade × cotação do dia) e, se souber, custo e data
de aplicação (para IR no rebalanceamento) e vencimento/taxa (para duration e stress).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import yaml

from quiron.nucleo.config import PASTA_CONFIG

# id → (nome, proxy de risco, duration padrão em anos para renda fixa)
CLASSES: dict[str, dict[str, Any]] = {
    "pos_fixado": {"nome": "Pós-fixado / caixa", "proxy": "CDI", "duration": 0.0},
    "prefixado": {"nome": "Prefixado", "proxy": "PRE3", "duration": 3.0},
    "inflacao": {"nome": "Inflação (IPCA+)", "proxy": "IPCA7", "duration": 7.0},
    "multimercado": {"nome": "Multimercado", "proxy": "MULTI", "duration": 0.0},
    "acoes": {"nome": "Ações Brasil", "proxy": "IBOV", "duration": 0.0},
    "fii": {"nome": "Fundos imobiliários", "proxy": "FII", "duration": 0.0},
    "internacional": {"nome": "Internacional", "proxy": "SPX_BRL", "duration": 0.0},
    "cripto": {"nome": "Cripto", "proxy": "BTC_BRL", "duration": 0.0},
}
ORDEM = list(CLASSES)
ISENTOS_IR = {"lci", "lca", "cri", "cra", "debenture_incentivada", "poupanca"}
ETFS_RV = {"BOVA11", "BOVV11", "SMAL11", "IVVB11", "SPXI11", "NASD11", "HASH11", "QBTC11", "ECOO11", "DIVO11", "BOVB11",
           "XINA11", "EURP11", "ACWI11", "WRLD11", "GOLD11", "BITH11", "ETHE11", "IMAB11", "FIXA11", "IRFM11", "B5P211"}
INTERNACIONAIS = {"IVVB11", "SPXI11", "NASD11", "XINA11", "EURP11", "ACWI11", "WRLD11"}
CRIPTO_ETF = {"HASH11", "QBTC11", "BITH11", "ETHE11"}
UNITS = {"TAEE11", "SANB11", "KLBN11", "ALUP11", "ENGI11", "BPAC11", "SAPR11", "TIET11", "IGTI11", "CPLE11", "ITUB11"}


@dataclass
class Posicao:
    nome: str
    classe: str
    valor: float = 0.0  # R$ hoje
    ticker: str = ""  # B3 (PETR4, HGLG11, IVVB11…) se houver
    quantidade: float | None = None
    tipo: str = ""  # cdb, lci, tesouro_ipca, acao, fii, etf, fundo, previdencia…
    custo: float | None = None  # R$ investidos (para IR)
    data_aplicacao: date | None = None
    vencimento: date | None = None
    taxa: str = ""  # texto livre: "110% CDI", "IPCA+6,5%", "13,2% a.a."
    isento: bool = False

    def __post_init__(self) -> None:
        if self.classe not in CLASSES:
            raise ValueError(f"{self.nome}: classe “{self.classe}” desconhecida ({', '.join(CLASSES)})")
        self.ticker = self.ticker.upper().strip()
        if self.tipo.lower() in ISENTOS_IR or self.classe == "fii":
            self.isento = True  # rendimento isento para PF (FII: rendimentos; ganho de capital é tributado)

    def anos_ate_vencimento(self, hoje: date | None = None) -> float | None:
        if not self.vencimento:
            return None
        return max(0.0, (self.vencimento - (hoje or date.today())).days / 365.25)

    def duration(self, hoje: date | None = None) -> float:
        """Duration (anos) aproximada para stress de juros. Pós-fixado ≈ 0; prefixado/IPCA+ sem cupom ≈ prazo."""
        if self.classe not in {"prefixado", "inflacao"}:
            return 0.0
        prazo = self.anos_ate_vencimento(hoje)
        if prazo is None:
            return CLASSES[self.classe]["duration"]
        if "juros" in self.tipo.lower() or "semestra" in self.nome.lower():
            return prazo * 0.72  # títulos com cupom semestral têm duration menor que o prazo (aprox.)
        return prazo


@dataclass
class Carteira:
    nome: str
    posicoes: list[Posicao]
    perfil: str = ""  # conservador | moderado | arrojado
    cliente: str = ""  # CLI-XXX
    avisos: list[str] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(p.valor for p in self.posicoes)

    def pesos_por_classe(self) -> dict[str, float]:
        total = self.total or 1
        pesos = {c: 0.0 for c in ORDEM}
        for p in self.posicoes:
            pesos[p.classe] += p.valor / total
        return pesos

    def como_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for p in d["posicoes"]:
            for k in ("data_aplicacao", "vencimento"):
                if p[k]:
                    p[k] = p[k].isoformat()
        return d

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Carteira":
        posicoes = []
        for p in d.get("posicoes", []):
            p = dict(p)
            for k in ("data_aplicacao", "vencimento"):
                if p.get(k) and isinstance(p[k], str):
                    p[k] = _data(p[k])
            posicoes.append(Posicao(**{k: v for k, v in p.items() if k in Posicao.__dataclass_fields__}))
        return cls(d.get("nome", "Carteira"), posicoes, d.get("perfil", ""), d.get("cliente", ""), d.get("avisos", []))


def _data(texto: str) -> date | None:
    texto = texto.strip()
    if not texto:
        return None
    if re.fullmatch(r"\d{4}", texto):
        return date(int(texto), 12, 31)
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto):
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", texto):
        return date(int(m.group(2)), int(m.group(1)), 15)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", texto):
        return date(int(m.group(1)), int(m.group(2)), 15)
    return date.fromisoformat(texto[:10])


def classe_por_ticker(ticker: str) -> str | None:
    """Classe provável de um ticker da B3 (o usuário/agente pode corrigir)."""
    t = ticker.upper()
    if t in UNITS:
        return "acoes"
    if t in INTERNACIONAIS or t.endswith("34") or t.endswith("39"):  # BDRs e ETFs de índices globais
        return "internacional"
    if t in CRIPTO_ETF:
        return "cripto"
    if t in {"IMAB11", "B5P211"}:
        return "inflacao"
    if t in {"IRFM11", "FIXA11"}:
        return "prefixado"
    if t in ETFS_RV:
        return "acoes"
    if re.fullmatch(r"[A-Z]{4}(3|4|5|6)", t):
        return "acoes"
    if re.fullmatch(r"[A-Z]{4}11", t):
        return "fii"  # a maioria dos "11" fora da lista de ETFs/units é FII — confira units (TAEE11, SANB11…)
    return None


def perfis() -> dict[str, Any]:
    return yaml.safe_load((PASTA_CONFIG / "alocacao_perfis.yaml").read_text(encoding="utf-8"))["perfis"]


def premissas() -> dict[str, Any]:
    return yaml.safe_load((PASTA_CONFIG / "premissas_carteira.yaml").read_text(encoding="utf-8"))
