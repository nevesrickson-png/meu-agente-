"""Simulador de patrimônio: as perguntas que todo cliente (e o próprio Rickson) faz.

1. Quanto preciso investir por mês para chegar ao meu objetivo?
2. Quando posso parar de trabalhar (independência financeira)?
3. Em quanto tempo chego a R$ X?
4. Imóvel ou investimentos financeiros?

Tudo em termos REAIS (R$ de hoje, já descontada a inflação) e calculado em Python, com três cenários de retorno
(pessimista/base/otimista) e Monte Carlo para a chance de chegar lá. Premissas em `config/premissas_planejamento.yaml`
(`retorno_real_aa`, `volatilidade_aa`, `retorno_real_usufruto`, `expectativa_vida_plano`, bloco `simulador`).
É simulação com premissas declaradas — nunca promessa de rentabilidade."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from quiron.servicos.planejamento.diagnostico import pmt_para, premissas, taxa_mensal, vp_renda

AVISO = ("Simulação em R$ de hoje (descontada a inflação), com premissas declaradas de retorno, volatilidade e custos. "
         "Não é promessa nem garantia de rentabilidade; resultados reais variam.")


@dataclass
class Entrada:
    patrimonio: float = 0.0           # R$ investidos hoje (sem imóvel de moradia)
    aporte_mensal: float = 0.0        # R$ por mês
    idade: int = 40
    perfil: str = "moderado"          # conservador | moderado | arrojado
    meta: float = 0.0                 # R$ (em valores de hoje) — "chegar a R$ 5 milhões"
    renda_desejada: float = 0.0       # R$/mês para viver de renda (em valores de hoje)
    idade_meta: int | None = None     # idade em que quer chegar à meta / parar de trabalhar
    crescimento_aporte_aa: float = 0.0  # % a.a. real de aumento do aporte
    retorno_real_aa: float | None = None  # None = pelo perfil
    imovel_valor: float = 0.0         # para a comparação imóvel × aplicação
    horizonte_imovel_anos: int = 20

    @classmethod
    def de_dict(cls, d: dict[str, Any]) -> "Entrada":
        campos = cls.__dataclass_fields__
        limpo = {}
        for k, v in (d or {}).items():
            if k not in campos or v in (None, ""):
                continue
            tipo = campos[k].type
            limpo[k] = str(v) if k == "perfil" else int(float(v)) if "int" in str(tipo) else float(v)
        e = cls(**limpo)
        e.validar()
        return e

    def validar(self) -> None:
        if not 14 <= self.idade <= 100:
            raise ValueError("idade entre 14 e 100 anos")
        if self.patrimonio < 0 or self.aporte_mensal < 0 or self.meta < 0 or self.renda_desejada < 0 or self.imovel_valor < 0:
            raise ValueError("valores não podem ser negativos")
        if self.perfil not in {"conservador", "moderado", "arrojado"}:
            raise ValueError("perfil: conservador, moderado ou arrojado")
        if self.idade_meta is not None and self.idade_meta <= self.idade:
            raise ValueError("a idade da meta precisa ser maior que a idade atual")


# ---------------------------------------------------------------- motor
def _premissas() -> tuple[dict, dict]:
    p = premissas()
    return p, p.get("simulador") or {}


def retorno_do_perfil(e: Entrada, p: dict) -> float:
    return e.retorno_real_aa if e.retorno_real_aa is not None else float(p["retorno_real_aa"][e.perfil])


def projetar(patrimonio: float, aporte: float, retorno_aa: float, anos: int, cresc_aporte_aa: float = 0.0) -> list[float]:
    """Patrimônio no fim de cada ano (índice 0 = hoje). Aporte mensal no fim do mês, reajustado a cada 12 meses."""
    i = taxa_mensal(retorno_aa)
    serie, valor, ap = [patrimonio], patrimonio, aporte
    for _ in range(anos):
        for _ in range(12):
            valor = valor * (1 + i) + ap
        ap *= 1 + cresc_aporte_aa / 100
        serie.append(valor)
    return serie


def meses_ate(meta: float, patrimonio: float, aporte: float, retorno_aa: float, cresc_aporte_aa: float = 0.0,
              limite_anos: int = 60) -> int | None:
    if meta <= patrimonio:
        return 0
    i = taxa_mensal(retorno_aa)
    valor, ap = patrimonio, aporte
    for m in range(1, limite_anos * 12 + 1):
        valor = valor * (1 + i) + ap
        if valor >= meta:
            return m
        if m % 12 == 0:
            ap *= 1 + cresc_aporte_aa / 100
    return None


def capital_para_renda(renda_mensal: float, idade_parada: int, p: dict) -> float:
    """Quanto é preciso ter, ao parar, para receber a renda até a idade do plano (consome o capital aos poucos)."""
    meses = max(12, (int(p.get("expectativa_vida_plano", 95)) - idade_parada) * 12)
    return vp_renda(renda_mensal, taxa_mensal(float(p.get("retorno_real_usufruto", 3.0))), meses)


def monte_carlo(patrimonio: float, aporte: float, retorno_aa: float, vol_aa: float, anos: int, n: int = 2000,
                cresc_aporte_aa: float = 0.0, semente: int = 42) -> np.ndarray:
    """Trajetórias anuais (n × anos+1) com retornos mensais lognormais (média real = retorno_aa)."""
    rng = np.random.default_rng(semente)
    mu_m = math.log(1 + retorno_aa / 100) / 12
    sig_m = vol_aa / 100 / math.sqrt(12)
    choques = rng.normal(mu_m - sig_m ** 2 / 2, sig_m, size=(n, anos * 12))
    fatores = np.exp(choques)
    valor = np.full(n, float(patrimonio))
    saida = np.empty((n, anos + 1))
    saida[:, 0] = valor
    ap = aporte
    for m in range(anos * 12):
        valor = valor * fatores[:, m] + ap
        if (m + 1) % 12 == 0:
            saida[:, (m + 1) // 12] = valor
            ap *= 1 + cresc_aporte_aa / 100
    return saida


# ---------------------------------------------------------------- respostas
@dataclass
class Simulacao:
    entrada: dict[str, Any]
    retorno_base: float
    cenarios: dict[str, float]                       # nome → retorno real a.a.
    anos: list[int]                                  # idades no eixo do gráfico
    series: dict[str, list[float]]                   # cenário → patrimônio por ano
    faixa: dict[str, list[float]] = field(default_factory=dict)  # Monte Carlo p10/p50/p90 por ano
    respostas: list[dict[str, Any]] = field(default_factory=list)
    imovel: dict[str, Any] | None = None
    premissas: list[str] = field(default_factory=list)
    aviso: str = AVISO

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def _anos_ate_meta(e: Entrada, retorno: float, horizonte: int) -> int | None:
    m = meses_ate(e.meta, e.patrimonio, e.aporte_mensal, retorno, e.crescimento_aporte_aa, horizonte)
    return None if m is None else m


def simular(e: Entrada, n_simulacoes: int | None = None) -> Simulacao:
    p, cfg = _premissas()
    e.validar()
    base = retorno_do_perfil(e, p)
    vol = float(p["volatilidade_aa"].get(e.perfil, 8.0))
    cen = {k: round(base + float(v), 2) for k, v in (cfg.get("cenarios_pp") or {"pessimista": -1.5, "base": 0, "otimista": 1.5}).items()}
    horizonte_max = int(cfg.get("horizonte_max_anos", 60))
    fim = e.idade_meta or min(max(e.idade + 30, 65), e.idade + horizonte_max)
    anos = max(1, min(fim - e.idade, horizonte_max))
    series = {k: [round(v, 2) for v in projetar(e.patrimonio, e.aporte_mensal, r, anos, e.crescimento_aporte_aa)] for k, r in cen.items()}
    n = n_simulacoes or int(p.get("simulacoes_monte_carlo", 2000))
    mc = monte_carlo(e.patrimonio, e.aporte_mensal, base, vol, anos, n, e.crescimento_aporte_aa)
    faixa = {f"p{q}": [round(float(x), 2) for x in np.percentile(mc, q, axis=0)] for q in (10, 50, 90)}
    sim = Simulacao(asdict(e), base, cen, [e.idade + k for k in range(anos + 1)], series, faixa)
    i_base = taxa_mensal(base)

    # 1) Quanto preciso investir por mês
    if e.meta and (e.idade_meta or anos):
        n_meses = (e.idade_meta - e.idade) * 12 if e.idade_meta else anos * 12
        por_cenario = {k: round(pmt_para(e.meta, e.patrimonio, taxa_mensal(r), n_meses), 2) for k, r in cen.items()}
        sim.respostas.append({"pergunta": "Quanto preciso investir por mês?", "chave": "aporte_necessario",
                              "valor": por_cenario["base"], "cenarios": por_cenario,
                              "texto": f"Para ter {_brl(e.meta)} aos {e.idade + n_meses // 12} anos: {_brl(por_cenario['base'])}/mês "
                                       f"(entre {_brl(por_cenario['otimista'])} e {_brl(por_cenario['pessimista'])} conforme o cenário)."})

    # 2) Quando posso parar de trabalhar
    if e.renda_desejada:
        idade_livre: dict[str, int | None] = {}
        for k, r in cen.items():
            serie = projetar(e.patrimonio, e.aporte_mensal, r, horizonte_max, e.crescimento_aporte_aa)
            idade_livre[k] = next((e.idade + a for a, v in enumerate(serie) if v >= capital_para_renda(e.renda_desejada, e.idade + a, p)), None)
        alvo_idade = idade_livre["base"]
        chance = None
        if alvo_idade is not None:
            anos_alvo = alvo_idade - e.idade
            mc_alvo = mc if anos_alvo <= anos else monte_carlo(e.patrimonio, e.aporte_mensal, base, vol, anos_alvo, n, e.crescimento_aporte_aa)
            chance = round(float((mc_alvo[:, anos_alvo] >= capital_para_renda(e.renda_desejada, alvo_idade, p)).mean()), 3)
        necessario = capital_para_renda(e.renda_desejada, alvo_idade or (e.idade_meta or 65), p)
        txt = (f"Com o aporte atual, a renda de {_brl(e.renda_desejada)}/mês fica garantida a partir dos {alvo_idade} anos "
               f"(cenários: {idade_livre['otimista'] or '—'} a {idade_livre['pessimista'] or 'não alcança'}); "
               f"capital necessário ≈ {_brl(necessario)}." if alvo_idade else
               f"Com o aporte atual, a renda de {_brl(e.renda_desejada)}/mês não é alcançada em {horizonte_max} anos no cenário base.")
        if e.idade_meta:
            n_m = (e.idade_meta - e.idade) * 12
            precisa = pmt_para(capital_para_renda(e.renda_desejada, e.idade_meta, p), e.patrimonio, i_base, n_m)
            txt += f" Para parar aos {e.idade_meta}, o aporte precisaria ser {_brl(precisa)}/mês."
        sim.respostas.append({"pergunta": "Quando posso parar de trabalhar?", "chave": "independencia", "valor": alvo_idade,
                              "cenarios": idade_livre, "chance": chance, "capital_necessario": round(necessario, 2), "texto": txt})

    # 3) Em quanto tempo chego a R$ X
    if e.meta:
        tempos = {k: meses_ate(e.meta, e.patrimonio, e.aporte_mensal, r, e.crescimento_aporte_aa, horizonte_max) for k, r in cen.items()}
        m = tempos["base"]
        chance_fim = round(float((mc[:, -1] >= e.meta).mean()), 3)
        txt = (f"{_brl(e.meta)} em {_tempo(m)} (aos {e.idade + m // 12} anos) no cenário base; "
               f"otimista {_tempo(tempos['otimista'])}, pessimista {_tempo(tempos['pessimista'])}. "
               f"Chance de ter a meta aos {e.idade + anos} anos: {chance_fim:.0%}." if m is not None else
               f"{_brl(e.meta)} não é alcançado em {horizonte_max} anos com o aporte atual (cenário base).")
        sim.respostas.append({"pergunta": f"Em quanto tempo chego a {_brl(e.meta)}?", "chave": "tempo_meta", "valor": m,
                              "cenarios": tempos, "chance_no_horizonte": chance_fim, "texto": txt})

    # 4) Imóvel × investimentos financeiros
    if e.imovel_valor:
        sim.imovel = imovel_x_financeiro(e.imovel_valor, e.horizonte_imovel_anos, base, cfg.get("imovel") or {})
        sim.respostas.append({"pergunta": "Imóvel ou investimentos financeiros?", "chave": "imovel", "valor": sim.imovel["melhor"],
                              "texto": sim.imovel["texto"]})

    im = cfg.get("imovel") or {}
    sim.premissas = [
        f"Retorno real (acima da inflação) do perfil {e.perfil}: {_pct(base)} a.a.; cenários {_pct(cen['pessimista'])} a {_pct(cen['otimista'])}",
        f"Volatilidade para o Monte Carlo: {_pct(vol, 0)} a.a. ({n} simulações)",
        f"Na fase de renda: {_pct(float(p.get('retorno_real_usufruto', 3.0)))} a.a. real, consumindo o capital até os "
        f"{p.get('expectativa_vida_plano', 95)} anos",
        f"Aporte reajustado {_pct(e.crescimento_aporte_aa)} a.a. acima da inflação",
    ] + ([f"Imóvel: aluguel {_pct(float(im.get('aluguel_bruto_aa', 5)))} a.a., vacância {float(im.get('vacancia', .08)):.0%}, custos "
          f"{_pct(float(im.get('custos_aa', 1)))} a.a., IR efetivo {float(im.get('ir_aluguel', .2)):.0%}, valorização real "
          f"{_pct(float(im.get('valorizacao_real_aa', 1)))} a.a., compra {float(im.get('custo_compra', .04)):.0%} e venda "
          f"{float(im.get('custo_venda', .06)):.0%}"] if e.imovel_valor else [])
    return sim


def imovel_x_financeiro(valor: float, anos: int, retorno_fin_aa: float, im: dict[str, Any]) -> dict[str, Any]:
    """Mesmo dinheiro em um imóvel para alugar × em aplicações. Aluguel líquido é reinvestido nas aplicações."""
    aluguel, vac = float(im.get("aluguel_bruto_aa", 5.0)) / 100, float(im.get("vacancia", 0.08))
    custos, ir = float(im.get("custos_aa", 1.0)) / 100, float(im.get("ir_aluguel", 0.20))
    val_aa, compra, venda = float(im.get("valorizacao_real_aa", 1.0)), float(im.get("custo_compra", 0.04)), float(im.get("custo_venda", 0.06))
    capital = valor * (1 + compra)  # o que sai do bolso para comprar
    r = retorno_fin_aa / 100
    imovel_val, caixa = valor, 0.0
    serie_imovel, serie_fin = [round(valor * (1 - venda), 2)], [round(capital, 2)]
    for ano in range(1, anos + 1):
        renda_liq = imovel_val * (aluguel * (1 - vac) * (1 - ir) - custos)
        caixa = caixa * (1 + r) + renda_liq
        imovel_val *= 1 + val_aa / 100
        serie_imovel.append(round(imovel_val * (1 - venda) + caixa, 2))
        serie_fin.append(round(capital * (1 + r) ** ano, 2))
    rend_liq_aa = (aluguel * (1 - vac) * (1 - ir) - custos) * 100
    # valorização real que empata (busca simples)
    def final_com(v):
        iv, cx = valor, 0.0
        for _ in range(anos):
            cx = cx * (1 + r) + iv * (aluguel * (1 - vac) * (1 - ir) - custos)
            iv *= 1 + v / 100
        return iv * (1 - venda) + cx
    lo, hi = -10.0, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if final_com(mid) < serie_fin[-1] else (lo, mid)
    empate = round((lo + hi) / 2, 2)
    melhor = "imóvel" if serie_imovel[-1] > serie_fin[-1] else "investimentos financeiros"
    dif = abs(serie_imovel[-1] - serie_fin[-1])
    texto = (f"Em {anos} anos, {_brl(valor)} em imóvel para alugar viram ≈ {_brl(serie_imovel[-1])} (já vendido, com os aluguéis "
             f"reinvestidos); a mesma quantia ({_brl(capital)} com ITBI/escritura) em aplicações a {_pct(retorno_fin_aa)} real viraria "
             f"≈ {_brl(serie_fin[-1])}. Vantagem: {melhor} (+{_brl(dif)}). O aluguel rende ≈ {_pct(rend_liq_aa)} a.a. líquido; o "
             f"imóvel só empata se valorizar {_pct(empate)} a.a. acima da inflação. Considere também liquidez, concentração e trabalho "
             "de administração (financiamento não incluído).")
    return {"anos": list(range(anos + 1)), "imovel": serie_imovel, "financeiro": serie_fin, "melhor": melhor,
            "rendimento_aluguel_liquido_aa": round(rend_liq_aa, 2), "valorizacao_de_empate_aa": empate, "texto": texto}


# ---------------------------------------------------------------- texto e gráfico (Telegram)
def _brl(v: float | None) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e6:
        return f"R$ {v / 1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {v:,.0f}".replace(",", ".")


def _pct(v: float, casas: int = 1) -> str:
    return f"{v:.{casas}f}".replace(".", ",") + "%"


def _tempo(meses: int | None) -> str:
    if meses is None:
        return "mais de 60 anos"
    a, m = divmod(meses, 12)
    return " e ".join(x for x in [f"{a} ano{'s' if a != 1 else ''}" if a else "", f"{m} mes{'es' if m != 1 else ''}" if m else ""] if x) or "já"


def texto(sim: Simulacao) -> str:
    e = sim.entrada
    cab = (f"📈 Simulação de patrimônio — {e['idade']} anos, perfil {e['perfil']}\n"
           f"Hoje: {_brl(e['patrimonio'])} · aporte {_brl(e['aporte_mensal'])}/mês"
           + (f" · meta {_brl(e['meta'])}" if e["meta"] else "") + (f" · renda desejada {_brl(e['renda_desejada'])}/mês" if e["renda_desejada"] else ""))
    fim = sim.anos[-1]
    proj = (f"\n\nProjeção aos {fim} anos (R$ de hoje): pessimista {_brl(sim.series['pessimista'][-1])} · base "
            f"{_brl(sim.series['base'][-1])} · otimista {_brl(sim.series['otimista'][-1])} · faixa provável (Monte Carlo 10–90%): "
            f"{_brl(sim.faixa['p10'][-1])} a {_brl(sim.faixa['p90'][-1])}")
    resp = "".join(f"\n\n❓ {r['pergunta']}\n{r['texto']}" for r in sim.respostas)
    prem = "\n\nPremissas: " + "; ".join(sim.premissas)
    return f"{cab}{proj}{resp}{prem}\n\n⚠️ {sim.aviso}"


def grafico_png(sim: Simulacao, caminho) -> None:
    """Linhas dos 3 cenários + faixa provável do Monte Carlo + meta (paleta validada do projeto)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=130)
    x = sim.anos
    ax.fill_between(x, np.array(sim.faixa["p10"]) / 1e6, np.array(sim.faixa["p90"]) / 1e6, color="#2a78d6", alpha=0.12,
                    label="faixa provável (10–90%)")
    for nome, cor, estilo in (("otimista", "#199e70", "--"), ("base", "#2a78d6", "-"), ("pessimista", "#d95926", "--")):
        ax.plot(x, np.array(sim.series[nome]) / 1e6, color=cor, linestyle=estilo, linewidth=2, label=nome)
        ax.annotate(_brl(sim.series[nome][-1]), (x[-1], sim.series[nome][-1] / 1e6), textcoords="offset points", xytext=(4, 0),
                    fontsize=8, color="#333333", va="center")
    meta = sim.entrada.get("meta")
    if meta:
        ax.axhline(meta / 1e6, color="#777777", linewidth=1, linestyle=":")
        ax.text(x[0], meta / 1e6, f" meta {_brl(meta)}", fontsize=8, color="#555555", va="bottom")
    ax.set_xlabel("idade")
    ax.set_ylabel("patrimônio (R$ milhões de hoje)")
    ax.set_title("Evolução do patrimônio por cenário", fontsize=11)
    ax.grid(alpha=0.25)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.text(0.01, 0.01, "Simulação, não promessa de rentabilidade. Quíron.", fontsize=7, color="#777777")
    fig.tight_layout()
    fig.savefig(caminho)
    plt.close(fig)


# ---------------------------------------------------------------- frase livre → entrada ("tenho 500 mil, invisto 5 mil…")
_NUM = r"(\d+(?:[.,]\d+)*)\s*(milh(?:ão|ao|ões|oes)|mil\b|mi\b|k\b)?"


def _valor(txt: str, mult: str | None) -> float:
    t = txt.replace(".", "").replace(",", ".") if re.search(r",\d{1,2}$", txt) or txt.count(".") > 1 or re.search(r"\.\d{3}$", txt) else txt.replace(",", ".")
    v = float(t)
    m = (mult or "").lower()
    return v * (1e6 if m.startswith("milh") or m == "mi" else 1e3 if m in {"mil", "k"} else 1)


def ler_frase(frase: str) -> dict[str, Any]:
    """Extrai os números de uma frase em português. Só regras (nada de modelo): o que não for dito fica de fora."""
    f = (frase or "").lower()
    d: dict[str, Any] = {}
    if m := re.search(r"(?:tenho|idade(?:\s+de)?|estou com)\s*(\d{2})\s*anos", f):
        d["idade"] = int(m.group(1))
    if m := re.search(r"(?:aos|até os|ate os|com)\s*(\d{2})\s*anos", f):
        if int(m.group(1)) != d.get("idade"):
            d["idade_meta"] = int(m.group(1))
    if m := re.search(r"(?:em|por)\s*(\d{1,2})\s*anos", f):
        d["_horizonte"] = int(m.group(1))
    if "idade" not in d:  # idade solta: "…, 50 anos, …" (não "em 10 anos", "aos 60 anos", "por 5 anos")
        for m in re.finditer(r"(\b\w+\s+)?(\d{2})\s*anos\b", f):
            anterior = (m.group(1) or "").strip()
            if anterior not in {"em", "por", "aos", "os", "com", "de", "daqui", "durante", "até", "ate"} and 14 <= int(m.group(2)) <= 100:
                d["idade"] = int(m.group(2))
                break
    f = re.sub(r"\d{1,3}\s*anos", " ", f)  # idades e prazos já lidos: não confundir com dinheiro
    regras = [
        ("aporte_mensal", rf"(?:invisto|aporto|aportando|aporte(?:\s+mensal)?(?:\s+de)?|guardo|guardando|poupo|investir|investindo)\s*(?:r\$\s*)?{_NUM}\s*(?:por mês|/m[eê]s|ao mês|mensais)?"),
        ("renda_desejada", rf"(?:renda(?:\s+de)?|viver com|receber)\s*(?:r\$\s*)?{_NUM}"),
        ("meta", rf"(?:meta(?:\s+de)?|chegar a|chegar aos|juntar|acumular|ter)\s*(?:r\$\s*)?{_NUM}"),
        ("patrimonio", rf"(?:tenho|patrim[oô]nio(?:\s+de)?|investido[s]?|aplicado[s]?|j[aá] tenho)\s*(?:r\$\s*)?{_NUM}"),
        ("imovel_valor", rf"(?:im[oó]vel(?:\s+de)?|apartamento(?:\s+de)?|casa(?:\s+de)?)\s*(?:r\$\s*)?{_NUM}"),
    ]
    usados: list[tuple[int, int]] = []
    for chave, rx in regras:
        if m := re.search(rx, f):
            d[chave] = _valor(m.group(1), m.group(2))
            usados.append(m.span())
    if "patrimonio" not in d and (m := re.search(rf"{_NUM}\s*(?:investidos?|aplicados?|guardados?|de patrim[oô]nio)\b", f)):
        d["patrimonio"] = _valor(m.group(1), m.group(2))  # "300 mil investidos"
    if "patrimonio" not in d:  # "/simular 500 mil, aporte 5 mil": valor sem rótulo LOGO NO INÍCIO é o patrimônio de hoje
        m = re.search(rf"(?:r\$\s*)?{_NUM}", f)
        if m and (m.group(2) or "r$" in m.group(0)) and not any(a <= m.start() < b for a, b in usados) \
                and not re.sub(r"[/\s,.;:\-]|simular|simula", "", f[:m.start()]) \
                and not re.match(r"\s*(?:por m[eê]s|/m[eê]s|ao m[eê]s|mensais|de renda)", f[m.end():]):
            d["patrimonio"] = _valor(m.group(1), m.group(2))
    if m := re.search(r"\b(conservador|moderado|arrojado)\b", f):
        d["perfil"] = m.group(1)
    horizonte = d.pop("_horizonte", None)
    if horizonte and "imovel_valor" in d:
        d["horizonte_imovel_anos"] = horizonte
    return d


def de_ficha(cliente: str, **ajustes: Any) -> Entrada:
    """Monta a simulação a partir da ficha de planejamento do cliente (CLI-XXX); `ajustes` sobrescrevem."""
    from quiron.servicos.planejamento import ficha as fichas

    f = fichas.carregar(cliente)
    investido = sum(b.valor for b in f.patrimonio if b.tipo in {"investimento", "previdencia_pgbl", "previdencia_vgbl"})
    base = {"patrimonio": investido, "aporte_mensal": f.aporte_mensal, "idade": f.idade or 40,
            "perfil": f.perfil if f.perfil in {"conservador", "moderado", "arrojado"} else "moderado",
            "renda_desejada": getattr(f, "renda_desejada_aposentadoria", 0.0) or f.despesas_mensais,
            "idade_meta": f.idade_aposentadoria if f.idade_aposentadoria and f.idade_aposentadoria > (f.idade or 0) else None}
    base.update({k: v for k, v in ajustes.items() if v not in (None, "", 0)})
    return Entrada.de_dict(base)
