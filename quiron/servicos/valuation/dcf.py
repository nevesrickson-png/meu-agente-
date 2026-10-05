"""DCF (fluxo de caixa livre da firma), custo de capital, múltiplos, cenários, sensibilidade e DCF reverso.

Custo de capital em dólar convertido para reais pela paridade de inflação (método de Damodaran):
Ke(US$) = Treasury 10 anos + β alavancado × ERP madura + risco-país; Kd(US$) = Treasury + spread do país + spread do
rating sintético (cobertura de juros); conversão: (1 + taxa US$) × (1 + IPCA longo) ÷ (1 + inflação EUA) − 1.
Projeção: receita cresce do CAGR histórico até o g da perpetuidade; margem EBIT, capex, depreciação e capital de giro
pelas médias históricas; perpetuidade com reinvestimento = g ÷ ROIC (crescimento coerente com o retorno).
Toda premissa sai com a fonte no relatório. Uso interno — não constitui relatório de análise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from quiron.nucleo.config import ler_yaml
from quiron.servicos.valuation.cvm_cias import Empresa, Periodo


def config() -> dict[str, Any]:
    return ler_yaml("valuation") or {}


# ---------------------------------------------------------------- mercado (insumos com fonte)
@dataclass
class Mercado:
    rf_eua: float  # Treasury 10 anos (decimal)
    erp_madura: float  # prêmio de risco de ações de mercado maduro
    risco_pais: float  # CRP do Brasil
    spread_pais: float  # spread de default do país (dívida)
    inflacao_br: float  # IPCA de longo prazo
    inflacao_eua: float
    beta_desalavancado: float
    industria: str
    fontes: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def _linha_damodaran(dataset: str, aba: str, coluna_chave: str, valor_chave: str) -> dict[str, Any] | None:
    from quiron.servicos.mercado import abertos

    abas, _ = abertos.damodaran(dataset)
    df = abas[aba].dropna(how="all")
    cab = None
    for _, linha in df.iterrows():
        valores = [str(v).strip() for v in linha.tolist()]
        if cab is None and coluna_chave in valores:
            cab = valores
            continue
        if cab and str(linha.iloc[cab.index(coluna_chave)]).strip().lower() == valor_chave.lower():
            return {c: v for c, v in zip(cab, linha.tolist())}
    return None


def industria_damodaran(e: Empresa, forcar: str = "") -> str:
    if forcar:
        return forcar
    cfg = config()
    setor = e.setor.upper()
    for regra in cfg.get("setores_damodaran", []):
        if any(p.upper() in setor for p in regra["contem"]):
            return regra["industria"]
    return cfg.get("padrao_damodaran", "Total Market (without financials)")


def _pc(v: float) -> str:
    return f"{v * 100:.2f}".replace(".", ",") + "%"


def mercado_atual(industria: str) -> Mercado:
    from quiron.servicos.mercado import abertos, bcb

    cfg = config()["custo_capital"]
    fontes, avisos = [], []
    try:
        import yfinance as yf

        rf = float(yf.Ticker("^TNX").history(period="10d")["Close"].dropna().iloc[-1]) / 100
        fontes.append(f"📊 Yahoo Finance (^TNX) — Treasury 10 anos {_pc(rf)} em {date.today():%d/%m/%Y}")
    except Exception as e:  # noqa: BLE001
        rf = 0.045
        avisos.append(f"Treasury indisponível ({type(e).__name__}): usei 4,5% (premissa manual).")
    br = _linha_damodaran("premio_pais", "ERPs by country", "Country", "Brazil") or {}
    try:
        def pct_(chaves: tuple[str, ...]) -> float:
            for k, v in br.items():
                if any(c.lower() in k.lower() for c in chaves):
                    return float(v)
            raise KeyError(chaves)

        erp_total = pct_(("Total Equity Risk Premium", "Equity Risk Premium"))
        crp = pct_(("Country Risk Premium",))
        spread = pct_(("Adj. Default Spread", "Default Spread"))
        erp_madura = erp_total - crp
    except (KeyError, ValueError, TypeError):
        erp_madura, crp, spread = 0.0433, 0.0324, 0.0213
        avisos.append("Damodaran (ctryprem) sem a linha do Brasil: usei ERP madura 4,33%, CRP 3,24%, spread 2,13%.")
    _, fonte_d = abertos.damodaran("premio_pais")
    fontes.append(f"{fonte_d} — Brasil: ERP madura {_pc(erp_madura)}, risco-país {_pc(crp)}, spread soberano {_pc(spread)}")
    linha = _linha_damodaran("betas_emergentes", "Industry Averages", "Industry Name", industria) or {}
    beta_u = None
    for k, v in linha.items():
        if "unlevered beta corrected for cash" in k.lower():
            beta_u = float(v)
    if beta_u is None:
        beta_u = 1.0
        avisos.append(f"Indústria “{industria}” não achada nos betas do Damodaran: β desalavancado 1,0.")
    _, fonte_b = abertos.damodaran("betas_emergentes")
    fontes.append(f"{fonte_b} — {industria}: β desalavancado (corrigido por caixa) " + f"{beta_u:.2f}".replace(".", ","))
    try:
        ano = date.today().year + 3
        ipca = bcb.focus("ipca", ano).mediana / 100
        fontes.append(f"📊 Banco Central (Focus) — IPCA {ano}: {_pc(ipca)} (inflação de longo prazo)")
    except Exception:  # noqa: BLE001
        ipca = 0.035
        avisos.append("Focus indisponível: IPCA de longo prazo 3,5% (premissa manual).")
    return Mercado(rf, erp_madura, crp, spread, ipca, float(cfg["inflacao_eua"]), beta_u, industria, fontes, avisos)


# ---------------------------------------------------------------- histórico
@dataclass
class Historico:
    anos: list[str]
    receita: list[float]
    margem_ebit: float
    margem_ebitda: float
    capex_receita: float
    depreciacao_receita: float
    giro_receita: float
    aliquota_efetiva: float
    cagr_receita: float
    roic: float
    tabela: list[list]  # por ano: receita, ebitda, ebit, lucro, margens, capex, fco


def historico(anuais: list[Periodo], n: int) -> Historico:
    ult = anuais[-n:]
    soma = lambda k, ps=ult: sum(p[k] for p in ps)  # noqa: E731
    rec = soma("receita") or 1.0
    lair = soma("lair")
    efetiva = -soma("ir") / lair if lair > 0 else 0.34
    base = anuais[-n - 1] if len(anuais) > n else anuais[0]
    anos_cagr = len(anuais[anuais.index(base):]) - 1 or 1
    cagr = (anuais[-1]["receita"] / base["receita"]) ** (1 / anos_cagr) - 1 if base["receita"] > 0 else 0.0
    roics = []
    for p in ult:
        investido = p["pl"] + p["divida_liquida"]
        if investido > 0:
            roics.append(p["ebit"] * (1 - 0.34) / investido)
    tabela = [[p.rotulo, p["receita"], p["ebitda"], p["ebit"], p["lucro_controladores"],
               p["ebit"] / p["receita"] * 100 if p["receita"] else None, p["capex"], p["fco"], p["divida_liquida"]]
              for p in anuais]
    return Historico([p.rotulo for p in anuais], [p["receita"] for p in anuais], soma("ebit") / rec, soma("ebitda") / rec,
                     soma("capex") / rec, soma("depreciacao") / rec, ult[-1]["capital_giro"] / (ult[-1]["receita"] or 1.0),
                     max(0.0, min(0.5, efetiva)), cagr, sum(roics) / len(roics) if roics else 0.10, tabela)


# ---------------------------------------------------------------- custo de capital
@dataclass
class CustoCapital:
    beta_alavancado: float
    ke_usd: float
    ke: float
    cobertura: float | None
    rating: str
    kd_usd: float
    kd: float
    kd_liquido: float
    peso_equity: float
    wacc: float
    valor_mercado: float
    divida: float


def _brl(taxa_usd: float, m: Mercado) -> float:
    return (1 + taxa_usd) * (1 + m.inflacao_br) / (1 + m.inflacao_eua) - 1


def custo_capital(base: Periodo, valor_mercado: float, m: Mercado) -> CustoCapital:
    cfg = config()["custo_capital"]
    t = float(cfg["ir_beneficio_divida"])
    divida = base["divida_bruta"] + base["arrendamentos"]
    de = divida / valor_mercado if valor_mercado > 0 else 0.0
    beta = min(cfg["beta_maximo"], max(cfg["beta_minimo"], m.beta_desalavancado * (1 + (1 - t) * de)))
    ke_usd = m.rf_eua + beta * m.erp_madura + m.risco_pais
    desp = abs(base["despesas_financeiras"])
    cobertura = base["ebit"] / desp if desp > 0 else None
    faixa = next(f for f in cfg["spreads_cobertura"] if (cobertura if cobertura is not None else 99) >= f["cobertura_min"])
    kd_usd = m.rf_eua + m.spread_pais + faixa["spread"]
    peso_e = valor_mercado / (valor_mercado + divida) if valor_mercado + divida > 0 else 1.0
    ke, kd = _brl(ke_usd, m), _brl(kd_usd, m)
    wacc = peso_e * ke + (1 - peso_e) * kd * (1 - t)
    return CustoCapital(beta, ke_usd, ke, cobertura, faixa["rating"], kd_usd, kd, kd * (1 - t), peso_e, wacc, valor_mercado, divida)


# ---------------------------------------------------------------- DCF
@dataclass
class Premissas:
    crescimento_inicial: float
    crescimento_perpetuo: float
    margem_ebit: float
    aliquota: float
    capex_receita: float
    depreciacao_receita: float
    giro_receita: float
    roic_perpetuo: float
    anos: int


@dataclass
class Resultado:
    premissas: Premissas
    wacc: float
    projecao: list[dict]
    valor_terminal: float
    vp_fluxos: float
    vp_terminal: float
    ev: float
    divida_liquida: float
    minoritarios: float
    equity: float
    acoes: float
    por_acao: float

    @property
    def peso_terminal(self) -> float:
        return self.vp_terminal / self.ev if self.ev else 0.0


def projetar(receita_base: float, p: Premissas, wacc: float, divida_liquida: float, minoritarios: float,
             acoes: float) -> Resultado:
    if wacc <= p.crescimento_perpetuo + 0.005:
        raise ValueError("WACC precisa ser maior que o crescimento da perpetuidade")
    proj, rec_ant, vp = [], receita_base, 0.0
    n = p.anos
    for t in range(1, n + 1):
        g = p.crescimento_inicial + (p.crescimento_perpetuo - p.crescimento_inicial) * (t - 1) / max(1, n - 1)
        rec = rec_ant * (1 + g)
        ebit = rec * p.margem_ebit
        nopat = ebit * (1 - p.aliquota)
        dep = rec * p.depreciacao_receita
        capex = rec * p.capex_receita
        giro = (rec - rec_ant) * p.giro_receita
        fcff = nopat + dep - capex - giro
        fd = 1 / (1 + wacc) ** t
        vp += fcff * fd
        proj.append({"ano": t, "crescimento": g, "receita": rec, "ebit": ebit, "nopat": nopat, "depreciacao": dep,
                     "capex": capex, "capital_giro": giro, "fcff": fcff, "fator": fd, "vp": fcff * fd})
        rec_ant = rec
    nopat_term = proj[-1]["ebit"] * (1 + p.crescimento_perpetuo) * (1 - p.aliquota)
    reinvest = p.crescimento_perpetuo / p.roic_perpetuo if p.roic_perpetuo > 0 else 0.0
    vt = nopat_term * (1 - reinvest) / (wacc - p.crescimento_perpetuo)
    vp_t = vt * proj[-1]["fator"]
    ev = vp + vp_t
    equity = ev - divida_liquida - minoritarios
    return Resultado(p, wacc, proj, vt, vp, vp_t, ev, divida_liquida, minoritarios, equity, acoes,
                     equity / acoes if acoes else 0.0)


def premissas_base(h: Historico, m: Mercado, wacc: float, ajustes: dict[str, Any] | None = None) -> Premissas:
    cfg = config()["projecao"]
    a = ajustes or {}
    g_perp = (1 + m.inflacao_br) * (1 + float(cfg["crescimento_real_perpetuidade"])) - 1
    g0 = a.get("crescimento_inicial")
    if g0 is None:
        g0 = min(cfg["crescimento_inicial_max"], max(cfg["crescimento_inicial_min"], h.cagr_receita))
    roic_p = max(wacc, min(h.roic if h.roic > 0 else wacc, wacc + float(cfg["roic_perpetuidade_premio"])))
    aliq = cfg.get("aliquota_ir", "efetiva")
    if aliq == "efetiva":
        aliq = min(0.34, max(float(cfg.get("aliquota_ir_minima", 0.10)), h.aliquota_efetiva))
    return Premissas(float(g0), float(a.get("crescimento_perpetuo", g_perp)), float(a.get("margem_ebit", h.margem_ebit)),
                     float(a.get("aliquota", aliq)), float(a.get("capex_receita", h.capex_receita)),
                     float(a.get("depreciacao_receita", h.depreciacao_receita)), float(a.get("giro_receita", h.giro_receita)),
                     float(a.get("roic_perpetuo", roic_p)), int(a.get("anos", cfg["anos"])))


def sensibilidade(receita: float, p: Premissas, wacc: float, dl: float, mino: float, acoes: float,
                  passos_wacc=(-0.01, -0.005, 0.0, 0.005, 0.01), passos_g=(-0.01, -0.005, 0.0, 0.005, 0.01)) -> list[list]:
    linhas = []
    for dw in passos_wacc:
        linha = [wacc + dw]
        for dg in passos_g:
            q = Premissas(**{**p.__dict__, "crescimento_perpetuo": p.crescimento_perpetuo + dg})
            try:
                linha.append(projetar(receita, q, wacc + dw, dl, mino, acoes).por_acao)
            except ValueError:
                linha.append(None)
        linhas.append(linha)
    return linhas


def dcf_reverso(receita: float, p: Premissas, wacc: float, dl: float, mino: float, acoes: float, preco: float) -> float | None:
    """Crescimento inicial que faz o DCF valer o preço de hoje (o que o mercado está "pedindo")."""
    def valor(g0: float) -> float:
        return projetar(receita, Premissas(**{**p.__dict__, "crescimento_inicial": g0}), wacc, dl, mino, acoes).por_acao

    lo, hi = -0.15, 1.0
    if not (valor(lo) <= preco <= valor(hi)):
        return None
    for _ in range(60):
        meio = (lo + hi) / 2
        lo, hi = (meio, hi) if valor(meio) < preco else (lo, meio)
    return (lo + hi) / 2


def wacc_implicito(receita: float, p: Premissas, dl: float, mino: float, acoes: float, preco: float) -> float | None:
    """Custo de capital que faz o DCF (premissas base) valer o preço de hoje."""
    def valor(w: float) -> float:
        return projetar(receita, Premissas(**{**p.__dict__, "roic_perpetuo": max(p.roic_perpetuo, w)}), w, dl, mino,
                        acoes).por_acao

    lo, hi = p.crescimento_perpetuo + 0.006, 0.40
    try:
        if not (valor(hi) <= preco <= valor(lo)):
            return None
    except ValueError:
        return None
    for _ in range(60):
        meio = (lo + hi) / 2
        lo, hi = (meio, hi) if valor(meio) > preco else (lo, meio)
    return (lo + hi) / 2


# ---------------------------------------------------------------- múltiplos
@dataclass
class Multiplos:
    preco: float
    valor_mercado: float
    ev: float
    pl: float | None  # preço/lucro
    ev_ebitda: float | None
    p_vp: float | None
    dy: float | None
    roe: float | None
    margem_ebitda: float | None
    margem_liquida: float | None
    divida_liquida_ebitda: float | None


def multiplos(base: Periodo, preco: float, acoes: float, dividendos_12m: float | None = None) -> Multiplos:
    vm = preco * acoes
    ev = vm + base["divida_liquida"] + base["minoritarios"]
    pl_controladores = base["pl"] - base["minoritarios"]
    lucro = base["lucro_controladores"]
    div = lambda a, b: a / b if b and b > 0 else None  # noqa: E731
    return Multiplos(preco, vm, ev, div(vm, lucro), div(ev, base["ebitda"]), div(vm, pl_controladores),
                     div(dividendos_12m, preco) if dividendos_12m is not None else None, div(lucro, pl_controladores),
                     div(base["ebitda"], base["receita"]), div(lucro, base["receita"]),
                     base["divida_liquida"] / base["ebitda"] if base["ebitda"] > 0 else None)


def cagr(a: float, b: float, anos: float) -> float | None:
    if a <= 0 or b <= 0 or anos <= 0:
        return None
    return math.exp(math.log(b / a) / anos) - 1
