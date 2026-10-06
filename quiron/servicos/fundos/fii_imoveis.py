"""Imóveis e carteira dos FIIs pelo informe TRIMESTRAL da CVM (dados abertos).

O informe trimestral traz, por fundo: cada imóvel (nome, endereço, área, unidades, vacância, inadimplência, % das
receitas do FII), os setores dos inquilinos dos imóveis prontos para renda, terrenos e os ativos financeiros (CRI, LCI,
cotas de outros FIIs…). Guardamos só o último trimestre entregue de cada fundo, em `dados/fundos.db`.
Atualização: no máximo 1 download por semana (zip de ~2 MB por ano).
"""

from __future__ import annotations

import re
import time
import zipfile
from collections import defaultdict
from datetime import date

from quiron.servicos.fundos import cvm

URL = f"{cvm.BASE}/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{{ano}}.zip"
TTL = 7 * 86400
UFS = {"AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
       "RS", "RO", "RR", "SC", "SP", "SE", "TO"}
ESQUEMA = """
CREATE TABLE IF NOT EXISTS fii_imovel (cnpj TEXT, data_ref TEXT, classe TEXT, nome TEXT, endereco TEXT, cidade TEXT,
  uf TEXT, area REAL, unidades INTEGER, vacancia REAL, inadimplencia REAL, pct_receitas REAL, pct_locado REAL);
CREATE INDEX IF NOT EXISTS fii_imovel_cnpj ON fii_imovel(cnpj);
CREATE TABLE IF NOT EXISTS fii_inquilino (cnpj TEXT, data_ref TEXT, imovel TEXT, setor TEXT, pct_receitas REAL);
CREATE INDEX IF NOT EXISTS fii_inquilino_cnpj ON fii_inquilino(cnpj);
CREATE TABLE IF NOT EXISTS fii_ativo (cnpj TEXT, data_ref TEXT, tipo TEXT, emissor TEXT, nome TEXT, vencimento TEXT, valor REAL);
CREATE INDEX IF NOT EXISTS fii_ativo_cnpj ON fii_ativo(cnpj);
"""


def local(endereco: str) -> tuple[str, str]:
    """(cidade, UF) a partir do endereço livre: "Av. X, 3000 - Barra, Rio de Janeiro - RJ" → ("Rio de Janeiro", "RJ")."""
    e = re.sub(r"\s+", " ", endereco or "").strip(" .;")
    e = re.sub(r",?\s*(?:CEP:?\s*)?\d{5}-?\d{3}\b.*$", "", e, flags=re.I).strip(" ,.-")
    uf, m = "", None
    for achado in re.finditer(r"(?:^|[\s,/-])([A-Z]{2})(?=\s*(?:[,.;)/-]|$|\s*-?\s*Brasil))", e):
        if achado.group(1) in UFS:  # fica a ÚLTIMA sigla que é UF ("Bloco AB, Barueri/SP" → SP)
            uf, m = achado.group(1), achado
    cidade = ""
    if uf:
        antes = e[: m.start(1)].rstrip(" ,/-")
        pedaco = re.split(r"\s+-\s+|,|/", antes)[-1].strip() if antes else ""
        cidade = pedaco if pedaco and not re.search(r"\d", pedaco) and len(pedaco) <= 40 else ""
    return cidade, uf


def _num(v: str | None) -> float | None:
    try:
        return float((v or "").replace(",", ".")) if (v or "").strip() not in ("", "-") else None
    except ValueError:
        return None


def atualizar(forcar: bool = False) -> None:
    hoje = date.today()
    with cvm.banco() as con:
        con.executescript(ESQUEMA)
        ult = cvm._meta(con, "fii_trimestral")
    if not forcar and ult and ult > time.time() - TTL:
        return
    ultimo: dict[str, tuple[str, int]] = {}  # cnpj → (data_ref, versão) mais recente
    linhas: dict[str, list[dict]] = defaultdict(list)
    for ano in (hoje.year - 1, hoje.year):
        arq = cvm.baixar(URL.format(ano=ano))
        if arq is None:
            continue
        try:
            with zipfile.ZipFile(arq) as z:
                for tipo in ("imovel", "imovel_renda_acabado_inquilino", "ativo"):
                    nome = f"inf_trimestral_fii_{tipo}_{ano}.csv"
                    if nome not in z.namelist():
                        continue
                    with z.open(nome) as f:
                        for l in cvm._linhas_csv(f):
                            c = cvm.digitos(l["CNPJ_Fundo_Classe"])
                            chave = (l["Data_Referencia"], int(l.get("Versao") or 0))
                            if tipo == "imovel" and (c not in ultimo or chave > ultimo[c]):  # último trimestre entregue
                                ultimo[c] = chave
                            linhas[tipo].append({**l, "_c": c, "_k": chave})
        finally:
            arq.unlink(missing_ok=True)
    if not linhas:
        return
    for l in linhas["ativo"]:  # fundo de papel (sem imóvel) ou trimestre mais novo só com ativos
        if l["_c"] not in ultimo or l["_k"] > ultimo[l["_c"]]:
            ultimo[l["_c"]] = l["_k"]
    with cvm.banco() as con:
        con.executescript(ESQUEMA)
        # troca numa transação só: quem ler no meio vê os dados antigos, nunca as tabelas vazias
        con.execute("BEGIN")
        con.execute("DELETE FROM fii_imovel")
        con.execute("DELETE FROM fii_inquilino")
        con.execute("DELETE FROM fii_ativo")
        for l in linhas["imovel"]:
            if ultimo.get(l["_c"]) != l["_k"]:
                continue
            cidade, uf = local(l.get("Endereco", ""))
            con.execute("INSERT INTO fii_imovel VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                l["_c"], l["Data_Referencia"], l.get("Classe", ""), (l.get("Nome_Imovel") or "").strip()[:150],
                (l.get("Endereco") or "").strip()[:200], cidade, uf, _num(l.get("Area")),
                int(_num(l.get("Numero_Unidades")) or 0) or None, _num(l.get("Percentual_Vacancia")),
                _num(l.get("Percentual_Inadimplencia")), _num(l.get("Percentual_Receitas_FII")), _num(l.get("Percentual_Locado"))))
        for l in linhas["imovel_renda_acabado_inquilino"]:
            if ultimo.get(l["_c"]) == l["_k"] and (l.get("Setor_Atuacao") or "-").strip() not in ("", "-"):
                con.execute("INSERT INTO fii_inquilino VALUES (?,?,?,?,?)", (l["_c"], l["Data_Referencia"],
                            (l.get("Nome_Imovel") or "").strip()[:150], l["Setor_Atuacao"].strip()[:80], _num(l.get("Percentual_Receitas_FII"))))
        for l in linhas["ativo"]:
            if ultimo.get(l["_c"]) == l["_k"]:
                con.execute("INSERT INTO fii_ativo VALUES (?,?,?,?,?,?,?)", (l["_c"], l["Data_Referencia"], (l.get("Tipo") or "").strip(),
                            (l.get("Emissor") or "").strip()[:100], (l.get("Nome_Ativo") or "").strip()[:100],
                            l.get("Data_Vencimento") or "", _num(l.get("Valor"))))
        cvm._marcar(con, "fii_trimestral")


def carteira(cnpj: str) -> dict:
    """Imóveis + agregados (por UF/cidade, vacância ponderada pela área, setores dos inquilinos) + ativos financeiros."""
    try:
        atualizar()
    except Exception as e:  # noqa: BLE001 — sem internet/CVM lenta: usa o que já está guardado
        import logging

        logging.info("informe trimestral de FII não atualizado agora (%s)", type(e).__name__)
        with cvm.banco() as con:
            con.executescript(ESQUEMA)
            # não tenta de novo a cada FII da mesma análise: nova tentativa daqui a 1 hora
            con.execute("INSERT OR REPLACE INTO meta VALUES ('fii_trimestral', '', ?)", (time.time() - TTL + 3600,))
    c = cvm.digitos(cnpj)
    with cvm.banco() as con:
        imoveis = [dict(r) for r in con.execute("SELECT * FROM fii_imovel WHERE cnpj = ? ORDER BY COALESCE(pct_receitas, 0) DESC, "
                                                "COALESCE(area, 0) DESC", (c,))]
        inquilinos = [dict(r) for r in con.execute("SELECT * FROM fii_inquilino WHERE cnpj = ?", (c,))]
        ativos = [dict(r) for r in con.execute("SELECT * FROM fii_ativo WHERE cnpj = ? ORDER BY COALESCE(valor, 0) DESC", (c,))]
    por_uf: dict[str, dict] = defaultdict(lambda: {"imoveis": 0, "area": 0.0, "receitas": 0.0})
    for i in imoveis:
        u = por_uf[i["uf"] or "sem UF no endereço"]
        u["imoveis"] += 1
        u["area"] += i["area"] or 0
        u["receitas"] += i["pct_receitas"] or 0
    area_total = sum(i["area"] or 0 for i in imoveis)
    com_vac = [i for i in imoveis if i["vacancia"] is not None and i["area"]]
    vac = (sum(i["vacancia"] * i["area"] for i in com_vac) / sum(i["area"] for i in com_vac)) if com_vac else None
    setores: dict[str, float] = defaultdict(float)
    for q in inquilinos:
        setores[q["setor"]] += q["pct_receitas"] or 0
    por_tipo: dict[str, float] = defaultdict(float)
    for a in ativos:
        por_tipo[a["tipo"] or "outros"] += a["valor"] or 0
    return {"cnpj": c, "data_ref": (imoveis or ativos or [{}])[0].get("data_ref", ""), "imoveis": imoveis,
            "por_uf": dict(sorted(por_uf.items(), key=lambda x: -x[1]["area"])), "area_total": area_total,
            "vacancia_ponderada": vac, "setores_inquilinos": dict(sorted(setores.items(), key=lambda x: -x[1])),
            "ativos": ativos, "ativos_por_tipo": dict(sorted(por_tipo.items(), key=lambda x: -x[1]))}


def _pct(v: float | None) -> float | None:
    return None if v is None else round(v * 100, 1)


def secoes(ticker: str, cart: dict):
    """Seção "Imóveis e carteira" de um FII para os relatórios."""
    from quiron.servicos.analise.relatorio import Grafico, Secao, Tabela

    tabelas, graficos = [], []
    imo = cart["imoveis"]
    if imo:
        tabelas.append(Tabela(f"{ticker}: imóveis ({len(imo)}; os 20 de maior peso na receita)",
                              ["Imóvel", "Cidade/UF", "Área (m²)", "Vacância", "Inadimplência", "% das receitas", "Tipo"],
                              [[i["nome"], "/".join(x for x in (i["cidade"], i["uf"]) if x) or (i["endereco"][:50] or "—"),
                                round(i["area"]) if i["area"] else None, _pct(i["vacancia"]), _pct(i["inadimplencia"]),
                                _pct(i["pct_receitas"]), (i["classe"] or "").replace("Imóveis para ", "")] for i in imo[:20]],
                              ["texto", "texto", "int", "pct", "pct", "pct", "texto"],
                              f"Informe trimestral da CVM de {cart['data_ref']}. Cidade/UF lidas do endereço declarado (sem UF: trecho do endereço)."))
        ufs = list(cart["por_uf"].items())
        tabelas.append(Tabela(f"{ticker}: onde estão os imóveis", ["UF", "Imóveis", "Área (m²)", "% da área", "% das receitas"],
                              [[u, d["imoveis"], round(d["area"]), round(d["area"] / cart["area_total"] * 100, 1) if cart["area_total"] else None,
                                _pct(d["receitas"])] for u, d in ufs], ["texto", "int", "int", "pct", "pct"]))
        if len(ufs) > 1 and cart["area_total"]:
            graficos.append(Grafico(f"{ticker}: área por estado (%)", "barras_h", [u for u, _ in ufs[:10]],
                                    {"% da área": [round(d["area"] / cart["area_total"] * 100, 1) for _, d in ufs[:10]]}, "pct"))
    if cart["setores_inquilinos"]:
        tabelas.append(Tabela(f"{ticker}: setores dos inquilinos", ["Setor", "% das receitas do FII"],
                              [[s, _pct(v)] for s, v in list(cart["setores_inquilinos"].items())[:12]], ["texto", "pct"]))
    if cart["ativos"]:
        total = sum(a["valor"] or 0 for a in cart["ativos"])
        tabelas.append(Tabela(f"{ticker}: ativos financeiros por tipo", ["Tipo", "Valor (R$)", "% dos ativos financeiros"],
                              [[t, round(v), round(v / total * 100, 1) if total else None] for t, v in cart["ativos_por_tipo"].items()],
                              ["texto", "reais", "pct"]))
        tabelas.append(Tabela(f"{ticker}: 15 maiores ativos financeiros", ["Ativo", "Emissor", "Tipo", "Vencimento", "Valor (R$)"],
                              [[a["nome"] or "—", a["emissor"] or "—", a["tipo"], a["vencimento"] or "—", round(a["valor"] or 0)]
                               for a in cart["ativos"][:15]], ["texto", "texto", "texto", "texto", "reais"]))
    if not tabelas:
        return None
    texto = []
    if imo:
        texto.append(f"{len(imo)} imóveis, {round(cart['area_total']):,} m² no total".replace(",", ".")
                     + (f", vacância média ponderada pela área de {str(_pct(cart['vacancia_ponderada'])).replace('.', ',')}%"
                        if cart["vacancia_ponderada"] is not None else "") + ".")
        principais = [f"{i['nome']} ({'/'.join(x for x in (i['cidade'], i['uf']) if x) or 'local não informado'})" for i in imo[:3]]
        texto.append("Principais: " + "; ".join(principais) + ".")
    if cart["ativos"] and not imo:
        texto.append("Fundo de papel/fundos: a carteira é de ativos financeiros (veja os tipos e os maiores abaixo).")
    return Secao(f"Imóveis e carteira — {ticker}", " ".join(texto), tabelas, graficos)


def fatos(cart: dict) -> dict:
    return {"data_ref": cart["data_ref"], "n_imoveis": len(cart["imoveis"]), "area_total_m2": round(cart["area_total"]),
            "vacancia_ponderada_pct": _pct(cart["vacancia_ponderada"]),
            "ufs": {u: d["imoveis"] for u, d in cart["por_uf"].items()},
            "maiores_imoveis": [(i["nome"], i["cidade"], i["uf"], _pct(i["pct_receitas"])) for i in cart["imoveis"][:5]],
            "setores_inquilinos_pct": {s: _pct(v) for s, v in list(cart["setores_inquilinos"].items())[:5]},
            "ativos_financeiros_por_tipo": {t: round(v) for t, v in list(cart["ativos_por_tipo"].items())[:6]}}


def texto(ticker: str, cart: dict) -> str:
    if not cart["imoveis"] and not cart["ativos"]:
        return f"{ticker}: sem imóveis nem ativos no último informe trimestral da CVM."
    linhas = [f"🏢 **{ticker} — imóveis e carteira** (informe trimestral de {cart['data_ref']})"]
    if cart["imoveis"]:
        vac = cart["vacancia_ponderada"]
        linhas.append(f"{len(cart['imoveis'])} imóveis · {round(cart['area_total']):,} m²".replace(",", ".")
                      + (f" · vacância ponderada {str(_pct(vac)).replace('.', ',')}%" if vac is not None else ""))
        linhas.append("Por estado: " + " · ".join(f"{u} {d['imoveis']}" for u, d in list(cart["por_uf"].items())[:8]))
        for i in cart["imoveis"][:10]:
            onde = "/".join(x for x in (i["cidade"], i["uf"]) if x) or i["endereco"][:60]
            extra = [f"{round(i['area']):,} m²".replace(",", ".") if i["area"] else "",
                     f"vacância {str(_pct(i['vacancia'])).replace('.', ',')}%" if i["vacancia"] is not None else "",
                     f"{str(_pct(i['pct_receitas'])).replace('.', ',')}% da receita" if i["pct_receitas"] else ""]
            linhas.append(f"• {i['nome']} — {onde} · " + " · ".join(x for x in extra if x))
    if cart["setores_inquilinos"]:
        linhas.append("Inquilinos por setor: " + " · ".join(f"{s} {str(_pct(v)).replace('.', ',')}%"
                                                            for s, v in list(cart["setores_inquilinos"].items())[:6]))
    if cart["ativos"]:
        linhas.append("Ativos financeiros: " + " · ".join(f"{t} R$ {v / 1e6:,.1f} mi".replace(",", "X").replace(".", ",").replace("X", ".")
                                                          for t, v in list(cart["ativos_por_tipo"].items())[:5]))
    linhas.append(f"📊 CVM Dados Abertos — informe trimestral de FII ({cart['data_ref']})")
    return "\n".join(linhas)
