"""Insumos do conteúdo: os FATOS que o modelo pode usar, numerados e com crédito — números do Banco Central (calculados
e datados aqui), manchetes do RSS, normas do radar regulatório, agenda (Copom) e trechos da biblioteca.

O modelo só pode citar o que está aqui (marcando [n]); créditos e conferência de números vêm desta lista."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass
class Insumo:
    id: int
    tipo: str  # numero | noticia | norma | agenda | livro | ideia
    texto: str
    credito: str
    link: str = ""
    aviso: str = ""  # nota interna para o Rickson (não vai para o texto público)


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn")


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def numeros() -> list[tuple[str, str]]:
    """(texto, crédito) dos indicadores principais — último dado do Banco Central (ou do cache, se fora do ar)."""
    from quiron.servicos.mercado import bcb

    saida = []
    for chave, rotulo in (("selic_meta", "Selic meta"), ("cdi", "CDI"), ("ipca_12m", "IPCA em 12 meses"), ("dolar_ptax", "Dólar PTAX")):
        try:
            s = bcb.sgs(chave, 1)
            p = s.ultimo
            valor = f"R$ {_br(p.valor, 4)}" if s.unidade == "R$" else f"{_br(p.valor)}{'% a.a.' if 'a.a.' in s.unidade else '%'}"
            saida.append((f"{rotulo}: {valor} (ref. {p.data:%d/%m/%Y})", f"Banco Central (SGS {bcb.SERIES[chave][0]}), {p.data:%d/%m/%Y}"
                          + (" — dado desatualizado" if s.desatualizado else "")))
        except Exception as e:  # noqa: BLE001 — fonte fora do ar: segue sem
            logging.info("sem %s (%s)", chave, type(e).__name__)
    ano = date.today().year
    for ind, rotulo in (("ipca", "IPCA"), ("selic", "Selic")):
        try:
            f = bcb.focus(ind, ano)
            saida.append((f"Focus — mediana do {rotulo} para {ano}: {_br(f.mediana)}% (rel. {f.data:%d/%m/%Y})",
                          f"Banco Central, Boletim Focus de {f.data:%d/%m/%Y}"))
        except Exception as e:  # noqa: BLE001
            logging.info("sem Focus %s (%s)", ind, type(e).__name__)
    return saida


def noticias(tema: str = "", horas: int = 48, limite: int = 8) -> list[tuple[str, str, str]]:
    from quiron.servicos.noticias import coleta, consultas

    try:
        consultas._garantir_coleta()
        itens = coleta.listar(horas)
    except Exception as e:  # noqa: BLE001
        logging.info("sem notícias (%s)", type(e).__name__)
        return []
    if tema:
        palavras = [p for p in re.findall(r"\w{4,}", _norm(tema))]
        itens = [n for n in itens if any(p in _norm(f"{n.titulo} {n.resumo}") for p in palavras)] or []
    else:  # sem tema: as mais relevantes (alertas e mais fontes primeiro)
        itens = sorted(itens, key=lambda n: (-len(n.alertas), -len(n.outras_fontes), n.publicado_em), reverse=False)
    return [(f"Manchete: {n.titulo}" + (f" — {n.resumo[:160]}" if n.resumo else ""),
             f"{n.fonte}, {n.publicado_em.astimezone(timezone(timedelta(hours=-3))):%d/%m/%Y}",
             n.link.split("*", 1)[1] if "*http" in n.link else n.link) for n in itens[:limite]]


def normas(tema: str = "", dias: int = 21, limite: int = 4) -> list[tuple[str, str, str]]:
    try:
        from quiron.servicos.carreira import radar

        itens = radar.listar(dias, 2, limite=20)
    except Exception:  # noqa: BLE001
        return []
    if tema:
        palavras = re.findall(r"\w{4,}", _norm(tema))
        itens = [i for i in itens if any(p in _norm(f"{i.titulo} {i.resumo}") for p in palavras)]
    return [(f"Norma/projeto: {i.titulo}" + (f" — {i.resumo[:160]}" if i.resumo else ""), f"{i.fonte}, {i.publicado_em:%d/%m/%Y}", i.link)
            for i in itens[:limite]]


def agenda(dias: int = 21) -> list[tuple[str, str]]:
    from quiron.servicos.mercado import painel

    hoje = datetime.now()
    try:
        eventos = [e for e in painel.eventos_fixos() if hoje <= e.quando <= hoje + timedelta(days=dias)]
    except Exception:  # noqa: BLE001
        return []
    return [(f"Agenda: {e.titulo} em {e.quando:%d/%m/%Y}", "Banco Central — calendário oficial do Copom (config/agenda_fixa.yaml)")
            for e in sorted(eventos, key=lambda e: e.quando)[:4]]


def livros(tema: str, n: int = 3) -> list[tuple[str, str]]:
    if not tema:
        return []
    try:
        from quiron.servicos.biblioteca.indice import Indice

        indice = Indice()
        if indice.total_trechos() == 0:
            return []
        res = indice.buscar(tema, n)
    except Exception as e:  # noqa: BLE001
        logging.info("sem biblioteca (%s)", type(e).__name__)
        return []
    return [(f"Trecho de livro: {r.texto[:500]}", r.citacao) for r in res]


AVISO_REGRA = " ⟂a conferir"  # separador interno: o que vem depois vira aviso para o Rickson


def regras(tema: str) -> list[tuple[str, str]]:
    """Regras oficiais ligadas ao tema (config/regras_mercado.yaml), com as contas feitas aqui."""
    from quiron.nucleo.regras import carregar_regras

    t = _norm(tema)
    r = carregar_regras()
    saida = []

    def credito(bloco: dict) -> str:
        return str(bloco.get("fonte", "regras de mercado")) + ("" if bloco.get("verificado_em") else AVISO_REGRA)

    if "poupanca" in t and r.get("poupanca"):
        p = r["poupanca"]
        anual = ((1 + p["rendimento_mensal_acima"]) ** 12 - 1) * 100
        saida.append((f"Regra da poupança: com a Selic acima de {_br(p['selic_gatilho'], 1)}% a.a., rende "
                      f"{_br(p['rendimento_mensal_acima'] * 100, 1)}% ao mês + TR (≈ {_br(anual)}% ao ano + TR); com a Selic até "
                      f"{_br(p['selic_gatilho'], 1)}%, rende {_br(p['percentual_selic_abaixo'] * 100, 0)}% da Selic + TR; isenta de IR "
                      "para pessoa física.", credito(p)))
    if any(k in t for k in ("tesouro", "cdb", "renda fixa", "imposto", " ir", "debenture", "selic", "poupanca")) and r.get("renda_fixa"):
        rf = r["renda_fixa"]
        faixas = []
        for f in rf["ir_tabela_regressiva"]:
            prazo = f"até {f['ate_dias']} dias" if "ate_dias" in f else f"acima de {f['acima_de_dias']} dias"
            faixas.append(f"{prazo}: {_br(f['aliquota'] * 100, 1)}%")
        saida.append(("IR na renda fixa (tabela regressiva sobre o rendimento): " + "; ".join(faixas) + ". Isentos para pessoa física: "
                      + ", ".join(rf.get("isentos_pf", [])) + ".", credito(rf)))
    if "poupanca" in t and ("tesouro" in t or "selic" in t) and r.get("poupanca") and r.get("renda_fixa"):
        try:  # conta pronta: Tesouro Selic líquido em 12 meses × poupança (sem TR), números do dia
            from quiron.servicos.mercado import bcb

            selic = bcb.sgs("selic_meta", 1).ultimo.valor
            ir_1ano = next(f["aliquota"] for f in r["renda_fixa"]["ir_tabela_regressiva"] if f.get("ate_dias", 0) >= 365)
            custodia = (r.get("tesouro_direto") or {}).get("taxa_custodia_b3", 0.0) * 100
            liquido = selic * (1 - ir_1ano) - custodia
            p = r["poupanca"]
            poup = ((1 + p["rendimento_mensal_acima"]) ** 12 - 1) * 100 if selic > p["selic_gatilho"] else selic * p["percentual_selic_abaixo"]
            saida.append((f"Conta (12 meses, Selic constante em {_br(selic)}% a.a.): Tesouro Selic rende ≈ {_br(liquido)}% a.a. líquido "
                          f"(IR de {_br(ir_1ano * 100, 1)}% e custódia de {_br(custodia)}% a.a.) contra ≈ {_br(poup)}% a.a. + TR da poupança — "
                          f"diferença de ≈ {_br(liquido - poup)} pontos percentuais.",
                          "Cálculo próprio com a Selic do Banco Central (SGS 432) e as regras de IR, custódia e poupança"))
        except Exception as e:  # noqa: BLE001
            logging.info("sem conta Tesouro x poupança (%s)", type(e).__name__)
    if any(k in t for k in ("cdb", "fgc", "banco", "lci", "lca", "poupanca", "garantia")) and r.get("fgc"):
        g = r["fgc"]
        saida.append((f"FGC: garante até R$ {_br(g['limite_por_cpf_por_instituicao'], 0)} por CPF por instituição, com teto de R$ "
                      f"{_br(g['teto_global'], 0)} a cada {g['teto_global_renovacao_anos']} anos; cobre {', '.join(g['cobre'])}; não cobre "
                      f"{', '.join(g['nao_cobre'])}.", credito(g)))
    return saida


def coletar(tema: str = "", com_livros: bool = True) -> list[Insumo]:
    itens: list[Insumo] = []

    def add(tipo: str, texto: str, credito: str, link: str = "") -> None:
        aviso = ""
        if AVISO_REGRA in credito:
            credito, aviso = credito.split(AVISO_REGRA)[0], f"regra ainda não conferida em config/regras_mercado.yaml: {credito.split(AVISO_REGRA)[0]}"
        itens.append(Insumo(len(itens) + 1, tipo, texto, credito, link, aviso))

    for t, c in numeros():
        add("numero", t, c)
    for t, c in regras(tema):
        add("regra", t, c)
    for t, c, link in normas(tema):
        add("norma", t, c, link)
    for t, c, link in noticias(tema):
        add("noticia", t, c, link)
    for t, c in agenda():
        add("agenda", t, c)
    if com_livros:
        for t, c in livros(tema):
            add("livro", t, c)
    return itens


def listar_para_modelo(itens: list[Insumo]) -> str:
    return "\n".join(f"[{i.id}] ({i.tipo}) {i.texto}" for i in itens)
