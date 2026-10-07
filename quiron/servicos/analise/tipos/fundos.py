"""Análises de fundos (Fase 10) com dados oficiais da CVM, no motor da Fase 7.

- fundo_analise: um fundo a fundo (rentabilidade por janela × CDI/benchmark, risco, pares, fluxo, taxas, liquidez);
- fundos_comparativo: 2 a 6 fundos lado a lado (com conferência das cotas na CVM);
- gestora: a casa — patrimônio, classes, fluxo e desempenho dos principais fundos contra os pares;
- previdencia_portabilidade: fundo atual × destino, projeção, custos e regimes de tributação;
- fii_comparativo: fundos imobiliários (VP da cota, P/VP, dividend yield, rentabilidade, segmento, liquidez).
Rentabilidade = razão de cotas da CVM (líquida de taxas, antes do IR). Uso interno — não é recomendação.
"""

from __future__ import annotations

import logging
import re

from typing import Any

import pandas as pd

from quiron.servicos.analise import redacao
from quiron.servicos.analise.fila import tipo
from quiron.servicos.analise.relatorio import Grafico, Relatorio, Secao, Tabela, brl, pct
from quiron.servicos.fundos import cvm, metricas
from quiron.servicos.fundos.metricas import AnaliseFundo

RODAPE = ("Uso interno e de estudo — dados da CVM; rentabilidade passada não garante resultado futuro; não constitui "
          "recomendação nem relatório de análise.")


def _p(v: float | None, casas: int = 2) -> float | None:
    return None if v is None else round(float(v) * 100, casas)


def _r(v: float | None, casas: int = 2) -> float | None:
    return None if v is None else round(float(v), casas)


def benchmarks(dados: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    """CDI, Ibovespa, IPCA e dólar mensais (as mesmas séries da Fase 8)."""
    if dados is not None:
        return dados, ["📊 benchmarks fornecidos"]
    from quiron.servicos.carteira import series

    s = series.carregar([])
    return s.retornos, [f for f in s.fontes if "CDI" in f or "IPCA" in f or "Yahoo" in f]


def preparar(anos: float, aviso=None) -> list[str]:
    """Garante cadastro, extrato e o índice mensal dos últimos `anos` anos. Devolve avisos."""
    cvm.atualizar_cadastro()
    cvm.atualizar_extrato()
    baixados = cvm.garantir_meses(int(round(anos * 12)) + 1, aviso=aviso)
    return [f"Informe diário da CVM baixado agora: {len(baixados)} mês(es)."] if len(baixados) > 3 else []


RE_FII = re.compile(r"^[A-Z]{4}1[1-3]$")


_OPCOES = {"anos", "modo", "saldo", "aporte", "aporte_mensal", "renda_mensal_aposentadoria", "horizonte", "perfil",
           "aprofundado", "detalhado", "periodo", "meses", "valor"}


def _separar(v: Any) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[,;]|\s+e\s+|\s*\+\s*", v) if x.strip()]
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _itens(params: dict[str, Any], *chaves: str) -> list[str]:
    """Fundos pedidos. O agente nem sempre usa o nome de campo esperado ({"fundo": …}, {"ativos": […]}): se as chaves
    conhecidas vierem vazias, junta o texto de qualquer outro campo que não seja opção (anos, saldo…)."""
    for k in chaves:
        if itens := _separar(params.get(k)):
            return itens
    saida: list[str] = []
    for k, v in params.items():
        if k.lower() not in _OPCOES:
            saida += _separar(v)
    return saida


def _so_fiis(params: dict[str, Any]) -> list[str]:
    """Todos os itens pedidos têm cara de ticker de FII (XXXX11)? Então a análise certa é a de FIIs."""
    itens = [i.upper() for i in _itens(params, "cnpjs", "fundos", "cnpj", "fiis", "tickers", "fundo", "ticker")]
    return itens if itens and all(RE_FII.match(i) for i in itens) else []


def _cnpjs(params: dict[str, Any], minimo: int = 1, maximo: int = 6) -> list[str]:
    bruto = _itens(params, "cnpjs", "fundos", "cnpj", "fundo", "nomes", "nome")
    saida = []
    for item in bruto:
        d = cvm.digitos(str(item))
        if len(d) < 11:  # veio nome: pega o maior da busca
            achados = cvm.buscar(str(item), 1)
            if not achados:
                raise cvm.FundoNaoEncontrado(f"não achei o fundo “{item}” no cadastro da CVM")
            d = achados[0].cnpj
        saida.append(d.zfill(14))
    if not minimo <= len(saida) <= maximo:
        raise ValueError(f"informe de {minimo} a {maximo} fundos (CNPJ ou nome)")
    return saida


def _rotulos(analises: list[AnaliseFundo]) -> dict[str, str]:
    """Nome curto de cada fundo; nomes repetidos ganham o final do CNPJ."""
    curtos = [_nome_curto(a.nome) for a in analises]
    return {a.classe.cnpj: (c if curtos.count(c) == 1 else f"{c} (…{a.classe.cnpj_formatado[-7:]})")
            for a, c in zip(analises, curtos)}


def _nome_curto(nome: str, n: int = 38) -> str:
    for corte in (" FUNDO DE INVESTIMENTO", " FIF", " FIC", " CLASSE", " - RESP", " RESP"):
        i = nome.upper().find(corte)
        if i > 8:
            nome = nome[:i]
            break
    return nome[:n].strip()


# ---------------------------------------------------------------- tabelas comuns
def tabela_rentabilidade(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    nomes = [j.nome for j in analises[0].janelas]
    linhas = []
    for a in analises:
        por = {j.nome: j for j in a.janelas}
        linhas.append([rot[a.classe.cnpj]] + [_p(por[n].retorno) if n in por else None for n in nomes])
    ref = analises[0]
    linhas.append(["CDI"] + [_p(j.cdi) for j in ref.janelas])
    if any(a.nome_benchmark == "IBOV" for a in analises):
        linhas.append(["Ibovespa"] + [_p(j.benchmark) if ref.nome_benchmark == "IBOV" else None for j in ref.janelas])
    return Tabela(f"Rentabilidade (%) — até {ref.data_final[8:10]}/{ref.data_final[5:7]}/{ref.data_final[:4]}",
                  ["Fundo", *nomes], linhas, ["texto"] + ["pct"] * len(nomes),
                  "Razão de cotas da CVM: líquida de taxas de administração/performance, antes do IR. Janelas até o último mês fechado.")


def tabela_pct_cdi(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    nomes = [j.nome for j in analises[0].janelas if j.cdi]
    return Tabela("Rentabilidade em % do CDI", ["Fundo", *nomes],
                  [[rot[a.classe.cnpj]] + [f"{j.pct_cdi * 100:.0f}%" if j.pct_cdi is not None else None
                                            for j in a.janelas if j.nome in nomes] for a in analises],
                  ["texto"] * (len(nomes) + 1))


def tabela_risco(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    linhas = []
    for a in analises:
        r = a.risco
        if not r:
            linhas.append([rot[a.classe.cnpj]] + [None] * 8)
            continue
        linhas.append([rot[a.classe.cnpj], r.meses, _p(r.vol_aa), _r(r.sharpe), _r(r.sortino), _p(r.max_drawdown),
                       f"{pct(r.pior_mes * 100)} ({r.pior_mes_quando})", _p(r.acima_cdi, 0), _r(r.beta_ibov)])
    return Tabela("Risco (retornos mensais, até 36 meses)", ["Fundo", "Meses", "Volatilidade a.a.", "Sharpe", "Sortino",
                                                            "Pior queda", "Pior mês", "Meses acima do CDI", "Beta Ibov"],
                  linhas, ["texto", "int", "pct", "num", "num", "pct", "texto", "pct", "num"],
                  "Sharpe e Sortino sobre o CDI. Pior queda = maior perda acumulada de um pico ao fundo (mensal).")


def tabela_cadastro(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    linhas = []
    for a in analises:
        e = a.extrato or {}
        perf = f"{pct(e['taxa_perf'], 0)} sobre {e.get('indice_perf') or '?'}" if e.get("taxa_perf") else "—"
        liq = (f"D+{e['dias_conversao']} cotização, +{e['dias_pagamento']} pagamento"
               if e.get("dias_conversao") is not None else "—")
        linhas.append([rot[a.classe.cnpj], a.classe.cnpj_formatado, a.classe.anbima or a.classe.classificacao,
                       _nome_curto(a.classe.gestor, 30), pct(e["taxa_adm"]) if e.get("taxa_adm") is not None else "—", perf,
                       brl(e["aplic_min"]) if e.get("aplic_min") is not None else "—", liq,
                       {"S": "sim", "N": "não"}.get(a.classe.tributacao_lp, "—"), a.classe.publico or e.get("publico") or "—"])
    return Tabela("Cadastro, taxas e liquidez (CVM)", ["Fundo", "CNPJ", "Classificação ANBIMA", "Gestora", "Taxa adm.",
                                                      "Performance", "Aplicação mínima", "Resgate", "Tributação LP", "Público"],
                  linhas, ["texto"] * 10, "Taxas e prazos do extrato anual entregue à CVM (pode estar desatualizado); “—” = sem extrato no ano.")


def tabela_fluxo(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    linhas = []
    for a in analises:
        var_pl = (a.pl / a.pl_12m - 1) if a.pl and a.pl_12m else None
        linhas.append([rot[a.classe.cnpj], _r(a.pl), _p(var_pl, 1), _r(a.captacao_liquida_12m), a.cotistas,
                       (a.cotistas - a.cotistas_12m) if a.cotistas is not None and a.cotistas_12m is not None else None])
    return Tabela("Patrimônio e fluxo", ["Fundo", "PL (R$)", "Variação do PL 12m", "Captação líquida 12m (R$)", "Cotistas",
                                         "Cotistas 12m (±)"], linhas, ["texto", "reais", "pct", "reais", "int", "int"])


def tabela_pares(analises: list[AnaliseFundo]) -> Tabela | None:
    rot = _rotulos(analises)
    linhas = [[rot[a.classe.cnpj], a.classe.anbima, *[f"{a.percentis[n][0]:.0f}º ({a.percentis[n][1]} pares)"
                                                        if n in a.percentis else "—" for n in ("12 meses", "36 meses")]]
              for a in analises]
    if all(l[2] == "—" and l[3] == "—" for l in linhas):
        return None
    return Tabela("Posição entre os pares (percentil: 100 = melhor)", ["Fundo", "Pares (ANBIMA)", "12 meses", "36 meses"],
                  linhas, ["texto"] * 4, f"Pares: mesma classificação ANBIMA, abertos, não exclusivos e com PL ≥ "
                                         f"{brl(metricas.PL_MINIMO_PARES)}.")


def tabela_conferencia(analises: list[AnaliseFundo]) -> Tabela:
    rot = _rotulos(analises)
    linhas = []
    for a in analises:
        for j in a.janelas:
            if j.nome in ("12 meses", "36 meses") and j.cota_inicial:
                linhas.append([rot[a.classe.cnpj], j.nome, f"{j.inicio[8:10]}/{j.inicio[5:7]}/{j.inicio[:4]}",
                               round(j.cota_inicial, 8), f"{j.fim[8:10]}/{j.fim[5:7]}/{j.fim[:4]}", round(j.cota_final, 8),
                               _p(j.retorno, 4)])
    return Tabela("Conferência com a CVM (informe diário)", ["Fundo", "Janela", "Data inicial", "Cota inicial", "Data final",
                                                             "Cota final", "Rentabilidade"],
                  linhas, ["texto", "texto", "texto", "texto", "texto", "texto", "pct"],
                  "Cotas exatamente como publicadas no informe diário da CVM; rentabilidade = cota final ÷ cota inicial − 1.")


def grafico_acumulado(analises: list[AnaliseFundo], bench: pd.DataFrame) -> Grafico:
    rot, series = metricas.acumulado_comum(analises)
    idx = pd.PeriodIndex(rot[1:], freq="M")
    series = {_nome_curto(k, 30): v for k, v in series.items()}
    if "CDI" in bench:
        series["CDI"] = [100.0] + list(100 * (1 + bench["CDI"].reindex(idx).fillna(0.0)).cumprod())
    passo = max(1, len(rot) // 40)
    return Grafico("R$ 100 aplicados no início do período comum", "linhas", rot[::passo],
                   {k: [round(x, 2) for x in v[::passo]] for k, v in series.items()}, "num", "mês")


def _fatos_fundo(a: AnaliseFundo) -> dict[str, Any]:
    e = a.extrato or {}
    return {"nome": _nome_curto(a.nome, 60), "cnpj": a.classe.cnpj_formatado, "anbima": a.classe.anbima,
            "gestora": a.classe.gestor, "benchmark": a.nome_benchmark, "data_final": a.data_final,
            "rentabilidade_pct": {j.nome: _p(j.retorno) for j in a.janelas if j.retorno is not None},
            "pct_cdi": {j.nome: _p(j.pct_cdi, 0) for j in a.janelas if j.pct_cdi is not None},
            "cdi_pct": {j.nome: _p(j.cdi) for j in a.janelas if j.cdi is not None},
            "volatilidade_pct": _p(a.risco.vol_aa) if a.risco else None, "sharpe": _r(a.risco.sharpe) if a.risco else None,
            "pior_queda_pct": _p(a.risco.max_drawdown) if a.risco else None,
            "meses_acima_cdi_pct": _p(a.risco.acima_cdi, 0) if a.risco else None,
            "percentil": {k: round(v[0]) for k, v in a.percentis.items()}, "pl": _r(a.pl),
            "captacao_liquida_12m": _r(a.captacao_liquida_12m), "cotistas": a.cotistas,
            "taxa_adm_pct": e.get("taxa_adm"), "taxa_perf_pct": e.get("taxa_perf"),
            "resgate": f"D+{e['dias_conversao']}+{e['dias_pagamento']}" if e.get("dias_conversao") is not None else None}


def _base(titulo: str, tipo_nome: str, subtitulo: str, avisos: list[str], fontes: list[str]) -> Relatorio:
    rel = Relatorio(titulo, tipo_nome, subtitulo=subtitulo, rodape=RODAPE, avisos=avisos)
    rel.fontes = [cvm.fonte(), "📊 CVM — cadastro de fundos (Resolução CVM 175), informe diário e extrato anual", *fontes]
    rel.premissas = ["Rentabilidade pela razão de cotas do informe diário da CVM (líquida de taxas, bruta de IR e "
                     "come-cotas); janelas encerradas no último mês fechado.",
                     "CDI: SGS 4391 (Banco Central); Ibovespa: Yahoo Finance; risco com retornos mensais (até 36 meses).",
                     f"Pares: mesma classificação ANBIMA, abertos, não exclusivos, PL ≥ {brl(metricas.PL_MINIMO_PARES)}."]
    rel.limitacoes = ["Rentabilidade passada não garante resultado futuro.",
                      "Fundos com subclasses podem ter taxas e cotas diferentes por subclasse (distribuidor).",
                      "Fundos espelho/feeder repetem o master com outra taxa; compare a estrutura que o cliente acessa.",
                      "Taxas e prazos vêm do extrato anual na CVM: confira a lâmina/regulamento vigente antes de recomendar.",
                      "Risco mensal subestima oscilações dentro do mês; sem dados de carteira (CDA) nesta análise."]
    return rel


# ---------------------------------------------------------------- tipos
@tipo("fundos_comparativo", descricao="Compara 2 a 6 fundos com dados oficiais da CVM: rentabilidade por janela × CDI, "
      "% do CDI, risco (vol, Sharpe, pior queda), posição entre os pares, fluxo, taxas, liquidez e conferência das cotas.",
      parametros={"cnpjs": "lista de CNPJs (ou nomes) dos fundos, de 2 a 6", "anos": "histórico em anos (padrão 3, máx. 5)"})
def comparativo(params: dict[str, Any], modo: str = "entregar", dados_bench: pd.DataFrame | None = None,
                redigir: bool = True, minimo: int = 2) -> Relatorio:
    if fiis := _so_fiis(params):  # "RBRR11 e MCCI11" são FIIs: o comparativo certo é o de fundos imobiliários
        return fii_comparativo({"fiis": fiis}, modo, redigir=redigir)
    anos = min(5.0, max(1.0, float(params.get("anos") or 3)))
    avisos = preparar(anos)
    cnpjs = _cnpjs(params, minimo, 6)
    bench, fontes_b = benchmarks(dados_bench)
    analises = [metricas.analisar(c, bench) for c in cnpjs]
    for a in analises:
        avisos += [f"{_nome_curto(a.nome)}: {x}" for x in a.avisos]
        if a.cotistas is not None and a.cotistas <= 5:
            avisos.append(f"{_nome_curto(a.nome)}: só {a.cotistas} cotista(s) — costuma ser veículo de distribuidor/master; "
                          "o cliente acessa por um fundo de cotas com outra taxa.")
    unico = len(analises) == 1
    titulo = (f"Análise de fundo — {_nome_curto(analises[0].nome, 60)}" if unico
              else "Comparativo de fundos — " + " × ".join(_nome_curto(a.nome, 22) for a in analises))
    rel = _base(titulo, "fundo_analise" if unico else "fundos_comparativo",
                "; ".join(f"{a.classe.cnpj_formatado}" for a in analises), avisos, fontes_b)
    j12 = {a.nome: next((j for j in a.janelas if j.nome == "12 meses"), None) for a in analises}
    validos = [a for a in analises if j12[a.nome] and j12[a.nome].retorno is not None]
    resumo = []
    if validos:
        melhor = max(validos, key=lambda a: j12[a.nome].retorno)
        resumo.append(f"Em 12 meses, {_nome_curto(melhor.nome)} rendeu {pct(j12[melhor.nome].retorno * 100)}"
                      + (f" ({pct(j12[melhor.nome].pct_cdi * 100, 0)} do CDI)" if j12[melhor.nome].pct_cdi else "") + ".")
    for a in analises:
        partes = []
        if a.risco:
            partes.append(f"volatilidade {pct(a.risco.vol_aa * 100)} a.a., pior queda {pct(a.risco.max_drawdown * 100)}")
        if "12 meses" in a.percentis:
            partes.append(f"percentil {a.percentis['12 meses'][0]:.0f} entre {a.percentis['12 meses'][1]} pares em 12 meses")
        if partes:
            resumo.append(f"{_nome_curto(a.nome)}: " + "; ".join(partes) + ".")
    rel.resumo = resumo
    rel.fatos = {"fundos": [_fatos_fundo(a) for a in analises]}
    secoes = [Secao("Rentabilidade", "", [tabela_rentabilidade(analises), tabela_pct_cdi(analises)],
                    [grafico_acumulado(analises, bench)]),
              Secao("Risco", "", [tabela_risco(analises)])]
    if not unico and all(a.risco for a in analises):
        secoes[1].graficos.append(Grafico(
            "Risco × retorno (até 36 meses)", "dispersao", [],
            {_nome_curto(a.nome, 28): [_p((1 + a.retornos.tail(36)).prod() ** (12 / min(36, len(a.retornos))) - 1)]
             for a in analises}, "pct", "volatilidade a.a.",
            x={_nome_curto(a.nome, 28): [_p(a.risco.vol_aa)] for a in analises}, formato_x="pct"))
    pares = tabela_pares(analises)
    secoes.append(Secao("Pares, patrimônio e fluxo", "", [t for t in (pares, tabela_fluxo(analises)) if t]))
    secoes.append(Secao("Cadastro, taxas e liquidez", "", [tabela_cadastro(analises)]))
    secoes.append(Secao("Conferência com a CVM", "", [tabela_conferencia(analises)]))
    rel.secoes = secoes
    rel.parametros = {"cnpjs": [cvm.formatar_cnpj(c) for c in cnpjs], "anos": anos}
    return redacao.redigir(rel, modo) if redigir else rel


@tipo("fundo_analise", descricao="Análise de UM fundo com dados da CVM: rentabilidade por janela × CDI/benchmark, risco, "
      "posição entre os pares, fluxo de captação, cotistas, taxas e liquidez.",
      parametros={"cnpj": "CNPJ (ou nome) do fundo", "anos": "histórico em anos (padrão 3, máx. 5)"})
def fundo(params: dict[str, Any], modo: str = "entregar", dados_bench: pd.DataFrame | None = None,
          redigir: bool = True) -> Relatorio:
    itens = _itens(params, "cnpj", "cnpjs", "fundo", "fundos", "nome", "ticker", "fii")
    return comparativo({**params, "cnpjs": itens[:1]}, modo, dados_bench, redigir, minimo=1)


@tipo("gestora", descricao="Raio-X de uma gestora com dados da CVM: patrimônio por classificação, nº de classes, captação "
      "líquida e desempenho dos maiores fundos contra os pares.",
      parametros={"gestora": "nome (ou CNPJ) da gestora", "anos": "histórico em anos (padrão 3)"})
def gestora(params: dict[str, Any], modo: str = "entregar", dados_bench: pd.DataFrame | None = None,
            redigir: bool = True) -> Relatorio:
    termo = str(params.get("gestora") or "").strip()
    if not termo:
        raise ValueError("informe o nome ou CNPJ da gestora")
    anos = min(5.0, max(1.0, float(params.get("anos") or 3)))
    avisos = preparar(anos)
    classes, nomes = cvm.fundos_da_gestora(termo)
    if not classes:
        raise cvm.FundoNaoEncontrado(f"nenhuma classe em funcionamento para a gestora “{termo}”")
    if len(nomes) > 1:
        avisos.append("O termo achou mais de uma gestora: " + "; ".join(nomes[:6]) + ". Use o CNPJ para filtrar.")
    bench, fontes_b = benchmarks(dados_bench)
    # patrimônio sem dupla contagem: fundos de cotas (FIC/CIC) investem em outros fundos da casa
    proprios = [c for c in classes if c.classe_cotas != "S" and "COTAS" not in c.nome.upper()]
    pl_total = sum(c.pl or 0 for c in proprios)
    por_class: dict[str, list[float]] = {}
    for c in proprios:
        k = c.anbima or c.classificacao or c.tipo.replace("Classes de Cotas de Fundos ", "")
        por_class.setdefault(k, []).append(c.pl or 0)
    distrib = sorted(((k, sum(v), len(v)) for k, v in por_class.items()), key=lambda x: -x[1])
    # maiores fundos acessíveis (inclui FIC, que é o que o cliente compra) com histórico
    candidatos = [c for c in classes if (c.exclusivo or "N") != "S" and "MASTER" not in c.nome.upper()][:40]
    analises = []
    for c in candidatos:
        try:
            a = metricas.analisar(c.cnpj, bench)
        except cvm.FundoNaoEncontrado:
            continue
        if len(a.retornos) >= 12:
            analises.append(a)
        if len(analises) >= 12:
            break
    fluxo = sum(a.captacao_liquida_12m for a in analises)
    perc12 = [a.percentis["12 meses"][0] for a in analises if "12 meses" in a.percentis]
    perc36 = [a.percentis["36 meses"][0] for a in analises if "36 meses" in a.percentis]
    nome_g = nomes[0] if nomes else termo
    rel = _base(f"Gestora — {nome_g}", "gestora", f"{len(classes)} classes em funcionamento", avisos, fontes_b)
    mediana = lambda v: float(pd.Series(v).median()) if v else None  # noqa: E731
    rel.fatos = {"gestora": nome_g, "classes": len(classes), "pl_sem_fic": round(pl_total, 2),
                 "maiores_classificacoes": [{"classificacao": k, "pl": round(v, 2), "classes": n} for k, v, n in distrib[:8]],
                 "fundos_analisados": len(analises), "captacao_liquida_12m_analisados": round(fluxo, 2),
                 "percentil_mediano_12m": _r(mediana(perc12), 0), "percentil_mediano_36m": _r(mediana(perc36), 0),
                 "fundos": [_fatos_fundo(a) for a in analises]}
    rel.resumo = [f"{nome_g}: {len(classes)} classes em funcionamento e {brl(pl_total)} de patrimônio (sem contar fundos de cotas).",
                  f"Maior concentração: {distrib[0][0]} ({brl(distrib[0][1])})." if distrib else "",
                  (f"Nos {len(analises)} maiores fundos abertos, o percentil mediano entre os pares é "
                   f"{mediana(perc12):.0f} em 12 meses" + (f" e {mediana(perc36):.0f} em 36 meses." if perc36 else "."))
                  if perc12 else "Sem pares suficientes para comparar.",
                  f"Captação líquida em 12 meses desses fundos: {brl(fluxo)}."]
    rel.resumo = [r for r in rel.resumo if r]
    t_dist = Tabela("Patrimônio por classificação (sem fundos de cotas)", ["Classificação", "PL (R$)", "Classes", "Participação"],
                    [[k, round(v, 2), n, _p(v / pl_total) if pl_total else None] for k, v, n in distrib[:15]],
                    ["texto", "reais", "int", "pct"])
    g = Grafico("Patrimônio por classificação", "barras_h", [k[:40] for k, _, _ in distrib[:8]],
                {"PL": [round(v, 0) for _, v, _ in distrib[:8]]}, "brl")
    secoes = [Secao("A gestora", "", [t_dist], [g])]
    if analises:
        secoes.append(Secao("Maiores fundos abertos", "", [tabela_rentabilidade(analises[:8]), tabela_risco(analises[:8])]))
        pares = tabela_pares(analises)
        secoes.append(Secao("Consistência contra os pares", "", [t for t in (pares, tabela_fluxo(analises)) if t]))
    rel.secoes = secoes
    rel.parametros = {"gestora": termo, "anos": anos}
    rel.limitacoes.append("Patrimônio sem fundos de cotas é aproximado (masters de terceiros e carteiras administradas ficam fora).")
    return redacao.redigir(rel, modo) if redigir else rel


@tipo("previdencia_portabilidade", descricao="Previdência: compara o fundo atual com o de destino (rentabilidade, taxas, "
      "risco), projeta o saldo nos dois e mostra a tabela regressiva × progressiva para decidir a portabilidade.",
      parametros={"cnpj_atual": "CNPJ (ou nome) do fundo de previdência atual", "cnpj_destino": "CNPJ (ou nome) do destino",
                  "saldo": "saldo atual em R$ (padrão 100000)", "aporte_mensal": "aporte mensal em R$ (padrão 0)",
                  "anos": "horizonte da projeção em anos (padrão 10)",
                  "renda_mensal_aposentadoria": "renda mensal esperada no resgate (para comparar com a tabela progressiva)"})
def previdencia(params: dict[str, Any], modo: str = "entregar", dados_bench: pd.DataFrame | None = None,
                redigir: bool = True) -> Relatorio:
    from quiron.nucleo import regras
    from quiron.servicos.planejamento import impostos

    cnpjs = _cnpjs({"cnpjs": [params.get("cnpj_atual"), params.get("cnpj_destino")]}, 2, 2)
    saldo = float(params.get("saldo") or 100_000)
    aporte = float(params.get("aporte_mensal") or 0)
    horizonte = int(params.get("anos") or 10)
    avisos = preparar(3)
    bench, fontes_b = benchmarks(dados_bench)
    atual, destino = (metricas.analisar(c, bench) for c in cnpjs)
    for a in (atual, destino):
        if "PREVID" not in f"{a.classe.anbima} {a.nome}".upper():
            avisos.append(f"{_nome_curto(a.nome)} não parece ser um fundo de previdência (confira o CNPJ).")
    rel = _base(f"Previdência: {_nome_curto(atual.nome, 28)} × {_nome_curto(destino.nome, 28)}", "previdencia_portabilidade",
                "Portabilidade entre fundos de previdência", avisos, fontes_b)

    def anual(a: AnaliseFundo) -> tuple[float | None, int]:
        r = a.retornos.tail(36)
        return (float((1 + r).prod() ** (12 / len(r)) - 1) if len(r) >= 12 else None), len(r)

    ra, na = anual(atual)
    rd, nd = anual(destino)
    proj = []
    if ra is not None and rd is not None:
        for nome, taxa in (("Atual", ra), ("Destino", rd)):
            i = (1 + taxa) ** (1 / 12) - 1
            n = horizonte * 12
            proj.append([nome, round(taxa * 100, 2), round(saldo * (1 + i) ** n + aporte * ((1 + i) ** n - 1) / i if i else saldo + aporte * n, 2)])
        dif = proj[1][2] - proj[0][2]
    else:
        dif = None
        avisos.append("Histórico curto (< 12 meses) em um dos fundos: sem projeção.")
    reg = regras.carregar_regras()["previdencia"]["tabela_regressiva"]
    t_reg = Tabela("Tabela regressiva (prazo de cada aporte)", ["Prazo", "Alíquota"],
                   [[(f"até {f['ate_anos']} anos" if "ate_anos" in f else f"acima de {f['acima_de_anos']} anos"),
                     round(f["aliquota"] * 100, 1)] for f in reg], ["texto", "pct"],
                   "Na portabilidade o regime e a data de cada aporte são mantidos (não zera o prazo).")
    tabelas_trib = [t_reg]
    renda = float(params.get("renda_mensal_aposentadoria") or 0)
    if renda:
        ir_prog = impostos.ir_na_fonte(renda)
        tabelas_trib.append(Tabela("Progressiva no resgate (renda informada)", ["Renda mensal (R$)", "IR mensal (R$)",
                                                                                 "Alíquota efetiva"],
                                   [[round(renda, 2), round(ir_prog, 2), round(ir_prog / renda * 100, 2)]],
                                   ["reais", "reais", "pct"], "Na progressiva o IR é retido em 15% e ajustado na declaração."))
    rel.fatos = {"atual": _fatos_fundo(atual), "destino": _fatos_fundo(destino), "saldo": saldo, "aporte_mensal": aporte,
                 "horizonte_anos": horizonte, "retorno_anual_atual_pct": _p(ra), "retorno_anual_destino_pct": _p(rd),
                 "meses_usados": [na, nd], "diferenca_projetada": _r(dif),
                 "projecao": [{"fundo": p[0], "retorno_aa_pct": p[1], "saldo_final": p[2]} for p in proj]}
    rel.resumo = [f"Em 36 meses (ou o disponível), o atual rendeu {pct(ra * 100)} a.a. e o destino {pct(rd * 100)} a.a."
                  if ra is not None and rd is not None else "Histórico insuficiente para comparar.",
                  (f"Mantida essa diferença por {horizonte} anos, o destino terminaria com {brl(abs(dif))} "
                   + ("a mais." if dif > 0 else "a menos.")) if dif is not None else "",
                  "Portabilidade não tem IR nem custo e mantém o regime e as datas dos aportes; só entre planos do mesmo "
                  "tipo (PGBL → PGBL, VGBL → VGBL)."]
    rel.resumo = [r for r in rel.resumo if r]
    t_proj = Tabela(f"Projeção do saldo em {horizonte} anos (retorno anual histórico mantido)",
                    ["Fundo", "Retorno a.a. usado", "Saldo projetado (R$)"], proj, ["texto", "pct", "reais"],
                    "Ilustrativo: repete o passado; serve para dimensionar o efeito de taxa e gestão, não para prometer.")
    rel.secoes = [Secao("Rentabilidade", "", [tabela_rentabilidade([atual, destino]), tabela_pct_cdi([atual, destino])],
                        [grafico_acumulado([atual, destino], bench)]),
                  Secao("Risco, taxas e liquidez", "", [tabela_risco([atual, destino]), tabela_cadastro([atual, destino])]),
                  Secao("Projeção", "", [t_proj] if proj else []),
                  Secao("Tributação", "", tabelas_trib),
                  Secao("Conferência com a CVM", "", [tabela_conferencia([atual, destino])])]
    rel.parametros = {k: v for k, v in params.items()}
    rel.limitacoes.append("Plano de previdência tem taxa de carregamento e regras da seguradora fora dos dados da CVM.")
    return redacao.redigir(rel, modo) if redigir else rel


# ---------------------------------------------------------------- FII
def _proventos_12m(ticker: str) -> float | None:
    """Rendimentos pagos por cota nos últimos 12 meses (B3, via Yahoo Finance)."""
    try:
        import yfinance as yf

        d = yf.Ticker(f"{ticker}.SA").dividends
        if d.empty:
            return None
        return float(d[d.index > d.index.max() - pd.Timedelta(days=365)].sum())
    except Exception:  # noqa: BLE001
        return None


def _cotacao(ticker: str) -> float | None:
    try:
        from quiron.servicos.mercado import cotacoes

        return float(cotacoes.cotacao(ticker).preco)
    except Exception:  # noqa: BLE001
        return None


@tipo("fii_comparativo", descricao="Compara fundos imobiliários com o informe mensal da CVM: valor patrimonial da cota, "
      "P/VP, dividend yield (sobre VP e sobre o preço), rentabilidade, segmento, PL e cotistas.",
      parametros={"fiis": "lista de tickers (HGLG11, KNRI11…) de 1 a 8"})
def fii_comparativo(params: dict[str, Any], modo: str = "entregar", precos: dict[str, float] | None = None,
                    proventos: dict[str, float] | None = None, redigir: bool = True) -> Relatorio:
    tickers = _itens(params, "fiis", "tickers", "fundos", "ativos", "codigos", "cnpjs", "fii", "ticker", "fundo")
    # "RBRR11 e MCCI11", "MCCI11 (Mauá)", "MCCI" (sem o 11): fica só o que tem cara de código de FII
    texto = " ".join(tickers)
    codigos = [c.upper() for c in re.findall(r"\b[A-Za-z]{4}1[1-3]\b", texto)]
    codigos += [c + "11" for c in re.findall(r"\b[A-Z]{4}\b", texto) if c + "11" not in codigos]  # "MCCI" em maiúsculas
    tickers = list(dict.fromkeys(codigos if codigos else [t.upper().strip() for t in tickers]))[:8]
    if not tickers:
        raise ValueError("informe os tickers dos FIIs (ex.: HGLG11, KNRI11)")
    linhas, fatos, avisos = [], [], []
    try:
        cvm.atualizar_fii()
    except Exception as e:  # noqa: BLE001 — CVM lenta/fora: segue com o informe já guardado (se houver)
        logging.warning("informe mensal de FII não atualizado (%s: %s)", type(e).__name__, e)
        avisos.append(f"Não consegui atualizar o informe mensal da CVM agora ({type(e).__name__}); usei o último guardado.")
    secoes_imoveis, imoveis_fatos = [], {}
    for t in tickers:
        try:
            hist = cvm.fii(t)
        except cvm.FundoNaoEncontrado as e:
            avisos.append(str(e))
            continue
        ult = hist[-1]
        ultimos = hist[-12:]
        dy_vp_12 = sum(h["dy_mes"] or 0 for h in ultimos)
        rendimentos = sum((h["dy_mes"] or 0) / 100 * (h["vp_cota"] or 0) for h in ultimos)
        rent_12 = 1.0
        for h in ultimos:
            rent_12 *= 1 + (h["rent_efetiva"] or 0) / 100
        preco = (precos or {}).get(t) if precos is not None else _cotacao(t)
        p_vp = preco / ult["vp_cota"] if preco and ult["vp_cota"] else None
        pagos = (proventos or {}).get(t) if proventos is not None else _proventos_12m(t)
        base = pagos if pagos else rendimentos  # proventos pagos (B3) são mais confiáveis que o % mensal declarado
        dy_preco = base / preco if preco and base else None
        if pagos and rendimentos and abs(rendimentos / pagos - 1) > 0.3:
            avisos.append(f"{t}: os rendimentos declarados à CVM ({brl(rendimentos)}/cota em 12m) divergem dos proventos "
                          f"pagos na B3 ({brl(pagos)}) — usei os pagos; a rentabilidade efetiva declarada também pode "
                          "estar inconsistente.")
        linhas.append([t, ult["segmento"] or "—", ult["mes"], _r(ult["vp_cota"]), _r(preco), _r(p_vp), round(dy_vp_12, 2),
                       _p(dy_preco), round((rent_12 - 1) * 100, 2), _r(ult["pl"]), ult["cotistas"], _r(ult["taxa_adm"], 3),
                       len(ultimos)])
        try:  # imóveis, inquilinos e ativos financeiros (informe trimestral da CVM)
            from quiron.servicos.fundos import fii_imoveis

            cart = fii_imoveis.carteira(ult["cnpj"])
            sec = fii_imoveis.secoes(t, cart)
            if sec:
                secoes_imoveis.append(sec)
                imoveis_fatos[t] = fii_imoveis.fatos(cart)
        except Exception as e:  # noqa: BLE001 — sem o trimestral, o comparativo sai do mesmo jeito
            avisos.append(f"{t}: imóveis do informe trimestral indisponíveis agora ({type(e).__name__}).")
        fatos.append({"ticker": t, "segmento": ult["segmento"], "mes": ult["mes"], "vp_cota": _r(ult["vp_cota"]),
                      "preco": _r(preco), "p_vp": _r(p_vp), "dy_12m_sobre_vp_pct": round(dy_vp_12, 2),
                      "dy_12m_sobre_preco_pct": _p(dy_preco), "rentabilidade_efetiva_12m_pct": round((rent_12 - 1) * 100, 2),
                      "pl": _r(ult["pl"]), "cotistas": ult["cotistas"]})
    if not linhas:
        raise cvm.FundoNaoEncontrado("nenhum dos FIIs foi encontrado no informe mensal da CVM")
    rel = _base("Comparativo de FIIs — " + ", ".join(l[0] for l in linhas), "fii_comparativo",
                "Informe mensal da CVM + cotação", avisos, ["📊 Cotação: brapi/Yahoo Finance (atraso de até 15 min)"])
    rel.premissas = ["Dividend yield sobre o preço = proventos pagos por cota nos últimos 12 meses (B3, via Yahoo) ÷ "
                     "cotação; sem esse dado, rendimentos declarados à CVM (DY mensal × VP). DY sobre VP = soma dos 12 "
                     "últimos % mensais informados à CVM.",
                     "Segmento: como declarado pela administradora à CVM.",
                     "Rentabilidade efetiva = composição mensal informada pela administradora (rendimentos + variação patrimonial).",
                     "P/VP = cotação ÷ valor patrimonial da cota do último informe."]
    rel.limitacoes = ["Informe mensal chega com 1–2 meses de atraso; o VP pode mudar com reavaliação dos imóveis.",
                      "Imóveis, vacância e inquilinos vêm do informe TRIMESTRAL (defasagem de até 3 meses); contratos e "
                      "prazos de locação estão nos relatórios gerenciais da gestora.",
                      "Rendimento passado não garante distribuição futura. Ganho de capital em FII paga 20% de IR."]
    rel.fatos = {"fiis": fatos, "imoveis": imoveis_fatos}
    melhor_dy = max((f for f in fatos if f["dy_12m_sobre_preco_pct"]), key=lambda f: f["dy_12m_sobre_preco_pct"], default=None)
    rel.resumo = [f"{f['ticker']} ({f['segmento']}): P/VP {num_ou(f['p_vp'])}, DY 12m {pct_ou(f['dy_12m_sobre_preco_pct'])} "
                  f"sobre o preço, rentabilidade efetiva 12m {pct(f['rentabilidade_efetiva_12m_pct'])}." for f in fatos]
    if melhor_dy:
        rel.resumo.append(f"Maior DY sobre o preço: {melhor_dy['ticker']} — confira se é sustentável (gestão, vacância, crédito).")
    t = Tabela("FIIs (último informe mensal)", ["FII", "Segmento", "Informe", "VP/cota (R$)", "Preço (R$)", "P/VP",
                                                "DY 12m s/ VP", "DY 12m s/ preço", "Rentab. efetiva 12m", "PL (R$)",
                                                "Cotistas", "Taxa adm. mês", "Meses"],
               linhas, ["texto", "texto", "texto", "num", "num", "num", "pct", "pct", "pct", "reais", "int", "pct", "int"])
    g = Grafico("Dividend yield 12 meses sobre o preço", "barras_h", [l[0] for l in linhas if l[7] is not None],
                {"DY": [l[7] for l in linhas if l[7] is not None]}, "pct")
    rel.secoes = [Secao("Comparativo", "", [t], [g] if g.rotulos else []), *secoes_imoveis]
    if secoes_imoveis:
        rel.fontes.append("📊 CVM Dados Abertos — informe trimestral de FII (imóveis, inquilinos, ativos)")
    rel.parametros = {"fiis": tickers}
    return redacao.redigir(rel, modo) if redigir else rel


def num_ou(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}".replace(".", ",")


def pct_ou(v: float | None) -> str:
    return "—" if v is None else pct(v)
