"""Demonstrações financeiras das companhias abertas pela CVM Dados Abertos (DFP anual, ITR trimestral, FCA cadastro).

Os zips anuais ficam em `dados/cache_cvm/` (anos fechados: renovados a cada 30 dias; ano corrente: a cada dia).
As contas são extraídas pelo código do plano de contas padronizado da CVM (empresas não financeiras); itens que
variam de empresa para empresa (depreciação, capex, arrendamentos) são achados pelo nome dentro do grupo certo.
Valores sempre em R$ (a CVM publica em milhares — `ESCALA_MOEDA`).
"""

from __future__ import annotations

import csv
import io
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from quiron.nucleo.config import pasta_dados
from quiron.servicos.fundos.cvm import baixar, digitos, formatar_cnpj, normalizar

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
FONTE = "CVM Dados Abertos (DFP/ITR/FCA)"

# código → nome padronizado (plano de contas da CVM para empresas não financeiras)
DRE = {"3.01": "receita", "3.02": "custo", "3.03": "lucro_bruto", "3.04.01": "desp_vendas", "3.04.02": "desp_ga",
       "3.05": "ebit", "3.06": "resultado_financeiro", "3.06.01": "receitas_financeiras", "3.06.02": "despesas_financeiras",
       "3.07": "lair", "3.08": "ir", "3.11": "lucro", "3.11.01": "lucro_controladores"}
BPA = {"1": "ativo", "1.01": "ativo_circulante", "1.01.01": "caixa", "1.01.02": "aplicacoes", "1.01.03": "recebiveis",
       "1.01.04": "estoques", "1.02.03": "imobilizado", "1.02.04": "intangivel"}
BPP = {"2.01": "passivo_circulante", "2.01.02": "fornecedores", "2.01.04": "divida_cp", "2.02.01": "divida_lp",
       "2.03": "pl"}


class EmpresaNaoEncontrada(LookupError):
    pass


# ---------------------------------------------------------------- arquivos
def pasta_cache() -> Path:
    p = pasta_dados() / "cache_cvm"
    p.mkdir(parents=True, exist_ok=True)
    return p


def arquivo(doc: str, ano: int) -> Path | None:
    """Zip anual (dfp/itr/fca) em cache. None se a CVM ainda não publicou."""
    destino = pasta_cache() / f"{doc}_cia_aberta_{ano}.zip"
    ttl = 86400 if ano >= date.today().year else 30 * 86400
    if destino.exists() and destino.stat().st_mtime > time.time() - ttl:
        return destino
    try:
        tmp = baixar(f"{BASE}/{doc.upper()}/DADOS/{doc}_cia_aberta_{ano}.zip")
    except Exception:  # noqa: BLE001 — sem rede: usa o que tiver em cache
        return destino if destino.exists() else None
    if tmp is None:
        return destino if destino.exists() else None
    tmp.replace(destino)
    return destino


def _linhas(z: zipfile.ZipFile, nome: str):
    if nome not in z.namelist():
        return
    with z.open(nome) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


# ---------------------------------------------------------------- cadastro (FCA)
@dataclass
class Empresa:
    cnpj: str
    cd_cvm: str
    nome: str
    setor: str
    descricao: str
    tickers: list[str] = field(default_factory=list)
    segmento: str = ""

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)

    @property
    def ticker(self) -> str:
        """Ticker principal: ON se houver, senão o primeiro (units/PN)."""
        ons = [t for t in self.tickers if t.endswith("3")]
        return (ons or self.tickers or [""])[0]


_EMPRESAS: dict[str, Empresa] | None = None


def empresas() -> dict[str, Empresa]:
    global _EMPRESAS
    if _EMPRESAS is not None:
        return _EMPRESAS
    saida: dict[str, Empresa] = {}
    hoje = date.today()
    for ano in (hoje.year, hoje.year - 1):
        arq = arquivo("fca", ano)
        if not arq:
            continue
        with zipfile.ZipFile(arq) as z:
            for l in _linhas(z, f"fca_cia_aberta_geral_{ano}.csv"):
                c = digitos(l["CNPJ_Companhia"])
                if c in saida or l.get("Situacao_Registro_CVM", "Ativo") != "Ativo":
                    continue
                saida[c] = Empresa(c, l["Codigo_CVM"].lstrip("0"), l["Nome_Empresarial"], l.get("Setor_Atividade", ""),
                                   l.get("Descricao_Atividade", "").strip())
            for l in _linhas(z, f"fca_cia_aberta_valor_mobiliario_{ano}.csv"):
                c = digitos(l["CNPJ_Companhia"])
                t = (l.get("Codigo_Negociacao") or "").strip().upper()
                if c in saida and t and not l.get("Data_Fim_Negociacao") and l.get("Mercado") == "Bolsa" \
                        and t not in saida[c].tickers and re.fullmatch(r"[A-Z]{4}\d{1,2}", t):
                    saida[c].tickers.append(t)
                    saida[c].segmento = saida[c].segmento or l.get("Segmento", "")
        if saida:
            break
    _EMPRESAS = saida
    return saida


def buscar(termo: str, limite: int = 8) -> list[Empresa]:
    t = termo.strip().upper()
    todas = empresas()
    if re.fullmatch(r"[A-Z]{4}\d{1,2}", t):
        achadas = [e for e in todas.values() if t in e.tickers or (len(t) >= 4 and any(x[:4] == t[:4] for x in e.tickers))]
        return sorted(achadas, key=lambda e: t not in e.tickers)[:limite]
    d = digitos(t)
    if len(d) >= 8:
        return [e for c, e in todas.items() if c.startswith(d)][:limite]
    palavras = normalizar(t).split()
    achadas = [e for e in todas.values() if all(p in normalizar(e.nome) for p in palavras)]
    return sorted(achadas, key=lambda e: (not e.tickers, len(e.nome)))[:limite]


def empresa(termo: str) -> Empresa:
    achadas = buscar(termo, 1)
    if not achadas:
        raise EmpresaNaoEncontrada(f"companhia “{termo}” não encontrada no cadastro da CVM (FCA)")
    return achadas[0]


# ---------------------------------------------------------------- demonstrações
@dataclass
class Periodo:
    """Valores de um período (R$). `tipo`: anual (DFP) | ytd (ITR acumulado no ano) | trimestre | ltm."""

    rotulo: str
    fim: str  # AAAA-MM-DD
    tipo: str
    valores: dict[str, float] = field(default_factory=dict)
    consolidado: bool = True

    def __getitem__(self, k: str) -> float:
        return self.valores.get(k, 0.0)

    def get(self, k: str, padrao: float | None = None) -> float | None:
        return self.valores.get(k, padrao)


def _escala(l: dict) -> float:
    return 1000.0 if (l.get("ESCALA_MOEDA") or "").upper().startswith("MIL") else 1.0


def _profundos(achados: dict[str, float]) -> float:
    """Soma contas achadas pelo nome sem contar pai e filho juntos."""
    return sum(v for c, v in achados.items() if not any(o != c and o.startswith(c + ".") for o in achados))


def _extrair(linhas: list[dict]) -> dict[str, float]:
    """Linhas de UM período (todas as demonstrações) → valores padronizados."""
    v: dict[str, float] = {}
    dep, capex, arrend, divid, minor = {}, {}, {}, {}, {}
    for l in linhas:
        c, nome = l["CD_CONTA"], l["DS_CONTA"]
        valor = float(l["VL_CONTA"] or 0) * _escala(l)
        dem = l["_dem"]
        if dem == "DRE" and c in DRE:
            v[DRE[c]] = valor
        elif dem == "BPA" and c in BPA:
            v[BPA[c]] = valor
        elif dem == "BPP":
            if c in BPP:
                v[BPP[c]] = valor
            if re.search(r"rrendamento", nome) and c.count(".") >= 2 and c.startswith(("2.01", "2.02")):
                arrend[c] = valor
            if re.search(r"n[ãa]o\s+controlador", nome, re.I) and c.startswith("2.03"):
                minor[c] = valor
        elif dem == "DFC":
            if c == "6.01":
                v["fco"] = valor
            elif c == "6.02":
                v["fci"] = valor
            elif c == "6.03":
                v["fcf"] = valor
            elif c.startswith("6.01") and re.search(r"deprecia|amortiza|exaust", nome, re.I) and \
                    not re.search(r"custo|capta|ágio|agio|deságio|desagio", nome, re.I):
                dep[c] = valor
            elif c.startswith("6.02") and re.search(r"imobiliz|intang", nome, re.I) and valor < 0 and \
                    not re.search(r"venda|alienaç|recebimento|baixa", nome, re.I):
                capex[c] = valor
            elif c.startswith("6.03") and re.search(r"dividend|juros\s+s", nome, re.I) and valor < 0:
                divid[c] = valor
    v["depreciacao"] = abs(_profundos(dep))
    v["capex"] = abs(_profundos(capex))
    v["arrendamentos"] = _profundos(arrend)
    v["minoritarios"] = _profundos(minor)
    v["dividendos_pagos"] = abs(_profundos(divid))
    if "lucro_controladores" not in v and "lucro" in v:
        v["lucro_controladores"] = v["lucro"] - 0.0
    v["divida_bruta"] = v.get("divida_cp", 0.0) + v.get("divida_lp", 0.0)
    v["caixa_total"] = v.get("caixa", 0.0) + v.get("aplicacoes", 0.0)
    v["divida_liquida"] = v["divida_bruta"] + v["arrendamentos"] - v["caixa_total"]
    v["ebitda"] = v.get("ebit", 0.0) + v["depreciacao"]
    v["capital_giro"] = v.get("recebiveis", 0.0) + v.get("estoques", 0.0) - v.get("fornecedores", 0.0)
    v["fcff_simples"] = v.get("fco", 0.0) - v["capex"]
    return v


def _carregar_doc(doc: str, ano: int, cnpj: str) -> dict[tuple[str, str, str], list[dict]]:
    """(dt_refer, dt_ini|'', dt_fim, ordem) → linhas da empresa num zip DFP/ITR (consolidado; individual se não houver)."""
    arq = arquivo(doc, ano)
    if not arq:
        return {}
    alvo = formatar_cnpj(cnpj)
    grupos: dict[tuple, list[dict]] = {}
    with zipfile.ZipFile(arq) as z:
        for visao in ("con", "ind"):
            achou = False
            for dem, arqs in (("DRE", ["DRE"]), ("BPA", ["BPA"]), ("BPP", ["BPP"]), ("DFC", ["DFC_MI", "DFC_MD"])):
                for nome in arqs:
                    for l in _linhas(z, f"{doc}_cia_aberta_{nome}_{visao}_{ano}.csv"):
                        if l["CNPJ_CIA"] != alvo:
                            continue
                        achou = True
                        l["_dem"], l["_visao"] = dem, visao
                        chave = (l["DT_REFER"], l.get("DT_INI_EXERC", ""), l["DT_FIM_EXERC"], l["ORDEM_EXERC"], l.get("VERSAO", "1"))
                        grupos.setdefault(chave, []).append(l)
            if achou:
                break
    # só a versão mais recente de cada documento
    ultima: dict[str, str] = {}
    for (ref, _, _, _, ver) in grupos:
        ultima[ref] = max(ultima.get(ref, "0"), ver, key=int)
    return {k: v for k, v in grupos.items() if k[4] == ultima[k[0]]}


def _agrupar_periodo(grupos: dict, dt_ref: str, ordem: str, inicio_ano: bool | None) -> list[dict]:
    """Junta DRE/DFC (com início) e balanço (sem início) de um mesmo fim de período."""
    linhas = []
    for (ref, ini, fim, ord_, _), ls in grupos.items():
        if ref != dt_ref or ord_ != ordem:
            continue
        if not ini:  # balanço
            linhas += ls
            continue
        if inicio_ano is None or (ini[5:10] == "01-01") == inicio_ano:
            linhas += ls
    return linhas


def demonstracoes(cnpj: str, anos: int = 5) -> tuple[list[Periodo], list[Periodo], list[str]]:
    """(anuais em ordem cronológica, trimestrais [ytd, trimestre, ytd_ano_anterior, trimestre_ano_anterior], avisos)."""
    c = digitos(cnpj)
    hoje = date.today()
    anuais: dict[str, Periodo] = {}
    avisos: list[str] = []
    for ano in range(hoje.year - anos, hoje.year + 1):
        grupos = _carregar_doc("dfp", ano, c)
        for (ref, ini, fim, ordem, _) in list(grupos):
            if ordem == "ÚLTIMO" and ref not in anuais:
                linhas = _agrupar_periodo(grupos, ref, "ÚLTIMO", None)
                consol = any(l["_visao"] == "con" for l in linhas)
                anuais[ref] = Periodo(ref[:4], ref, "anual", _extrair(linhas), consol)
    trimestrais: list[Periodo] = []
    for ano in (hoje.year, hoje.year - 1):
        grupos = _carregar_doc("itr", ano, c)
        if not grupos:
            continue
        ref = max(k[0] for k in grupos)
        if anuais and ref <= max(anuais):
            break  # o último balanço anual é mais novo que o último ITR
        rot = f"{(int(ref[5:7]) + 2) // 3}T{ref[2:4]}"
        ref_ant = f"{int(ref[:4]) - 1}{ref[4:]}"
        for ordem, r, nome in (("ÚLTIMO", ref, rot), ("PENÚLTIMO", ref, f"{rot[:2]}{int(rot[2:]) - 1}")):
            ytd = _extrair(_agrupar_periodo(grupos, r, ordem, True))
            tri = _extrair(_agrupar_periodo(grupos, r, ordem, False)) if ref[5:7] != "03" else dict(ytd)
            fim = ref if ordem == "ÚLTIMO" else ref_ant
            trimestrais += [Periodo(f"{nome} acumulado", fim, "ytd", ytd), Periodo(nome, fim, "trimestre", tri)]
        break
    if not anuais:
        raise EmpresaNaoEncontrada(f"sem DFP de {formatar_cnpj(c)} nos últimos {anos} anos")
    lista = [anuais[k] for k in sorted(anuais)]
    if not lista[-1].consolidado:
        avisos.append("Sem demonstrações consolidadas: usei as individuais (controladora).")
    return lista, trimestrais, avisos


FLUXOS = ("receita", "custo", "lucro_bruto", "desp_vendas", "desp_ga", "ebit", "resultado_financeiro", "receitas_financeiras",
          "despesas_financeiras", "lair", "ir", "lucro", "lucro_controladores", "fco", "fci", "fcf", "depreciacao", "capex",
          "dividendos_pagos", "ebitda", "fcff_simples")


def ltm(anuais: list[Periodo], trimestrais: list[Periodo]) -> Periodo:
    """Últimos 12 meses: último ano + acumulado do ano − mesmo acumulado do ano anterior; balanço do último ITR."""
    ult = anuais[-1]
    if len(trimestrais) < 4:
        return Periodo(f"{ult.rotulo} (anual)", ult.fim, "ltm", dict(ult.valores), ult.consolidado)
    ytd, ytd_ant = trimestrais[0], trimestrais[2]
    v = dict(ytd.valores)  # balanço mais recente
    for k in FLUXOS:
        v[k] = ult[k] + ytd[k] - ytd_ant[k]
    return Periodo(f"12 meses até {ytd.fim[8:10]}/{ytd.fim[5:7]}/{ytd.fim[:4]}", ytd.fim, "ltm", v, ult.consolidado)


def acoes(cnpj: str) -> tuple[float, float, str]:
    """(ações totais, em tesouraria, data) da composição do capital mais recente (DFP/ITR)."""
    alvo = formatar_cnpj(cnpj)
    melhor = None
    hoje = date.today()
    for doc, ano in (("itr", hoje.year), ("dfp", hoje.year - 1), ("itr", hoje.year - 1), ("dfp", hoje.year - 2)):
        arq = arquivo(doc, ano)
        if not arq:
            continue
        with zipfile.ZipFile(arq) as z:
            for l in _linhas(z, f"{doc}_cia_aberta_composicao_capital_{ano}.csv"):
                if l["CNPJ_CIA"] == alvo and (melhor is None or l["DT_REFER"] > melhor["DT_REFER"]):
                    melhor = l
        if melhor:
            break
    if not melhor:
        raise EmpresaNaoEncontrada("composição do capital não encontrada na CVM")
    total = float(melhor["QT_ACAO_TOTAL_CAP_INTEGR"] or 0)
    tes = float(melhor["QT_ACAO_TOTAL_TESOURO"] or 0)
    return total, tes, melhor["DT_REFER"]


def setor_pares(e: Empresa, limite: int = 8) -> list[Empresa]:
    """Companhias do mesmo setor (FCA) com ação em bolsa."""
    return [x for x in empresas().values() if x.setor == e.setor and x.cnpj != e.cnpj and x.tickers][:limite * 3]


def financeira(e: Empresa, anuais: list[Periodo]) -> bool:
    """Bancos, seguradoras e afins: o DCF de fluxo de caixa da firma não se aplica."""
    texto = normalizar(e.setor)
    return any(p in texto for p in ("BANCO", "INTERMEDIACAO FINANCEIRA", "SEGURADORA", "PREVIDENCIA E SEGUROS")) or \
        (bool(anuais) and anuais[-1].get("receita", 0.0) == 0.0 and anuais[-1].get("ativo", 0.0) > 0)
