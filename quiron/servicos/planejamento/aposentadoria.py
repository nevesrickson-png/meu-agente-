"""Aposentadoria (independência financeira): capital necessário, trajetória atual, aporte necessário, Monte Carlo.

Tudo em R$ de hoje (taxas REAIS). Acumulação até a idade de aposentadoria; usufruto até a idade do plano
(`expectativa_vida_plano`). O INSS reduz o que a carteira precisa pagar a partir da idade em que começa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from quiron.servicos.planejamento.diagnostico import pmt_para, premissas, retorno_real, taxa_mensal, vf, vp_renda
from quiron.servicos.planejamento.ficha import Ficha


@dataclass
class Aposentadoria:
    idade: int
    idade_aposentadoria: int
    idade_fim: int
    idade_inss: int
    renda_desejada: float
    inss: float
    capital_inicial: float  # patrimônio financeiro destinado à aposentadoria hoje
    aporte_atual: float
    retorno_acumulacao: float  # % a.a. real
    retorno_usufruto: float
    capital_necessario: float  # na data da aposentadoria
    capital_projetado: float  # com o aporte atual
    aporte_necessario: float  # mensal, para atingir o capital necessário
    renda_sustentavel: float  # renda mensal que o capital projetado paga até a idade do plano (com INSS)
    idade_esgota: float | None  # com a trajetória atual (None = dura até o fim do plano)
    prob_sucesso_atual: float
    prob_sucesso_necessario: float
    percentis_capital: dict[str, float]  # P10/P50/P90 do capital na aposentadoria (trajetória atual)
    sucesso_alvo: float = 0.85
    aporte_alvo: float | None = None  # aporte mensal para chegar à probabilidade-alvo (None: aposentado)
    renda_alvo: float = 0.0  # renda mensal sustentável com a probabilidade-alvo e o aporte atual
    aporte_viavel: float | None = None  # o que cabe no orçamento depois das prioridades (informado pelo plano)
    prob_viavel: float | None = None  # chance da renda desejada com o aporte viável
    renda_viavel: float | None = None  # renda sustentável (probabilidade-alvo) com o aporte viável
    sensibilidade: list[list] = field(default_factory=list)  # [cenário, aporte necessário]
    trajetoria: dict[str, list[float]] = field(default_factory=dict)  # por idade: atual, necessária, P10, P50, P90
    idades: list[int] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


def _capital_necessario(renda: float, inss: float, idade_ap: int, idade_inss: int, idade_fim: int, i_u: float) -> float:
    """VP (na aposentadoria) da renda que a carteira paga: cheia até o INSS começar, depois renda − INSS."""
    antes = max(0, idade_inss - idade_ap) * 12
    total = max(0, idade_fim - idade_ap) * 12
    depois = max(0, total - antes)
    pv_antes = vp_renda(renda, i_u, min(antes, total))
    pv_depois = vp_renda(max(0.0, renda - inss), i_u, depois) / (1 + i_u) ** min(antes, total)
    return pv_antes + pv_depois


def _saque(m: int, idade_ap: int, idade_inss: int, renda: float, inss: float) -> float:
    """Saque mensal da carteira no mês m depois da aposentadoria."""
    return renda - (inss if idade_ap + m / 12 >= idade_inss else 0.0)


def _simular(capital: float, aporte: float, n_acum: int, n_total: int, mu_a: float, sig_a: float, mu_u: float,
             sig_u: float, idade_ap: int, idade_inss: int, renda: float, inss: float, n_sim: int,
             semente: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Monte Carlo mensal (retornos reais lognormais). Devolve (riqueza por mês [sim, mês], sucesso [sim])."""
    g = np.random.default_rng(semente)
    meses = n_acum + n_total

    def params(mu: float, sig: float) -> tuple[float, float]:
        sm = sig / np.sqrt(12)
        return np.log(1 + mu) / 12 - sm ** 2 / 2, sm

    ma, sa = params(mu_a, sig_a)
    mu_, su = params(mu_u, sig_u)
    ret = np.empty((n_sim, meses))
    if n_acum:
        ret[:, :n_acum] = np.exp(g.normal(ma, sa, (n_sim, n_acum))) - 1
    ret[:, n_acum:] = np.exp(g.normal(mu_, su, (n_sim, n_total))) - 1
    riqueza = np.empty((n_sim, meses + 1))
    riqueza[:, 0] = capital
    w = np.full(n_sim, capital)
    for t in range(meses):
        if t < n_acum:
            w = w * (1 + ret[:, t]) + aporte
        else:
            w = (w - _saque(t - n_acum, idade_ap, idade_inss, renda, inss)) * (1 + ret[:, t])
        w = np.where(w > 0, w, -1.0)  # esgotou
        riqueza[:, t + 1] = w
    return riqueza, riqueza[:, -1] > 0


def planejar(f: Ficha, capital_inicial: float | None = None, p: dict | None = None,
             aporte_viavel: float | None = None) -> Aposentadoria:
    p = p or premissas()
    notas = []
    idade = int(f.idade)
    aposentado = f.ocupacao == "aposentado"
    idade_ap = idade if aposentado else int(f.idade_aposentadoria or max(idade + 1, 65))
    idade_ap = max(idade_ap, idade)
    idade_fim = max(int(p["expectativa_vida_plano"]), idade_ap + 5)
    idade_inss = int(f.idade_inss or idade_ap)
    if aposentado:
        idade_inss = min(idade_inss, idade)
    renda = f.renda_desejada_aposentadoria
    inss = f.inss_beneficio_mensal if (f.contribui_inss or aposentado) else 0.0
    if not inss and not aposentado:
        notas.append("Sem estimativa do INSS: a carteira paga a renda inteira (conservador). Peça o extrato no Meu INSS.")
    capital = f.investimentos if capital_inicial is None else capital_inicial
    aporte = 0.0 if aposentado else f.aporte_mensal
    r_a = retorno_real(f.perfil, None, p)
    r_u = float(p["retorno_real_usufruto"])
    i_a, i_u = taxa_mensal(r_a), taxa_mensal(r_u)
    n_acum = (idade_ap - idade) * 12
    n_total = (idade_fim - idade_ap) * 12

    necessario = _capital_necessario(renda, inss, idade_ap, idade_inss, idade_fim, i_u)
    projetado = vf(capital, aporte, i_a, n_acum)
    aporte_nec = pmt_para(necessario, capital, i_a, n_acum) if n_acum else 0.0
    unitario = _capital_necessario(1.0, 0.0, idade_ap, idade_inss, idade_fim, i_u)  # VP de R$ 1/mês
    pv_inss = _capital_necessario(0.0, -inss, idade_ap, idade_inss, idade_fim, i_u) if inss else 0.0
    renda_sust = (projetado + pv_inss) / unitario if unitario else 0.0

    # trajetória determinística: quando o dinheiro acaba?
    w, esgota = projetado, None
    for m in range(n_total):
        w = (w - _saque(m, idade_ap, idade_inss, renda, inss)) * (1 + i_u)
        if w < 0:
            esgota = idade_ap + (m + 1) / 12
            break

    vols = p["volatilidade_aa"]
    sig_a = vols.get(f.perfil, vols["moderado"]) / 100
    sig_u = min(sig_a, vols["moderado"] / 100) * 0.75  # carteira de usufruto mais conservadora
    n_sim = int(p.get("simulacoes_monte_carlo", 3000))
    riq_atual, ok_atual = _simular(capital, aporte, n_acum, n_total, r_a / 100, sig_a, r_u / 100, sig_u, idade_ap,
                                   idade_inss, renda, inss, n_sim)
    _, ok_nec = _simular(capital, max(aporte, aporte_nec), n_acum, n_total, r_a / 100, sig_a, r_u / 100, sig_u,
                         idade_ap, idade_inss, renda, inss, n_sim)
    def chance(aporte_m: float, renda_m: float) -> float:
        return float(_simular(capital, aporte_m, n_acum, n_total, r_a / 100, sig_a, r_u / 100, sig_u, idade_ap,
                              idade_inss, renda_m, inss, n_sim)[1].mean())

    alvo = float(p.get("sucesso_minimo", 0.85))
    aporte_alvo = None
    if n_acum:
        lo, hi = 0.0, max(1000.0, aporte_nec * 4)
        while chance(hi, renda) < alvo and hi < 1e7:
            hi *= 2
        for _ in range(18):  # bissecção (mesmos números aleatórios → função monótona)
            meio = (lo + hi) / 2
            lo, hi = (meio, hi) if chance(meio, renda) < alvo else (lo, meio)
        aporte_alvo = hi
    def renda_com(aporte_m: float) -> float:
        lo, hi = 0.0, max(renda, inss + 1) * 3
        for _ in range(18):
            meio = (lo + hi) / 2
            lo, hi = (meio, hi) if chance(aporte_m, meio) >= alvo else (lo, meio)
        return lo

    renda_alvo = renda_com(aporte)
    prob_viavel = renda_viavel = None
    if aporte_viavel is not None and n_acum:
        prob_viavel, renda_viavel = chance(aporte_viavel, renda), renda_com(aporte_viavel)

    cap_ap = riq_atual[:, n_acum]
    perc = {f"P{q}": float(np.percentile(np.where(cap_ap > 0, cap_ap, 0), q)) for q in (10, 50, 90)}

    # sensibilidade do aporte necessário
    sens = []
    for nome, d_ret, d_idade in (("Base", 0, 0), ("Retorno real −1 p.p.", -1, 0), ("Retorno real +1 p.p.", 1, 0),
                                 ("Aposentar 3 anos depois", 0, 3), ("Aposentar 3 anos antes", 0, -3)):
        ia = max(idade, idade_ap + d_idade)
        if aposentado and d_idade:
            continue
        ii = max(idade_inss, ia) if f.idade_inss is None else idade_inss
        nec = _capital_necessario(renda, inss, ia, ii, idade_fim, taxa_mensal(r_u + d_ret))
        sens.append([nome, round(pmt_para(nec, capital, taxa_mensal(r_a + d_ret), (ia - idade) * 12), 2), round(nec, 2)])

    # trajetórias anuais (para o gráfico)
    idades = list(range(idade, idade_fim + 1))
    atual, nec_traj = [], []
    wa, wn = capital, capital
    for k, ida in enumerate(idades):
        atual.append(max(0.0, wa))
        nec_traj.append(max(0.0, wn))
        for mm in range(12):
            m_abs = k * 12 + mm
            if m_abs < n_acum:
                wa = wa * (1 + i_a) + aporte
                wn = wn * (1 + i_a) + max(aporte, aporte_nec)
            else:
                s = _saque(m_abs - n_acum, idade_ap, idade_inss, renda, inss)
                wa, wn = (wa - s) * (1 + i_u), (wn - s) * (1 + i_u)
    anuais = riq_atual[:, ::12][:, :len(idades)]
    anuais = np.where(anuais > 0, anuais, 0)
    traj = {"Trajetória atual": atual, "Com o aporte necessário": nec_traj,
            "Monte Carlo P10 (atual)": [float(x) for x in np.percentile(anuais, 10, axis=0)],
            "Monte Carlo P50 (atual)": [float(x) for x in np.percentile(anuais, 50, axis=0)]}
    return Aposentadoria(idade, idade_ap, idade_fim, idade_inss, renda, inss, capital, aporte, r_a, r_u, necessario,
                         projetado, aporte_nec, renda_sust, esgota, float(ok_atual.mean()), float(ok_nec.mean()), perc,
                         alvo, aporte_alvo, renda_alvo, aporte_viavel if n_acum else None, prob_viavel, renda_viavel,
                         sens, traj, idades, notas)
