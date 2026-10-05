"""Calculadoras financeiras básicas (usadas no Terminal e, na Fase 7, também pelo agente via `CALC`).

Regra do projeto: número sempre calculado em Python, com a memória de cálculo visível.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quiron.nucleo import regras


@dataclass
class Resultado:
    titulo: str
    linhas: list[tuple[str, str]]  # (rótulo, valor formatado)
    memoria: list[str] = field(default_factory=list)  # como foi calculado
    avisos: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"titulo": self.titulo, "linhas": self.linhas, "memoria": self.memoria, "avisos": self.avisos}


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: float, casas: int = 2) -> str:
    return f"{v:.{casas}f}".replace(".", ",") + "%"


def taxa_mensal(taxa_aa: float) -> float:
    return ((1 + taxa_aa / 100) ** (1 / 12) - 1) * 100


def taxa_anual(taxa_am: float) -> float:
    return ((1 + taxa_am / 100) ** 12 - 1) * 100


def juros_compostos(valor_inicial: float, aporte_mensal: float, taxa_aa: float, anos: float) -> Resultado:
    meses = round(anos * 12)
    i = taxa_mensal(taxa_aa) / 100
    fator = (1 + i) ** meses
    vf_inicial = valor_inicial * fator
    vf_aportes = aporte_mensal * ((fator - 1) / i) if i else aporte_mensal * meses  # aporte no fim de cada mês
    total = vf_inicial + vf_aportes
    investido = valor_inicial + aporte_mensal * meses
    return Resultado(
        "Juros compostos",
        [("Valor final", _brl(total)), ("Total investido", _brl(investido)), ("Juros ganhos", _brl(total - investido))],
        [f"Taxa mensal equivalente: {_pct(i * 100, 4)} a.m. = (1 + {_pct(taxa_aa)})^(1/12) − 1",
         f"{meses} meses; aportes no fim de cada mês",
         "VF = VP·(1+i)^n + PMT·((1+i)^n − 1)/i"],
    )


def equivalencia(taxa: float, periodo: str = "aa") -> Resultado:
    """Converte taxa ao ano ↔ ao mês ↔ ao dia útil (252)."""
    aa = taxa if periodo == "aa" else taxa_anual(taxa)
    am = taxa_mensal(aa)
    ad = ((1 + aa / 100) ** (1 / 252) - 1) * 100
    return Resultado(
        "Equivalência de taxas",
        [("Ao ano", _pct(aa, 4)), ("Ao mês", _pct(am, 4)), ("Ao dia útil (252)", _pct(ad, 6))],
        ["Capitalização composta: (1 + taxa)^(período novo / período original) − 1"],
    )


def aliquota_ir(dias: int) -> tuple[float, list[str]]:
    """Alíquota da tabela regressiva de renda fixa (config/regras_mercado.yaml)."""
    r = regras.carregar_regras()
    tabela = r["renda_fixa"]["ir_tabela_regressiva"]
    avisos = [a for a in regras.avisos(r) if a.startswith("renda_fixa")]
    for faixa in tabela:
        if "ate_dias" in faixa and dias <= faixa["ate_dias"]:
            return float(faixa["aliquota"]), avisos
    return float(tabela[-1]["aliquota"]), avisos


def aliquota_iof(dias: int) -> float:
    """IOF regressivo sobre o rendimento de resgates antes de 30 dias (Decreto 6.306/2007, anexo):
    96% no 1º dia, 93% no 2º … 3% no 29º, zero a partir do 30º — fração = ⌊100 × (30 − dias) ÷ 30⌋ %."""
    limite = int(regras.carregar_regras()["renda_fixa"].get("iof", {}).get("aplica_resgate_antes_de_dias", 30))
    if dias >= limite or dias < 1:
        return 0.0
    return (100 * (limite - dias) // limite) / 100


def cdb_x_isento(taxa_isenta_aa: float, taxa_cdb_aa: float, dias: int) -> Resultado:
    """Compara uma aplicação isenta (LCI/LCA) com um CDB tributado no mesmo prazo."""
    aliq, avisos = aliquota_ir(dias)
    iof = aliquota_iof(dias)
    fator = (1 - iof) * (1 - aliq)  # IOF sai primeiro do rendimento; o IR incide sobre o que sobra
    cdb_liquido = taxa_cdb_aa * fator  # aproximação usual sobre a taxa anual
    cdb_equivalente = taxa_isenta_aa / fator
    melhor = "Isento (LCI/LCA)" if taxa_isenta_aa > cdb_liquido else "CDB" if cdb_liquido > taxa_isenta_aa else "Empate"
    return Resultado(
        "CDB × LCI/LCA",
        [("Alíquota de IR no prazo", _pct(aliq * 100, 1)), ("CDB líquido", _pct(cdb_liquido) + " a.a."),
         ("CDB precisa render (bruto) para empatar", _pct(cdb_equivalente) + " a.a."), ("Melhor no prazo", melhor)],
        [f"{dias} dias → alíquota {_pct(aliq * 100, 1)} (tabela regressiva)"]
        + ([f"Resgate antes de 30 dias: IOF de {_pct(iof * 100, 0)} do rendimento (sai antes do IR)"] if iof else []) + [
         "CDB líquido ≈ taxa bruta × (1 − alíquota); equivalente = taxa isenta ÷ (1 − alíquota)",
         "Aproximação sobre a taxa anual; não considera FGC, liquidez nem risco do emissor"],
        avisos,
    )


def taxa_real(nominal_aa: float, inflacao_aa: float) -> Resultado:
    real = ((1 + nominal_aa / 100) / (1 + inflacao_aa / 100) - 1) * 100
    return Resultado(
        "Taxa real (Fisher)",
        [("Taxa real", _pct(real) + " a.a."), ("Diferença simples (aproximação)", _pct(nominal_aa - inflacao_aa) + " a.a.")],
        ["(1 + nominal) ÷ (1 + inflação) − 1"],
    )


def percentual_cdi(percentual: float, cdi_aa: float) -> Resultado:
    """Taxa anual de uma aplicação que paga X% do CDI (base 252)."""
    diario_cdi = (1 + cdi_aa / 100) ** (1 / 252) - 1
    diario = diario_cdi * percentual / 100
    aa = ((1 + diario) ** 252 - 1) * 100
    return Resultado(
        f"{_pct(percentual, 0)} do CDI",
        [("Taxa equivalente", _pct(aa) + " a.a."), ("CDI usado", _pct(cdi_aa) + " a.a.")],
        ["CDI diário = (1 + CDI)^(1/252) − 1; aplica o percentual ao diário e capitaliza 252 dias"],
    )


def financiamento(valor: float, taxa_am: float, meses: int, sistema: str = "price") -> Resultado:
    """Parcelas pela Tabela Price (parcela fixa) ou SAC (amortização fixa)."""
    i = taxa_am / 100
    n = int(meses)
    if n <= 0 or valor <= 0:
        raise ValueError("valor e meses precisam ser positivos")
    if sistema == "sac":
        amort = valor / n
        primeira = amort + valor * i
        ultima = amort + amort * i
        juros = sum((valor - amort * k) * i for k in range(n))
        memoria = [f"Amortização fixa = {_brl(valor)} ÷ {n} = {_brl(amort)}",
                   "Parcela k = amortização + juros sobre o saldo devedor (cai a cada mês)"]
        linhas = [("1ª parcela", _brl(primeira)), ("Última parcela", _brl(ultima))]
    else:
        pmt = valor * i / (1 - (1 + i) ** -n) if i else valor / n
        juros = pmt * n - valor
        memoria = [f"PMT = PV·i ÷ (1 − (1+i)^−n) = {_brl(valor)}·{_pct(taxa_am, 4)} ÷ (1 − (1+{_pct(taxa_am, 4)})^−{n})"]
        linhas = [("Parcela fixa", _brl(pmt))]
    return Resultado(f"Financiamento ({'SAC' if sistema == 'sac' else 'Price'})",
                     linhas + [("Total de juros", _brl(juros)), ("Total pago", _brl(valor + juros)),
                               ("Taxa anual equivalente", _pct(taxa_anual(taxa_am)) + " a.a.")], memoria)


def _fluxos(texto: str | list) -> list[float]:
    if isinstance(texto, list):
        return [float(x) for x in texto]
    partes = [p for p in str(texto).replace("\n", ";").split(";") if p.strip()]
    return [float(p.strip().replace(".", "").replace(",", ".") if "," in p else p.strip()) for p in partes]


def _vpl(taxa: float, fluxos: list[float]) -> float:
    return sum(f / (1 + taxa) ** t for t, f in enumerate(fluxos))


def vpl_tir(fluxos: str, taxa_desconto: float) -> Resultado:
    """VPL e TIR de uma série de fluxos por período (o 1º é o período 0, normalmente negativo)."""
    f = _fluxos(fluxos)
    if len(f) < 2:
        raise ValueError("informe ao menos 2 fluxos separados por ponto e vírgula")
    vpl = _vpl(taxa_desconto / 100, f)
    linhas = [("VPL", _brl(vpl))]
    memoria = [f"VPL = Σ Fₜ ÷ (1 + {_pct(taxa_desconto)})^t, t = 0…{len(f) - 1}"]
    avisos = []
    if any(x < 0 for x in f) and any(x > 0 for x in f):
        baixo, alto = -0.99, 10.0
        if _vpl(baixo, f) * _vpl(alto, f) > 0:
            avisos.append("TIR não encontrada entre −99% e 1000% por período")
        else:
            for _ in range(200):  # bisseção: conferível e sem dependências
                meio = (baixo + alto) / 2
                if _vpl(baixo, f) * _vpl(meio, f) <= 0:
                    alto = meio
                else:
                    baixo = meio
            linhas.append(("TIR", _pct(meio * 100) + " por período"))
            memoria.append("TIR = taxa que zera o VPL (bisseção)")
            trocas = sum(1 for a, b in zip(f, f[1:]) if (a < 0) != (b < 0) and a and b)
            if trocas > 1:
                avisos.append("Fluxo com mais de uma troca de sinal: pode haver mais de uma TIR")
    else:
        avisos.append("TIR exige fluxos com sinais diferentes (investimento e retorno)")
    return Resultado("VPL e TIR", linhas, memoria, avisos)


def aporte_necessario(meta: float, anos: float, taxa_aa: float, valor_inicial: float = 0.0) -> Resultado:
    """Aporte mensal para chegar à meta (aportes no fim de cada mês)."""
    n = round(anos * 12)
    i = taxa_mensal(taxa_aa) / 100
    falta = meta - valor_inicial * (1 + i) ** n
    pmt = max(0.0, falta * i / ((1 + i) ** n - 1) if i else falta / n)
    return Resultado("Aporte necessário", [("Aporte mensal", _brl(pmt)), ("Total aportado", _brl(pmt * n + valor_inicial)),
                                           ("Juros no período", _brl(meta - pmt * n - valor_inicial))],
                     [f"Taxa mensal: {_pct(i * 100, 4)}; {n} meses",
                      "PMT = (meta − VP·(1+i)^n) · i ÷ ((1+i)^n − 1)"],
                     ["Use taxa REAL (acima da inflação) se a meta estiver em valores de hoje"])


def renda_aposentadoria(patrimonio: float, taxa_real_aa: float, anos: float = 0) -> Resultado:
    """Renda mensal (em valores de hoje) que o patrimônio sustenta: por N anos (consome o capital) ou perpétua (anos=0)."""
    i = taxa_mensal(taxa_real_aa) / 100
    if anos and anos > 0:
        n = round(anos * 12)
        renda = patrimonio * i / (1 - (1 + i) ** -n) if i else patrimonio / n
        memoria = [f"PMT = PV·i ÷ (1 − (1+i)^−n), {n} meses, i = {_pct(i * 100, 4)} real ao mês"]
        titulo = f"Renda por {anos:g} anos (consome o capital)"
    else:
        renda = patrimonio * i
        memoria = [f"Perpetuidade: renda = patrimônio × {_pct(i * 100, 4)} real ao mês (preserva o capital)"]
        titulo = "Renda perpétua (preserva o capital)"
    return Resultado(titulo, [("Renda mensal", _brl(renda)), ("Renda anual", _brl(renda * 12))], memoria,
                     ["Valores de hoje (taxa real); não considera IR sobre os rendimentos nem taxas"])


def pu_prefixado(taxa_aa: float, dias_uteis: int, valor_face: float = 1000.0) -> Resultado:
    """Preço unitário de um título prefixado sem cupom (ex.: LTN / Tesouro Prefixado), base 252."""
    pu = valor_face / (1 + taxa_aa / 100) ** (int(dias_uteis) / 252)
    return Resultado("PU de título prefixado", [("PU", _brl(pu)), ("Desconto sobre o valor de face", _pct((1 - pu / valor_face) * 100))],
                     [f"PU = {_brl(valor_face)} ÷ (1 + {_pct(taxa_aa)})^({int(dias_uteis)}/252)"])


def duration(fluxos: str, taxa_aa: float) -> Resultado:
    """Duration de Macaulay e modificada de fluxos ANUAIS a partir do ano 1 (ex.: cupons e principal)."""
    f = _fluxos(fluxos)
    y = taxa_aa / 100
    vps = [x / (1 + y) ** t for t, x in enumerate(f, 1)]
    preco = sum(vps)
    if preco <= 0:
        raise ValueError("fluxos precisam ter valor presente positivo")
    mac = sum(t * v for t, v in enumerate(vps, 1)) / preco
    mod = mac / (1 + y)
    return Resultado("Duration", [("Preço (VP dos fluxos)", _brl(preco)), ("Duration de Macaulay", f"{mac:.2f} anos".replace(".", ",")),
                                  ("Duration modificada", f"{mod:.2f}".replace(".", ",")),
                                  ("Variação de preço p/ +1 p.p.", _pct(-mod, 2) + " (aprox.)")],
                     ["Macaulay = Σ t·VPₜ ÷ Σ VPₜ; modificada = Macaulay ÷ (1 + taxa)",
                      "ΔPreço% ≈ −modificada × Δtaxa"])


CALCULADORAS = {
    "juros_compostos": juros_compostos,
    "equivalencia": equivalencia,
    "cdb_x_isento": cdb_x_isento,
    "taxa_real": taxa_real,
    "percentual_cdi": percentual_cdi,
    "financiamento": financiamento,
    "vpl_tir": vpl_tir,
    "aporte_necessario": aporte_necessario,
    "renda_aposentadoria": renda_aposentadoria,
    "pu_prefixado": pu_prefixado,
    "duration": duration,
}

# Campos de cada calculadora (fonte única para o Terminal, o agente/MCP e o Telegram):
# (nome, rótulo, padrão, tipo: num | int | texto | opção, opções)
ESQUEMAS: dict[str, dict] = {
    "juros_compostos": {"nome": "Juros compostos", "campos": [("valor_inicial", "Valor inicial (R$)", 10000, "num"),
                        ("aporte_mensal", "Aporte mensal (R$)", 1000, "num"), ("taxa_aa", "Taxa (% a.a.)", 12, "num"),
                        ("anos", "Prazo (anos)", 10, "num")]},
    "equivalencia": {"nome": "Equivalência", "campos": [("taxa", "Taxa (%)", 12, "num"),
                     ("periodo", "Período da taxa", "aa", "opção", [["aa", "ao ano"], ["am", "ao mês"]])]},
    "cdb_x_isento": {"nome": "CDB × LCI", "campos": [("taxa_isenta_aa", "LCI/LCA (% a.a.)", 11, "num"),
                     ("taxa_cdb_aa", "CDB (% a.a.)", 13.5, "num"), ("dias", "Prazo (dias)", 720, "int")]},
    "taxa_real": {"nome": "Taxa real", "campos": [("nominal_aa", "Taxa nominal (% a.a.)", 13.75, "num"),
                  ("inflacao_aa", "Inflação (% a.a.)", 4.5, "num")]},
    "percentual_cdi": {"nome": "% do CDI", "campos": [("percentual", "% do CDI", 110, "num")]},
    "financiamento": {"nome": "Financiamento", "campos": [("valor", "Valor financiado (R$)", 300000, "num"),
                      ("taxa_am", "Taxa (% a.m.)", 1, "num"), ("meses", "Prazo (meses)", 360, "int"),
                      ("sistema", "Sistema", "price", "opção", [["price", "Price (parcela fixa)"], ["sac", "SAC"]])]},
    "vpl_tir": {"nome": "VPL e TIR", "campos": [("fluxos", "Fluxos (;) — 1º = hoje", "-1000; 300; 400; 500", "texto"),
                ("taxa_desconto", "Taxa de desconto (% por período)", 10, "num")]},
    "aporte_necessario": {"nome": "Aporte p/ meta", "campos": [("meta", "Meta (R$)", 1000000, "num"),
                          ("anos", "Prazo (anos)", 20, "num"), ("taxa_aa", "Taxa (% a.a.)", 5, "num"),
                          ("valor_inicial", "Já tenho (R$)", 0, "num")]},
    "renda_aposentadoria": {"nome": "Renda aposentadoria", "campos": [("patrimonio", "Patrimônio (R$)", 2000000, "num"),
                            ("taxa_real_aa", "Taxa real (% a.a.)", 4, "num"),
                            ("anos", "Por quantos anos (0 = perpétua)", 0, "num")]},
    "pu_prefixado": {"nome": "PU prefixado", "campos": [("taxa_aa", "Taxa (% a.a.)", 13.5, "num"),
                     ("dias_uteis", "Dias úteis até o vencimento", 504, "int"), ("valor_face", "Valor de face (R$)", 1000, "num")]},
    "duration": {"nome": "Duration", "campos": [("fluxos", "Fluxos anuais (;) a partir do ano 1", "10; 10; 10; 110", "texto"),
                 ("taxa_aa", "Taxa (% a.a.)", 10, "num")]},
}


def executar(nome: str, entrada: dict) -> Resultado:
    """Converte a entrada (textos do formulário, com vírgula decimal) pelos tipos do esquema e calcula."""
    if nome not in CALCULADORAS:
        raise KeyError(nome)
    tipos = {c[0]: c[3] for c in ESQUEMAS[nome]["campos"]}
    args = {}
    for k, v in entrada.items():
        if k not in tipos and k != "cdi_aa":
            continue
        if v in ("", None):
            continue
        t = tipos.get(k, "num")
        if t in {"texto", "opção"}:
            args[k] = str(v)
        else:
            valor = float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in v else float(v)
            args[k] = int(valor) if t == "int" else valor
    return CALCULADORAS[nome](**args)
