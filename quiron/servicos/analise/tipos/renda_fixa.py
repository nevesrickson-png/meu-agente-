"""Análise: comparativo de renda fixa (CDB/LC, LCI/LCA/CRI/CRA/incentivadas, Tesouro Selic, IPCA+ e Prefixado).

Coleta (Banco Central SGS + Focus, Tesouro Transparente) → cenário mês a mês → valores brutos, IR (tabela regressiva de
`config/regras_mercado.yaml`), custódia do Tesouro, líquido, taxa líquida e ganho real → sensibilidade (CDI ±2 p.p.,
IPCA +2 p.p.) → relatório com tabelas, gráficos e planilha. Toda conta é feita aqui, em Python.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from quiron.nucleo import regras
from quiron.servicos.analise import redacao
from quiron.servicos.analise.fila import tipo
from quiron.servicos.analise.relatorio import Grafico, Relatorio, Secao, Tabela, brl, pct
from quiron.servicos.calculadoras import aliquota_ir

ISENTOS = {"lci", "lca", "cri", "cra", "debenture_incentivada"}
NOMES = {"cdb": "CDB", "lc": "LC", "lci": "LCI", "lca": "LCA", "cri": "CRI", "cra": "CRA",
         "debenture": "Debênture", "debenture_incentivada": "Debênture incentivada", "cdb_pre": "CDB prefixado",
         "ipca_mais": "Título IPCA+", "tesouro_selic": "Tesouro Selic", "tesouro_ipca": "Tesouro IPCA+",
         "tesouro_prefixado": "Tesouro Prefixado"}
PADRAO_OPCOES = [{"tipo": "cdb", "percentual_cdi": 110}, {"tipo": "lci", "percentual_cdi": 92},
                 {"tipo": "tesouro_selic"}, {"tipo": "tesouro_ipca"}, {"tipo": "tesouro_prefixado"}]
SPREAD_CDI_SELIC = 0.10  # CDI ≈ Selic meta − 0,10 p.p. (premissa declarada)


# ---------------------------------------------------------------- cenário (mês a mês)
@dataclass
class Cenario:
    nome: str
    selic: list[float]  # % a.a. em cada mês do horizonte
    ipca: list[float]  # % a.a. em cada mês

    @property
    def cdi(self) -> list[float]:
        return [s - SPREAD_CDI_SELIC for s in self.selic]

    def deslocado(self, nome: str, juros: float = 0.0, inflacao: float = 0.0) -> "Cenario":
        return Cenario(nome, [max(0.0, s + juros) for s in self.selic], [i + inflacao for i in self.ipca])


def montar_cenario(meses: int, selic_atual: float, selic_fim_ano: dict[int, float], ipca_ano: dict[int, float],
                   hoje: date | None = None) -> Cenario:
    """Selic: interpolação linear entre a atual e as medianas do Focus para o fim de cada ano (depois, constante).
    IPCA: mediana do Focus do ano-calendário de cada mês (último ano conhecido se faltar)."""
    hoje = hoje or date.today()
    marcos = [(0.0, selic_atual)]
    for ano in sorted(selic_fim_ano):
        t = (date(ano, 12, 31) - hoje).days / 365.25 * 12
        if t > 0:
            marcos.append((t, selic_fim_ano[ano]))
    selic, ipca = [], []
    for m in range(meses):
        meio = m + 0.5
        anteriores = [mk for mk in marcos if mk[0] <= meio]
        posteriores = [mk for mk in marcos if mk[0] > meio]
        a = anteriores[-1]
        if posteriores:
            b = posteriores[0]
            selic.append(a[1] + (b[1] - a[1]) * (meio - a[0]) / (b[0] - a[0]))
        else:
            selic.append(a[1])
        ano_mes = (hoje.year * 12 + hoje.month - 1 + m) // 12
        conhecido = [y for y in ipca_ano if y <= ano_mes]
        ipca.append(ipca_ano[max(conhecido)] if conhecido else ipca_ano[min(ipca_ano)])
    return Cenario("Base (Focus)", selic, ipca)


# ---------------------------------------------------------------- cálculo de cada opção
@dataclass
class Opcao:
    tipo: str
    nome: str
    percentual_cdi: float | None = None
    taxa_pre: float | None = None  # % a.a.
    taxa_real: float | None = None  # % a.a. acima do IPCA
    spread_selic: float | None = None  # Tesouro Selic: % a.a. acima da Selic
    vencimento: date | None = None
    referencia: str = ""

    @property
    def isento(self) -> bool:
        return self.tipo in ISENTOS

    @property
    def tesouro(self) -> bool:
        return self.tipo.startswith("tesouro_")

    def descricao_taxa(self) -> str:
        if self.percentual_cdi is not None:
            return f"{pct(self.percentual_cdi, 1)} do CDI"
        if self.taxa_pre is not None:
            return f"{pct(self.taxa_pre)} a.a. (pré)"
        if self.taxa_real is not None:
            return f"IPCA + {pct(self.taxa_real)} a.a."
        if self.spread_selic is not None:
            return f"Selic + {pct(self.spread_selic, 4)} a.a."
        return "—"

    def taxa_no_mes(self, c: Cenario, m: int) -> float:
        """Taxa anual (%) válida no mês m do horizonte."""
        if self.percentual_cdi is not None:
            diario = (1 + c.cdi[m] / 100) ** (1 / 252) - 1
            return ((1 + diario * self.percentual_cdi / 100) ** 252 - 1) * 100
        if self.taxa_pre is not None:
            return self.taxa_pre
        if self.taxa_real is not None:
            return ((1 + c.ipca[m] / 100) * (1 + self.taxa_real / 100) - 1) * 100
        if self.spread_selic is not None:
            return ((1 + c.cdi[m] / 100) * (1 + self.spread_selic / 100) - 1) * 100
        raise ValueError(f"{self.nome}: falta a taxa")


@dataclass
class Resultado:
    opcao: Opcao
    bruto: float
    ir: float
    custodia: float
    liquido: float
    taxa_liquida_aa: float
    inflacao_periodo: float  # %
    ganho_real: float  # R$ acima da inflação
    taxa_real_aa: float
    aliquota: float
    serie_liquida: list[float] = field(default_factory=list)  # valor líquido se resgatado em cada mês


def calcular(op: Opcao, valor: float, meses: int, c: Cenario, custodia_aa: float = 0.002) -> Resultado:
    custo_mes = (1 - custodia_aa) ** (1 / 12) if op.tesouro and not (op.tipo == "tesouro_selic" and valor <= 10_000) else 1.0
    bruto, inflacao, serie = valor, 1.0, []
    custodia_acum = 0.0
    for m in range(meses):
        bruto *= (1 + op.taxa_no_mes(c, m) / 100) ** (1 / 12)
        antes = bruto
        bruto *= custo_mes
        custodia_acum += antes - bruto
        inflacao *= (1 + c.ipca[m] / 100) ** (1 / 12)
        aliq_m = 0.0 if op.isento else aliquota_ir(round((m + 1) * 365 / 12))[0]
        serie.append(bruto - max(0.0, bruto - valor) * aliq_m)
    aliq = 0.0 if op.isento else aliquota_ir(round(meses * 365 / 12))[0]
    ir = max(0.0, bruto - valor) * aliq
    liquido = bruto - ir
    anos = meses / 12
    taxa_liq = ((liquido / valor) ** (1 / anos) - 1) * 100
    real = ((liquido / valor) / inflacao) ** (1 / anos) - 1
    return Resultado(op, bruto + custodia_acum, ir, custodia_acum, liquido, taxa_liq, (inflacao - 1) * 100,
                     liquido - valor * inflacao, real * 100, aliq, serie)


# ---------------------------------------------------------------- dados de mercado
@dataclass
class Mercado:
    selic: float
    data_selic: date
    selic_fim_ano: dict[int, float]
    ipca_ano: dict[int, float]
    tesouro: dict[str, Any]  # tipo → Titulo
    data_tesouro: date | None
    fontes: list[str]
    avisos: list[str]


def coletar(anos: float) -> Mercado:
    from quiron.servicos.mercado import bcb, tesouro

    fontes, avisos = [], []
    s = bcb.sgs("selic_meta", 1)
    fontes.append(f"📊 {s.fonte} — Selic meta {pct(s.ultimo.valor)} a.a. em {s.ultimo.data:%d/%m/%Y}")
    if s.desatualizado:
        avisos.append("Selic veio do último valor guardado (fonte fora do ar).")
    hoje = date.today()
    selic_fim, ipca_ano = {}, {}
    for ano in range(hoje.year, hoje.year + int(anos) + 2):
        for indicador, destino in (("selic", selic_fim), ("ipca", ipca_ano)):
            try:
                e = bcb.focus(indicador, ano)
                destino[ano] = e.mediana
                if ano == hoje.year + 1 or (ano == hoje.year and indicador == "ipca"):
                    fontes.append(f"📊 {e.fonte} — mediana {indicador.upper()} {ano}: {pct(e.mediana)} ({e.data:%d/%m/%Y})")
            except Exception:  # noqa: BLE001 — Focus pode não ter anos distantes
                pass
    if not ipca_ano:
        try:
            i12 = bcb.sgs("ipca_12m", 1)
            ipca_ano[hoje.year] = i12.ultimo.valor
            fontes.append(f"📊 {i12.fonte} — IPCA 12 meses {pct(i12.ultimo.valor)} ({i12.ultimo.data:%m/%Y})")
            avisos.append("Focus indisponível: inflação projetada = IPCA dos últimos 12 meses.")
        except Exception:  # noqa: BLE001
            ipca_ano[hoje.year] = 4.5
            avisos.append("Sem dado de inflação: usei 4,5% a.a. (premissa manual).")
    if not selic_fim:
        avisos.append("Focus da Selic indisponível: Selic constante no horizonte.")
    titulos, data_tes = {}, None
    try:
        tab = tesouro.titulos_atuais()
        data_tes = tab.data_base
        alvo = date(hoje.year + int(anos), hoje.month, min(hoje.day, 28))
        for chave, nome_tipo in (("tesouro_selic", "selic"), ("tesouro_ipca", "ipca_mais"), ("tesouro_prefixado", "prefixado")):
            candidatos = [t for t in tesouro.por_tipo(tab, nome_tipo) if t.taxa_compra is not None]
            if candidatos:
                depois = [t for t in candidatos if t.vencimento >= alvo]
                titulos[chave] = min(depois, key=lambda t: t.vencimento) if depois else max(candidatos, key=lambda t: t.vencimento)
        fontes.append(f"📊 {tab.fonte} — taxas de compra de {tab.data_base:%d/%m/%Y}")
        if tab.desatualizado:
            avisos.append("Taxas do Tesouro vieram do último arquivo guardado (fonte fora do ar).")
    except Exception as e:  # noqa: BLE001
        logging.warning("Tesouro indisponível: %s", e)
        avisos.append("Tesouro Transparente indisponível: títulos públicos ficaram de fora.")
    return Mercado(s.ultimo.valor, s.ultimo.data, selic_fim, ipca_ano, titulos, data_tes, fontes, avisos)


def montar_opcoes(pedidas: list[dict[str, Any]], mercado: Mercado) -> tuple[list[Opcao], list[str]]:
    opcoes, avisos = [], []
    for o in pedidas:
        t = str(o.get("tipo", "")).lower().strip()
        nome = str(o.get("nome") or "").strip()
        if nome.lower().replace(" ", "_") == t:  # o agente às vezes repete o tipo como nome: usa o nome real
            nome = ""
        if t in {"tesouro_selic", "tesouro_ipca", "tesouro_prefixado"}:
            tit = mercado.tesouro.get(t)
            if not tit:
                avisos.append(f"{NOMES[t]} sem taxa disponível agora — fora do comparativo.")
                continue
            base = dict(tipo=t, nome=nome or tit.nome, vencimento=tit.vencimento, referencia="Tesouro Direto")
            if t == "tesouro_selic":
                opcoes.append(Opcao(spread_selic=tit.taxa_compra, **base))
            elif t == "tesouro_ipca":
                opcoes.append(Opcao(taxa_real=tit.taxa_compra, **base))
            else:
                opcoes.append(Opcao(taxa_pre=tit.taxa_compra, **base))
            continue
        if t not in NOMES:
            avisos.append(f"Tipo “{t}” não reconhecido — ignorado.")
            continue
        op = Opcao(t, nome or NOMES[t])
        if o.get("percentual_cdi") is not None:
            op.percentual_cdi = float(o["percentual_cdi"])
        elif o.get("taxa_pre") is not None:
            op.taxa_pre = float(o["taxa_pre"])
        elif o.get("taxa_real") is not None:
            op.taxa_real = float(o["taxa_real"])
        else:
            avisos.append(f"{op.nome}: informe percentual_cdi, taxa_pre ou taxa_real — ignorado.")
            continue
        if not nome:
            op.nome = f"{NOMES[t]} {op.descricao_taxa()}"
        opcoes.append(op)
    return opcoes, avisos


# ---------------------------------------------------------------- relatório
def montar_relatorio(valor: float, anos: float, opcoes: list[Opcao], base: Cenario, mercado: Mercado,
                     custodia_aa: float) -> Relatorio:
    meses = max(1, round(anos * 12))
    resultados = sorted((calcular(o, valor, meses, base, custodia_aa) for o in opcoes), key=lambda r: -r.liquido)
    melhor, pior = resultados[0], resultados[-1]
    cenarios = [base.deslocado("CDI −2 p.p.", juros=-2), base.deslocado("CDI +2 p.p.", juros=2),
                base.deslocado("IPCA +2 p.p.", inflacao=2)]
    sens = {c.nome: sorted(((calcular(o, valor, meses, c, custodia_aa).liquido, o.nome) for o in opcoes), reverse=True)
            for c in cenarios}
    cdi_medio = sum(base.cdi) / meses
    ipca_medio = sum(base.ipca) / meses
    aliq_prazo = aliquota_ir(round(meses * 365 / 12))[0]
    isentas = [r for r in resultados if r.opcao.isento and r.opcao.percentual_cdi is not None]
    equivalencias = [(r.opcao.nome, r.opcao.percentual_cdi / (1 - aliq_prazo)) for r in isentas]

    rel = Relatorio(
        f"Comparativo de renda fixa — {brl(valor)} por {anos:g} ano{'s' if anos != 1 else ''}",
        "renda_fixa_comparativo",
        subtitulo=", ".join(o.nome for o in opcoes),
        fatos={"valor": valor, "anos": anos, "meses": meses, "melhor": melhor.opcao.nome, "melhor_liquido": round(melhor.liquido, 2),
               "pior": pior.opcao.nome, "pior_liquido": round(pior.liquido, 2),
               "diferenca_melhor_pior": round(melhor.liquido - pior.liquido, 2), "cdi_medio": round(cdi_medio, 2),
               "ipca_medio": round(ipca_medio, 2), "selic_atual": mercado.selic, "aliquota_ir_prazo_pct": aliq_prazo * 100,
               "resultados": [{"opcao": r.opcao.nome, "taxa": r.opcao.descricao_taxa(), "liquido": round(r.liquido, 2),
                               "taxa_liquida_aa": round(r.taxa_liquida_aa, 2), "taxa_real_aa": round(r.taxa_real_aa, 2),
                               "ganho_real": round(r.ganho_real, 2), "ir": round(r.ir, 2), "custodia": round(r.custodia, 2)}
                              for r in resultados],
               "sensibilidade": {k: [{"opcao": n, "liquido": round(v, 2)} for v, n in lst] for k, lst in sens.items()},
               "equivalencia_cdb": [{"isento": n, "cdb_equivalente_pct_cdi": round(v, 1)} for n, v in equivalencias]},
        resumo=[f"Melhor no cenário base: **{melhor.opcao.nome}**, {brl(melhor.liquido)} líquidos "
                f"({pct(melhor.taxa_liquida_aa)} a.a. líquido; {pct(melhor.taxa_real_aa)} a.a. acima da inflação).",
                f"Diferença entre a melhor e a pior opção: {brl(melhor.liquido - pior.liquido)}.",
                *[f"{n} equivale a um CDB de {pct(v, 1)} do CDI no prazo (IR de {pct(aliq_prazo * 100, 1)})."
                  for n, v in equivalencias],
                f"Se o CDI ficar 2 p.p. abaixo do esperado, lidera: {sens['CDI −2 p.p.'][0][1]}; "
                f"2 p.p. acima: {sens['CDI +2 p.p.'][0][1]}."],
        premissas=[f"Valor aplicado {brl(valor)}, resgate no fim de {meses} meses (sem resgates no meio).",
                   f"Selic hoje {pct(mercado.selic)} a.a.; trajetória pelas medianas do Focus para o fim de cada ano "
                   f"({', '.join(f'{a}: {pct(v)}' for a, v in sorted(mercado.selic_fim_ano.items())) or 'sem Focus: constante'}).",
                   f"CDI = Selic − {pct(SPREAD_CDI_SELIC)}; CDI médio projetado no período: {pct(cdi_medio)} a.a.",
                   f"Inflação (IPCA) pelo Focus de cada ano ({', '.join(f'{a}: {pct(v)}' for a, v in sorted(mercado.ipca_ano.items()))}); "
                   f"média no período {pct(ipca_medio)} a.a.",
                   f"IR pela tabela regressiva (no prazo: {pct(aliq_prazo * 100, 1)}); LCI/LCA/CRI/CRA/incentivadas isentas para PF.",
                   f"Tesouro: taxa de compra do dia, custódia B3 de {pct(custodia_aa * 100)} a.a. (Tesouro Selic isento até "
                   "R$ 10 mil), carregado até o fim do prazo pela mesma taxa."],
        fontes=mercado.fontes + ["📊 Regras tributárias e de custódia: config/regras_mercado.yaml"],
        limitacoes=["Não considera risco de crédito do emissor, FGC, liquidez antes do vencimento nem marcação a mercado.",
                    "Títulos com vencimento depois do prazo foram avaliados sem marcação a mercado no resgate (na "
                    "prática, vender antes pode dar ganho ou perda).",
                    "Projeções do Focus mudam toda semana; a sensibilidade mostra o efeito de juros e inflação diferentes.",
                    "Cálculo mensal aproximado (sem calendário de dias úteis); diferenças de centavos são esperadas."],
        avisos=mercado.avisos + [a for a in regras.avisos() if a.startswith(("renda_fixa", "tesouro_direto"))],
    )
    tabela = Tabela("Resultado no vencimento (cenário base)",
                    ["Opção", "Taxa", "Bruto (R$)", "IR (R$)", "Custódia (R$)", "Líquido (R$)", "Líquido a.a.", "Real a.a.",
                     "Ganho real (R$)"],
                    [[r.opcao.nome, r.opcao.descricao_taxa(), round(r.bruto, 2), round(r.ir, 2), round(r.custodia, 2),
                      round(r.liquido, 2), round(r.taxa_liquida_aa, 2), round(r.taxa_real_aa, 2), round(r.ganho_real, 2)]
                     for r in resultados],
                    ["texto", "texto", "reais", "reais", "reais", "reais", "pct", "pct", "reais"],
                    "Bruto = antes de IR e custódia. Ganho real = líquido menos o valor corrigido pela inflação projetada.")
    venc = [[r.opcao.nome, f"{r.opcao.vencimento:%d/%m/%Y}", r.opcao.referencia] for r in resultados if r.opcao.vencimento]
    tabelas = [tabela]
    if venc:
        tabelas.append(Tabela("Títulos públicos usados", ["Título", "Vencimento", "Fonte"], venc))
    sens_tab = Tabela("Sensibilidade: valor líquido em outros cenários (R$)", ["Opção", "Base", *sens.keys()],
                      [[r.opcao.nome, round(r.liquido, 2),
                        *[round(next(v for v, n in sens[c] if n == r.opcao.nome), 2) for c in sens]] for r in resultados],
                      ["texto", "reais", "reais", "reais", "reais"], "Cenários deslocam toda a trajetória da Selic/CDI ou do IPCA.")
    if equivalencias:
        tabelas.append(Tabela("Isento × CDB equivalente", ["Isento", "CDB precisa pagar (% do CDI)"],
                              [[n, round(v, 1)] for n, v in equivalencias], ["texto", "num"],
                              f"Equivalente = % do CDI ÷ (1 − {pct(aliq_prazo * 100, 1)}) no prazo."))
    graf_barras = Grafico("Valor líquido no vencimento (cenário base)", "barras_h", [r.opcao.nome for r in resultados],
                          {"Líquido": [round(r.liquido, 2) for r in resultados]}, "brl")
    passo = 1 if meses <= 36 else 3
    graf_linhas = Grafico("Valor líquido se resgatado em cada mês", "linhas",
                          [f"{m + 1}" for m in range(0, meses, passo)],
                          {r.opcao.nome: [round(v, 2) for v in r.serie_liquida[::passo]] for r in resultados[:5]}, "brl",
                          "meses", "Inclui o IR que seria cobrado se o resgate fosse naquele mês (tabela regressiva).")
    rel.secoes = [Secao("Resultado", "", tabelas, [graf_barras]), Secao("Ao longo do tempo", "", [], [graf_linhas]),
                  Secao("Sensibilidade", "", [sens_tab])]
    return rel


@tipo("renda_fixa_comparativo",
      descricao="Compara aplicações de renda fixa (CDB/LC, LCI/LCA, CRI/CRA, incentivadas, Tesouro Selic/IPCA+/Prefixado) "
                "com as taxas de hoje: líquido de IR e custódia, ganho real e sensibilidade a juros e inflação.",
      parametros={"valor": "valor aplicado em R$ (padrão 100000)",
                  "prazo_anos": "prazo em anos, aceita fração (padrão 2)",
                  "opcoes": "lista; cada item com tipo (cdb, lc, lci, lca, cri, cra, debenture, debenture_incentivada, "
                            "cdb_pre, ipca_mais, tesouro_selic, tesouro_ipca, tesouro_prefixado) e a taxa: percentual_cdi "
                            "(ex.: 110), taxa_pre (% a.a.) ou taxa_real (% acima do IPCA); nome opcional. Tesouro usa a "
                            "taxa do dia. Padrão: CDB 110% CDI, LCI 92% CDI e os 3 Tesouros"})
def comparativo(params: dict[str, Any], modo: str = "entregar", mercado: Mercado | None = None,
                hoje: date | None = None, redigir: bool = True) -> Relatorio:
    valor = float(params.get("valor") or 100_000)
    anos = float(params.get("prazo_anos") or 2)
    if valor <= 0 or not 1 / 12 <= anos <= 30:
        raise ValueError("valor precisa ser positivo e prazo entre 1 mês e 30 anos")
    mercado = mercado or coletar(anos)
    opcoes, avisos = montar_opcoes(params.get("opcoes") or PADRAO_OPCOES, mercado)
    if not opcoes:
        raise ValueError("nenhuma opção válida para comparar")
    meses = max(1, round(anos * 12))
    base = montar_cenario(meses, mercado.selic, mercado.selic_fim_ano, mercado.ipca_ano, hoje)
    custodia = float(regras.carregar_regras().get("tesouro_direto", {}).get("taxa_custodia_b3", 0.002))
    rel = montar_relatorio(valor, anos, opcoes, base, mercado, custodia)
    rel.avisos = avisos + rel.avisos
    rel.parametros = params
    return redacao.redigir(rel, modo) if redigir else rel
