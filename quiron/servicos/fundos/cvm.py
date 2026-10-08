"""Base de fundos a partir da CVM Dados Abertos (oficial, gratuita) — guardada em `dados/fundos.db`.

- Cadastro (Resolução CVM 175): `registro_fundo_classe.zip` → classes, fundos (gestor/administrador) e subclasses.
- Extrato anual: taxas de administração/performance, aplicação mínima, prazos de cotização e pagamento.
- Informe diário: cada mês é baixado UMA vez e resumido num índice mensal de TODOS os fundos (cota e PL do último dia,
  cotistas, captação e resgates do mês) — base da rentabilidade, do risco e da comparação com os pares. O arquivo bruto
  (~12 MB/mês) é descartado depois de resumido. Meses recentes (o atual e o anterior) são atualizados a cada 12 h.
- FII: informe mensal (valor patrimonial da cota, dividend yield, rentabilidade, segmento, cotistas).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from quiron.nucleo.config import pasta_dados
from quiron.servicos.mercado import http

BASE = "https://dados.cvm.gov.br/dados"
URL_CADASTRO = f"{BASE}/FI/CAD/DADOS/registro_fundo_classe.zip"
URL_EXTRATO = f"{BASE}/FI/DOC/EXTRATO/DADOS/extrato_fi_{{ano}}.csv"
URL_DIARIO = f"{BASE}/FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_{{aaaamm}}.zip"
URL_FII = f"{BASE}/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{{ano}}.zip"
FONTE = "CVM Dados Abertos"
PRIMEIRO_MES = date(2021, 1, 1)  # antes disso a CVM só publica arquivos anuais (HIST)
TTL_CADASTRO = 7 * 86400
TTL_RECENTE = 12 * 3600

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT, atualizado REAL);
CREATE TABLE IF NOT EXISTS classes (
  cnpj TEXT, id_classe TEXT, id_fundo TEXT, nome TEXT, busca TEXT, tipo TEXT, situacao TEXT, classificacao TEXT,
  anbima TEXT, tributacao_lp TEXT, classe_cotas TEXT, publico TEXT, exclusivo TEXT, condominio TEXT, inicio TEXT,
  pl REAL, data_pl TEXT);
CREATE INDEX IF NOT EXISTS classes_cnpj ON classes(cnpj);
CREATE INDEX IF NOT EXISTS classes_anbima ON classes(anbima);
CREATE TABLE IF NOT EXISTS fundos (id_fundo TEXT PRIMARY KEY, cnpj TEXT, nome TEXT, tipo TEXT, gestor TEXT,
  cnpj_gestor TEXT, administrador TEXT, busca_gestor TEXT);
CREATE INDEX IF NOT EXISTS fundos_gestor ON fundos(cnpj_gestor);
CREATE TABLE IF NOT EXISTS subclasses (id_classe TEXT, id_sub TEXT PRIMARY KEY, nome TEXT, situacao TEXT, publico TEXT,
  previdenciario TEXT);
CREATE TABLE IF NOT EXISTS extrato (cnpj TEXT PRIMARY KEY, data TEXT, anbima TEXT, publico TEXT, aplic_min REAL,
  dias_conversao INTEGER, dias_pagamento INTEGER, taxa_adm REAL, taxa_perf REAL, indice_perf TEXT, taxa_saida TEXT);
CREATE TABLE IF NOT EXISTS mensal (cnpj TEXT, sub TEXT, mes TEXT, data TEXT, cota REAL, pl REAL, cotistas INTEGER,
  captacao REAL, resgate REAL, PRIMARY KEY (cnpj, sub, mes));
CREATE INDEX IF NOT EXISTS mensal_mes ON mensal(mes);
CREATE TABLE IF NOT EXISTS fii (cnpj TEXT, mes TEXT, nome TEXT, isin TEXT, ticker TEXT, segmento TEXT, mandato TEXT,
  gestao TEXT, publico TEXT, cotistas INTEGER, pl REAL, cotas REAL, vp_cota REAL, dy_mes REAL, rent_efetiva REAL,
  rent_patrimonial REAL, taxa_adm REAL, PRIMARY KEY (cnpj, mes));
"""


class FundoNaoEncontrado(LookupError):
    pass


def digitos(t: str) -> str:
    return re.sub(r"\D", "", t or "")


def formatar_cnpj(t: str) -> str:
    d = digitos(t).zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", (t or "").upper()).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return http.numero_br(v)


# ---------------------------------------------------------------- banco e downloads
def caminho_banco() -> Path:
    return pasta_dados() / "fundos.db"


@contextmanager
def banco() -> Iterator[sqlite3.Connection]:
    caminho = caminho_banco()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, timeout=60)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(ESQUEMA)
        yield con
        con.commit()
    finally:
        con.close()


def _meta(con: sqlite3.Connection, chave: str) -> float | None:
    r = con.execute("SELECT atualizado FROM meta WHERE chave = ?", (chave,)).fetchone()
    return r[0] if r else None


def _marcar(con: sqlite3.Connection, chave: str, valor: str = "") -> None:
    con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?, ?)", (chave, valor, time.time()))


def baixar(url: str) -> Path | None:
    """Baixa para um arquivo temporário (em partes: nada de 50 MB na memória). None se a CVM ainda não publicou."""
    fd, nome = tempfile.mkstemp(suffix=Path(url).suffix)
    os.close(fd)  # no Windows um arquivo aberto não pode ser reaberto nem apagado (WinError 32)
    arq = Path(nome)
    try:
        with http.cliente().stream("GET", url, timeout=300) as r:
            if r.status_code == 404:
                arq.unlink(missing_ok=True)
                return None
            r.raise_for_status()
            with arq.open("wb") as f:
                for parte in r.iter_bytes(1 << 20):
                    f.write(parte)
        return arq
    except Exception:
        arq.unlink(missing_ok=True)
        raise


def _linhas_csv(f, sep: str = ";") -> Iterator[dict]:
    yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=sep)


# ---------------------------------------------------------------- cadastro
def atualizar_cadastro(forcar: bool = False) -> None:
    with banco() as con:
        if not forcar and (_meta(con, "cadastro") or 0) > time.time() - TTL_CADASTRO:
            return
    arq = baixar(URL_CADASTRO)
    if arq is None:
        raise http.FonteIndisponivel("cadastro de fundos da CVM indisponível")
    try:
        with zipfile.ZipFile(arq) as z, banco() as con:
            nomes = {Path(n).stem: n for n in z.namelist()}
            con.execute("DELETE FROM classes")
            con.execute("DELETE FROM fundos")
            con.execute("DELETE FROM subclasses")
            with z.open(nomes["registro_fundo"]) as f:
                con.executemany("INSERT OR REPLACE INTO fundos VALUES (?,?,?,?,?,?,?,?)", (
                    (l["ID_Registro_Fundo"], digitos(l["CNPJ_Fundo"]), l["Denominacao_Social"], l["Tipo_Fundo"], l["Gestor"],
                     digitos(l["CPF_CNPJ_Gestor"]), l["Administrador"], normalizar(l["Gestor"])) for l in _linhas_csv(f)))
            with z.open(nomes["registro_classe"]) as f:
                con.executemany("INSERT INTO classes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    (digitos(l["CNPJ_Classe"]), l["ID_Registro_Classe"], l["ID_Registro_Fundo"], l["Denominacao_Social"],
                     normalizar(l["Denominacao_Social"]), l["Tipo_Classe"], l["Situacao"], l["Classificacao"],
                     l["Classificacao_Anbima"], l["Tributacao_Longo_Prazo"], l["Classe_Cotas"], l["Publico_Alvo"],
                     l["Exclusivo"], l["Forma_Condominio"], l["Data_Inicio"], _f(l["Patrimonio_Liquido"]),
                     l["Data_Patrimonio_Liquido"]) for l in _linhas_csv(f)))
            if "registro_subclasse" in nomes:
                with z.open(nomes["registro_subclasse"]) as f:
                    con.executemany("INSERT OR REPLACE INTO subclasses VALUES (?,?,?,?,?,?)", (
                        (l["ID_Registro_Classe"], l["ID_Subclasse"], l["Denominacao_Social"], l["Situacao"],
                         l["Publico_Alvo"], l["Previdenciario"]) for l in _linhas_csv(f)))
            _marcar(con, "cadastro")
    finally:
        arq.unlink(missing_ok=True)


def atualizar_extrato(forcar: bool = False) -> None:
    """Extratos do ano atual e do anterior (o mais recente de cada classe prevalece)."""
    with banco() as con:
        if not forcar and (_meta(con, "extrato") or 0) > time.time() - TTL_CADASTRO:
            return
    ano = date.today().year
    linhas: dict[str, dict] = {}
    for a in (ano - 1, ano):
        arq = baixar(URL_EXTRATO.format(ano=a))
        if arq is None:
            continue
        try:
            with arq.open("rb") as f:
                for l in _linhas_csv(f):
                    c = digitos(l.get("CNPJ_FUNDO_CLASSE") or l.get("CNPJ_FUNDO") or "")
                    if c and (c not in linhas or l["DT_COMPTC"] >= linhas[c]["DT_COMPTC"]):
                        linhas[c] = l
        finally:
            arq.unlink(missing_ok=True)

    def inteiro(v: str | None) -> int | None:
        try:
            return int(float(v)) if v else None
        except ValueError:
            return None

    with banco() as con:
        con.execute("DELETE FROM extrato")
        con.executemany("INSERT OR REPLACE INTO extrato VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            (c, l["DT_COMPTC"], l.get("CLASSE_ANBIMA", ""), l.get("PUBLICO_ALVO", ""), _f(l.get("APLIC_MIN")),
             inteiro(l.get("QT_DIA_CONVERSAO_COTA")), inteiro(l.get("QT_DIA_PAGTO_RESGATE")), _f(l.get("TAXA_ADM")),
             _f(l.get("TAXA_PERFM")), (l.get("PARAM_TAXA_PERFM") or "").strip(), l.get("EXISTE_TAXA_SAIDA", ""))
            for c, l in linhas.items()))
        _marcar(con, "extrato")


# ---------------------------------------------------------------- índice mensal (informe diário)
def meses(inicio: date, fim: date) -> list[date]:
    saida, m = [], date(inicio.year, inicio.month, 1)
    while m <= fim:
        saida.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return saida


def _final(mes: date, hoje: date) -> bool:
    """Mês com dados definitivos: anterior ao mês passado (a CVM ainda corrige o mês corrente e o anterior)."""
    return (hoje.year * 12 + hoje.month) - (mes.year * 12 + mes.month) >= 2


def indexar_mes(mes: date) -> int:
    """Resume o informe diário de um mês no índice. Devolve quantas classes/subclasses entraram (0 = não publicado)."""
    arq = baixar(URL_DIARIO.format(aaaamm=mes.strftime("%Y%m")))
    if arq is None:
        return 0
    agregado: dict[tuple[str, str], list] = {}
    try:
        with zipfile.ZipFile(arq) as z:
            for nome in z.namelist():
                with z.open(nome) as f:
                    for l in _linhas_csv(f):
                        chave = (digitos(l.get("CNPJ_FUNDO_CLASSE") or l.get("CNPJ_FUNDO") or ""), l.get("ID_SUBCLASSE") or "")
                        d = l["DT_COMPTC"]
                        cap, res = _f(l.get("CAPTC_DIA")) or 0.0, _f(l.get("RESG_DIA")) or 0.0
                        a = agregado.get(chave)
                        if a is None:
                            agregado[chave] = [d, l["VL_QUOTA"], l["VL_PATRIM_LIQ"], l["NR_COTST"], cap, res]
                        else:
                            if d >= a[0]:
                                a[0:4] = [d, l["VL_QUOTA"], l["VL_PATRIM_LIQ"], l["NR_COTST"]]
                            a[4] += cap
                            a[5] += res
    finally:
        arq.unlink(missing_ok=True)
    m = mes.strftime("%Y-%m")
    with banco() as con:
        con.execute("DELETE FROM mensal WHERE mes = ?", (m,))
        con.executemany("INSERT OR REPLACE INTO mensal VALUES (?,?,?,?,?,?,?,?,?)", (
            (c, s, m, a[0], _f(a[1]), _f(a[2]), int(float(a[3])) if a[3] else None, a[4], a[5])
            for (c, s), a in agregado.items() if _f(a[1])))
        _marcar(con, f"mes:{m}", "final" if _final(mes, date.today()) else "parcial")
    return len(agregado)


def garantir_meses(n_meses: int, hoje: date | None = None, aviso=None) -> list[str]:
    """Garante no índice os últimos `n_meses` (+ o mês corrente). Devolve os meses que precisaram ser baixados."""
    hoje = hoje or date.today()
    inicio = max(PRIMEIRO_MES, date(hoje.year, hoje.month, 1).replace(day=1))
    for _ in range(n_meses):
        inicio = date(inicio.year - (inicio.month == 1), (inicio.month - 2) % 12 + 1, 1)
    inicio = max(inicio, PRIMEIRO_MES)
    baixados = []
    for mes in meses(inicio, hoje):
        chave = f"mes:{mes:%Y-%m}"
        with banco() as con:
            r = con.execute("SELECT valor, atualizado FROM meta WHERE chave = ?", (chave,)).fetchone()
        if r and (r["valor"] == "final" or r["atualizado"] > time.time() - TTL_RECENTE):
            continue
        if aviso:
            aviso(f"baixando o informe diário de {mes:%m/%Y} da CVM…")
        try:
            if indexar_mes(mes):
                baixados.append(f"{mes:%Y-%m}")
        except Exception as e:  # noqa: BLE001 — um mês com problema não derruba a análise
            logging.warning("informe diário %s indisponível: %s", mes, e)
    return baixados


# ---------------------------------------------------------------- FII (informe mensal)
def atualizar_fii(anos: int = 2, forcar: bool = False) -> None:
    hoje = date.today()
    for ano in range(hoje.year - anos + 1, hoje.year + 1):
        chave = f"fii:{ano}"
        with banco() as con:
            ult = _meta(con, chave)
        if not forcar and ult and (ano < hoje.year or ult > time.time() - TTL_CADASTRO):
            continue
        arq = baixar(URL_FII.format(ano=ano))
        if arq is None:
            continue
        geral, comp = {}, {}
        try:
            with zipfile.ZipFile(arq) as z:
                for nome in z.namelist():
                    alvo = geral if "geral" in nome else comp if "complemento" in nome else None
                    if alvo is None:
                        continue
                    with z.open(nome) as f:
                        for l in _linhas_csv(f):
                            k = (digitos(l["CNPJ_Fundo_Classe"]), l["Data_Referencia"][:7])
                            if k not in alvo or int(l.get("Versao") or 0) >= int(alvo[k].get("Versao") or 0):
                                alvo[k] = l
        finally:
            arq.unlink(missing_ok=True)
        with banco() as con:
            for (c, m), g in geral.items():
                x = comp.get((c, m), {})
                isin = g.get("Codigo_ISIN", "")
                ticker = (isin[2:6] + "11") if re.fullmatch(r"BR[A-Z0-9]{4}CTF\d{3}", isin or "") else ""
                pct = lambda k: (_f(x.get(k)) or 0.0) * 100 if x.get(k) not in (None, "") else None  # noqa: E731
                con.execute("INSERT OR REPLACE INTO fii VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    c, m, g.get("Nome_Fundo_Classe", ""), isin, ticker, g.get("Segmento_Atuacao", ""), g.get("Mandato", ""),
                    g.get("Tipo_Gestao", ""), g.get("Publico_Alvo", ""), int(float(x["Total_Numero_Cotistas"]))
                    if x.get("Total_Numero_Cotistas") else None, _f(x.get("Patrimonio_Liquido")), _f(x.get("Cotas_Emitidas")),
                    _f(x.get("Valor_Patrimonial_Cotas")), pct("Percentual_Dividend_Yield_Mes"),
                    pct("Percentual_Rentabilidade_Efetiva_Mes"), pct("Percentual_Rentabilidade_Patrimonial_Mes"),
                    pct("Percentual_Despesas_Taxa_Administracao")))
            _marcar(con, chave)


# ---------------------------------------------------------------- consultas
@dataclass
class Classe:
    cnpj: str
    nome: str
    tipo: str
    situacao: str
    classificacao: str
    anbima: str
    tributacao_lp: str
    classe_cotas: str
    publico: str
    exclusivo: str
    condominio: str
    inicio: str
    pl: float | None
    data_pl: str
    gestor: str
    cnpj_gestor: str
    administrador: str
    id_classe: str = ""

    @property
    def cnpj_formatado(self) -> str:
        return formatar_cnpj(self.cnpj)


def _classe(r: sqlite3.Row) -> Classe:
    return Classe(r["cnpj"], r["nome"], r["tipo"], r["situacao"], r["classificacao"] or "", r["anbima"] or "",
                  r["tributacao_lp"] or "", r["classe_cotas"] or "", r["publico"] or "", r["exclusivo"] or "",
                  r["condominio"] or "", r["inicio"] or "", r["pl"], r["data_pl"] or "", r["gestor"] or "",
                  r["cnpj_gestor"] or "", r["administrador"] or "", r["id_classe"] or "")


SELECT_CLASSE = ("SELECT c.*, f.gestor, f.cnpj_gestor, f.administrador FROM classes c "
                 "LEFT JOIN fundos f ON f.id_fundo = c.id_fundo")


def buscar(termo: str, limite: int = 10, so_ativos: bool = True, tipo: str = "") -> list[Classe]:
    """Por CNPJ (só dígitos bastam) ou por palavras do nome (todas precisam aparecer). Maiores PL primeiro."""
    atualizar_cadastro()
    d = digitos(termo)
    with banco() as con:
        if len(d) >= 8 and len(d) == len(re.sub(r"[\s./-]", "", termo)):
            linhas = con.execute(f"{SELECT_CLASSE} WHERE c.cnpj LIKE ? ORDER BY c.pl DESC LIMIT ?", (f"{d}%", limite)).fetchall()
        else:
            palavras = normalizar(termo).split()
            if not palavras:
                return []
            filtro = " AND ".join("c.busca LIKE ?" for _ in palavras)
            extra = " AND c.situacao LIKE 'Em Funcionamento%'" if so_ativos else ""
            if tipo:
                extra += " AND c.tipo LIKE ?"
            args = [f"%{p}%" for p in palavras] + ([f"%{tipo}%"] if tipo else []) + [limite]
            linhas = con.execute(f"{SELECT_CLASSE} WHERE {filtro}{extra} ORDER BY c.pl DESC LIMIT ?", args).fetchall()
    return [_classe(r) for r in linhas]


def classe(cnpj: str) -> Classe:
    atualizar_cadastro()
    with banco() as con:
        r = con.execute(f"{SELECT_CLASSE} WHERE c.cnpj = ? ORDER BY c.situacao LIKE 'Em Funcionamento%' DESC LIMIT 1",
                        (digitos(cnpj),)).fetchone()
    if not r:
        raise FundoNaoEncontrado(f"CNPJ {formatar_cnpj(cnpj)} não está no cadastro da CVM")
    return _classe(r)


def extrato(cnpj: str) -> dict | None:
    atualizar_extrato()
    with banco() as con:
        r = con.execute("SELECT * FROM extrato WHERE cnpj = ?", (digitos(cnpj),)).fetchone()
    return dict(r) if r else None


def subclasses_no_indice(cnpj: str) -> list[tuple[str, str, float | None]]:
    """(id da subclasse, nome, PL mais recente) — '' é a própria classe."""
    with banco() as con:
        linhas = con.execute("SELECT m.sub, s.nome, m.pl FROM mensal m LEFT JOIN subclasses s ON s.id_sub = m.sub "
                             "WHERE m.cnpj = ? AND m.mes = (SELECT MAX(mes) FROM mensal WHERE cnpj = ?) ORDER BY m.pl DESC",
                             (digitos(cnpj), digitos(cnpj))).fetchall()
    return [(r["sub"], r["nome"] or ("classe" if not r["sub"] else r["sub"]), r["pl"]) for r in linhas]


def serie_mensal(cnpj: str, sub: str | None = None) -> tuple[list[dict], str]:
    """Linhas mensais (mes, data, cota, pl, cotistas, captacao, resgate) e a subclasse usada."""
    c = digitos(cnpj)
    if sub is None:
        opcoes = subclasses_no_indice(c)
        if not opcoes:
            raise FundoNaoEncontrado(f"{formatar_cnpj(c)} sem cotas no informe diário da CVM no período")
        sub = "" if any(o[0] == "" for o in opcoes) else opcoes[0][0]
    with banco() as con:
        linhas = [dict(r) for r in con.execute("SELECT mes, data, cota, pl, cotistas, captacao, resgate FROM mensal "
                                               "WHERE cnpj = ? AND sub = ? ORDER BY mes", (c, sub))]
    return linhas, sub


def retornos_mes(mes_ini: str, mes_fim: str) -> dict[tuple[str, str], tuple[float, float | None]]:
    """Retorno acumulado (cota fim ÷ cota no fim do mês anterior ao início) de todas as classes, com o PL final."""
    with banco() as con:
        base = con.execute("SELECT MAX(mes) FROM mensal WHERE mes < ?", (mes_ini,)).fetchone()[0]
        if not base:
            return {}
        a = {(r["cnpj"], r["sub"]): r["cota"] for r in con.execute("SELECT cnpj, sub, cota FROM mensal WHERE mes = ?", (base,))}
        b = con.execute("SELECT cnpj, sub, cota, pl FROM mensal WHERE mes = ?", (mes_fim,)).fetchall()
    return {(r["cnpj"], r["sub"]): (r["cota"] / a[(r["cnpj"], r["sub"])] - 1, r["pl"]) for r in b
            if a.get((r["cnpj"], r["sub"])) and r["cota"]}



def pares(anbima: str, excluir: str = "") -> list[tuple[str, str]]:
    """Classes da mesma classificação ANBIMA, abertas, em funcionamento (pares para comparar)."""
    with banco() as con:
        return [(r["cnpj"], "") for r in con.execute(
            "SELECT cnpj FROM classes WHERE anbima = ? AND situacao LIKE 'Em Funcionamento%' AND cnpj != ? "
            "AND (exclusivo IS NULL OR exclusivo != 'S')", (anbima, digitos(excluir)))]


def fundos_da_gestora(termo: str, limite: int = 400) -> tuple[list[Classe], list[str]]:
    """Classes em funcionamento dos fundos geridos por quem bate com o termo (nome ou CNPJ do gestor)."""
    atualizar_cadastro()
    d = digitos(termo)
    with banco() as con:
        if len(d) >= 8:
            gest = con.execute("SELECT DISTINCT gestor FROM fundos WHERE cnpj_gestor = ?", (d,)).fetchall()
            filtro, args = "f.cnpj_gestor = ?", [d]
        else:
            palavras = normalizar(termo).split()
            filtro = " AND ".join("f.busca_gestor LIKE ?" for _ in palavras)
            args = [f"%{p}%" for p in palavras]
            gest = con.execute(f"SELECT DISTINCT gestor FROM fundos f WHERE {filtro}", args).fetchall()
        linhas = con.execute(f"{SELECT_CLASSE} WHERE {filtro} AND c.situacao LIKE 'Em Funcionamento%' ORDER BY c.pl DESC "
                             "LIMIT ?", args + [limite]).fetchall()
    return [_classe(r) for r in linhas], [g[0] for g in gest if g[0]]


def fii(termo: str) -> list[dict]:
    """Histórico mensal de um FII pelo ticker (HGLG11), CNPJ ou nome."""
    atualizar_fii()
    t = termo.strip().upper()
    with banco() as con:
        if re.fullmatch(r"[A-Z]{4}11", t):
            # o mesmo ISIN às vezes aparece em mais de um fundo (erro de cadastro): fica o de mais cotistas (o listado)
            cnpj = con.execute("SELECT cnpj FROM fii f WHERE ticker = ? AND mes = (SELECT MAX(mes) FROM fii WHERE cnpj = f.cnpj) "
                               "ORDER BY COALESCE(cotistas, 0) DESC, mes DESC LIMIT 1", (t,)).fetchone()
        elif len(digitos(t)) >= 8:
            cnpj = con.execute("SELECT cnpj FROM fii WHERE cnpj LIKE ? ORDER BY mes DESC LIMIT 1", (digitos(t) + "%",)).fetchone()
        else:
            palavras = normalizar(t).split()
            cnpj = con.execute("SELECT cnpj FROM fii WHERE " + " AND ".join("UPPER(nome) LIKE ?" for _ in palavras)
                               + " ORDER BY pl DESC LIMIT 1", [f"%{p}%" for p in palavras]).fetchone()
        if not cnpj:
            raise FundoNaoEncontrado(f"FII “{termo}” não encontrado no informe mensal da CVM")
        return [dict(r) for r in con.execute("SELECT * FROM fii WHERE cnpj = ? ORDER BY mes", (cnpj[0],))]


def fonte(data: str = "") -> str:
    return f"📊 {FONTE} — " + (f"dados até {data}" if data else date.today().strftime("%d/%m/%Y"))
