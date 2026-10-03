"""CVM Dados Abertos (companhias e fundos), IBGE (calendário de divulgações) e datasets do Damodaran."""

from __future__ import annotations

import csv
import re
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from quiron.servicos.biblioteca.trechos import chave
from quiron.servicos.mercado.http import numero_br, obter

URL_CIAS = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
URL_INF_DIARIO = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{aaaamm}.zip"
URL_IBGE_CALENDARIO = "https://servicodados.ibge.gov.br/api/v3/calendario/"
URL_DAMODARAN = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/{arquivo}"

DATASETS_DAMODARAN = {
    "premio_pais": ("ctryprem.xlsx", "Prêmio de risco por país (CRP/ERP)"),
    "erp_historico": ("histimpl.xls", "Prêmio de risco implícito dos EUA (histórico)"),
    "betas_eua": ("betas.xls", "Betas por setor — EUA"),
    "betas_emergentes": ("betaemerg.xls", "Betas por setor — emergentes"),
    "multiplos_eua": ("pedata.xls", "P/L por setor — EUA"),
    "ev_ebitda_emergentes": ("vebitdaemerg.xls", "EV/EBITDA por setor — emergentes"),
}


def _csv(texto: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _digitos(t: str) -> str:
    return "".join(c for c in t if c.isdigit())


# ---------------------------------------------------------------- CVM companhias


def buscar_companhia(termo: str, limite: int = 5) -> tuple[list[dict], str]:
    r = obter(URL_CIAS, fonte="CVM Dados Abertos", ttl=24 * 3600, formato="texto", codificacao="latin-1")
    k, dig = chave(termo), _digitos(termo)
    achados = []
    for l in _csv(r.conteudo):
        if l.get("SIT") and l["SIT"].strip().upper() != "ATIVO":
            continue
        nomes = chave(f"{l.get('DENOM_SOCIAL', '')} {l.get('DENOM_COMERC', '')}")
        if (dig and len(dig) >= 8 and dig in _digitos(l.get("CNPJ_CIA", ""))) or (k and k in nomes):
            achados.append(
                {
                    "nome": l.get("DENOM_SOCIAL", "").strip(),
                    "cnpj": l.get("CNPJ_CIA", "").strip(),
                    "codigo_cvm": l.get("CD_CVM", "").strip(),
                    "setor": l.get("SETOR_ATIV", "").strip(),
                    "situacao": l.get("SIT", "").strip(),
                }
            )
            if len(achados) >= limite:
                break
    return achados, f"📊 {r.fonte} — {r.obtido_em:%d/%m/%Y %H:%M}"


# ---------------------------------------------------------------- CVM fundos (informe diário)


@dataclass
class CotaFundo:
    data: date
    cota: float
    patrimonio: float | None
    captacao: float | None
    resgate: float | None
    cotistas: int | None


def informe_diario(cnpj: str, mes: date | None = None) -> tuple[list[CotaFundo], str]:
    """Cotas diárias do fundo no mês (padrão: mês atual, ou o anterior se o atual ainda não saiu)."""
    alvo = _digitos(cnpj)
    meses = [mes] if mes else [date.today().replace(day=1), (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)]
    for m in meses:
        try:
            r = obter(URL_INF_DIARIO.format(aaaamm=m.strftime("%Y%m")), fonte="CVM Dados Abertos (informe diário)", ttl=12 * 3600, formato="bytes")
        except Exception:  # noqa: BLE001 — mês ainda não publicado
            continue
        with zipfile.ZipFile(io.BytesIO(r.conteudo)) as z:
            texto = z.read(z.namelist()[0]).decode("latin-1")
        cotas = []
        for l in _csv(texto):
            cnpj_linha = l.get("CNPJ_FUNDO_CLASSE") or l.get("CNPJ_FUNDO") or ""  # após a CVM 175 a coluna mudou
            if _digitos(cnpj_linha) != alvo:
                continue
            cotas.append(
                CotaFundo(
                    date.fromisoformat(l["DT_COMPTC"]),
                    float(l["VL_QUOTA"]),
                    numero_br(l.get("VL_PATRIM_LIQ")),
                    numero_br(l.get("CAPTC_DIA")),
                    numero_br(l.get("RESG_DIA")),
                    int(l["NR_COTST"]) if l.get("NR_COTST") else None,
                )
            )
        if cotas:
            cotas.sort(key=lambda c: c.data)
            return cotas, f"📊 {r.fonte} — {r.obtido_em:%d/%m/%Y %H:%M}"
    return [], "📊 CVM Dados Abertos"


# ---------------------------------------------------------------- IBGE


@dataclass
class Divulgacao:
    quando: datetime
    titulo: str
    fonte: str


def calendario_ibge(dias: int = 7) -> list[Divulgacao]:
    hoje = date.today()
    params = {"de": hoje.strftime("%m-%d-%Y"), "ate": (hoje + timedelta(days=dias)).strftime("%m-%d-%Y"), "qtd": "100"}
    r = obter(URL_IBGE_CALENDARIO, params=params, fonte="IBGE (calendário)", ttl=12 * 3600)
    itens = r.conteudo.get("items", []) if isinstance(r.conteudo, dict) else r.conteudo
    saida = []
    for i in itens:
        quando = i.get("data_divulgacao") or i.get("data")
        try:
            dt = datetime.strptime(quando.strip(), "%d/%m/%Y %H:%M:%S")
        except (ValueError, AttributeError):
            continue
        titulo = re.sub(r"#\S+", "", i.get("nome_produto") or i.get("titulo") or "Divulgação IBGE").strip()
        if i.get("titulo") and i.get("nome_produto") and i["titulo"] != i["nome_produto"]:
            titulo = f"{i['nome_produto']} — {i['titulo']}"
        saida.append(Divulgacao(dt, titulo, "IBGE"))
    return sorted(saida, key=lambda d: d.quando)


# ---------------------------------------------------------------- Damodaran


def damodaran(dataset: str):
    """Baixa (cache de 30 dias) e abre o dataset como dict {aba: DataFrame}."""
    import pandas as pd

    arquivo, _ = DATASETS_DAMODARAN[dataset]
    r = obter(URL_DAMODARAN.format(arquivo=arquivo), fonte="Damodaran (NYU Stern)", ttl=30 * 86400, formato="bytes")
    abas = pd.read_excel(io.BytesIO(r.conteudo), sheet_name=None, header=None)
    return abas, f"📊 Damodaran Online ({arquivo}) — baixado em {r.obtido_em:%d/%m/%Y}"


def buscar_damodaran(dataset: str, termo: str, limite: int = 10) -> str:
    """Procura um termo (ex.: 'Brazil', 'Banks') em todas as abas e devolve as linhas com o cabeçalho provável."""
    abas, fonte = damodaran(dataset)
    k = chave(termo)
    saida = []
    for nome, df in abas.items():
        df = df.dropna(how="all").dropna(axis=1, how="all")
        cabecalho = None
        for _, linha in df.iterrows():
            valores = [str(v) for v in linha.tolist() if str(v) != "nan"]
            if cabecalho is None and sum(1 for v in valores if not _parece_numero(v)) >= max(3, len(valores) - 1):
                cabecalho = valores
            if any(k in chave(v) for v in valores):
                saida.append(f"**{nome}**: " + " | ".join(_rotular(cabecalho, linha.tolist())))
                if len(saida) >= limite:
                    return "\n".join(saida) + f"\n\n{fonte}"
    return ("\n".join(saida) or f"'{termo}' não encontrado em {dataset}.") + f"\n\n{fonte}"


def _parece_numero(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


def _rotular(cabecalho: list[str] | None, valores: list) -> list[str]:
    vals = [v for v in valores if str(v) != "nan"]
    if not cabecalho or len(cabecalho) != len(vals):
        return [_fmt(v) for v in vals]
    return [f"{c}: {_fmt(v)}" for c, v in zip(cabecalho, vals)]


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.2%}" if abs(v) < 1 else f"{v:,.2f}"
    return str(v)
