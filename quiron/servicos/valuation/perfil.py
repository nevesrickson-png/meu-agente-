"""Perfil da companhia: o que ela faz, onde atua, quem controla e onde estão as pessoas.

Fontes (todas públicas):
- CVM FCA (cadastro): setor, descrição da atividade, sede, fundação, espécie de controle, site.
- CVM FRE (Formulário de Referência, dados estruturados): acionistas com 5% ou mais, sociedades controladas/coligadas
  (com atividade e sede quando a companhia informa) e empregados por região.
- Yahoo Finance (`info`): descrição do negócio, setor/indústria, número de funcionários. Vem em inglês; o Quíron
  traduz com a IA quando possível (o original fica guardado).

Privacidade: o FRE traz CPF/CNPJ dos acionistas — nunca guardamos nem mostramos documentos, só nome e percentual.
Cache por companhia em `dados/cache_cvm/perfis/<cnpj>.json` (7 dias).
"""

from __future__ import annotations

import json
import logging
import os
import time
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from quiron.servicos.fundos.cvm import digitos
from quiron.servicos.valuation import cvm_cias

VALIDADE_S = 7 * 86400


@dataclass
class Perfil:
    nome: str
    tickers: list[str]
    setor_cvm: str = ""
    descricao_cvm: str = ""
    sede: str = ""
    fundacao: str = ""
    controle: str = ""
    site: str = ""
    setor: str = ""                # Yahoo (sector)
    industria: str = ""            # Yahoo (industry)
    funcionarios: int | None = None
    negocio: str = ""              # descrição do negócio (pt quando traduzida)
    negocio_original: str = ""
    acionistas: list[dict] = field(default_factory=list)      # {nome, pct_total, pct_on, controlador}
    controladas: list[dict] = field(default_factory=list)     # {nome, participacao, atividade, sede}
    empregados_regiao: dict[str, int] = field(default_factory=dict)
    fontes: list[str] = field(default_factory=list)

    def resumo(self) -> str:
        partes = [self.negocio or self.descricao_cvm]
        if self.sede:
            partes.append(f"Sede: {self.sede}.")
        if self.controle:
            partes.append(f"Controle: {self.controle.lower()}.")
        if self.funcionarios:
            partes.append(f"Funcionários: {self.funcionarios:,}".replace(",", ".") + ".")
        return " ".join(p for p in partes if p)


def _pasta():
    p = cvm_cias.pasta_cache() / "perfis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _fca(cnpj: str) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    hoje = date.today()
    for ano in (hoje.year, hoje.year - 1):
        arq = cvm_cias.arquivo("fca", ano)
        if not arq:
            continue
        with zipfile.ZipFile(arq) as z:
            for l in cvm_cias._linhas(z, f"fca_cia_aberta_geral_{ano}.csv"):
                if digitos(l["CNPJ_Companhia"]) == cnpj and int(l.get("Versao") or 0) >= int(saida.get("_versao", -1)):
                    saida.update(_versao=int(l.get("Versao") or 0), setor=l.get("Setor_Atividade", ""),
                                 descricao=(l.get("Descricao_Atividade") or "").strip(), fundacao=l.get("Data_Constituicao", ""),
                                 controle=l.get("Especie_Controle_Acionario", ""), site=l.get("Pagina_Web", ""))
            for l in cvm_cias._linhas(z, f"fca_cia_aberta_endereco_{ano}.csv"):
                if digitos(l["CNPJ_Companhia"]) == cnpj and "Sede" in (l.get("Tipo_Endereco") or ""):
                    saida["sede"] = ", ".join(x for x in (l.get("Cidade", "").strip(), l.get("Sigla_UF", "").strip()) if x)
        if saida:
            break
    return saida


def _fre(cnpj: str) -> dict[str, Any]:
    """Última versão do FRE da companhia: acionistas (≥ 5%, sem documentos), controladas e empregados por região."""
    hoje = date.today()
    for ano in (hoje.year, hoje.year - 1):
        arq = cvm_cias.arquivo("fre", ano)
        if not arq:
            continue
        with zipfile.ZipFile(arq) as z:
            def linhas(nome: str) -> list[dict]:
                achadas = [l for l in cvm_cias._linhas(z, f"fre_cia_aberta_{nome}_{ano}.csv") if digitos(l["CNPJ_Companhia"]) == cnpj]
                if not achadas:
                    return []
                ultima = max(int(l.get("Versao") or 0) for l in achadas)
                return [l for l in achadas if int(l.get("Versao") or 0) == ultima]

            acion = linhas("posicao_acionaria")
            if not acion and not linhas("participacao_sociedade"):
                continue

            def num(v: str | None) -> float:
                try:
                    return float((v or "0").replace(",", "."))
                except ValueError:
                    return 0.0

            acionistas = []
            for l in acion:
                if l.get("ID_Acionista_Relacionado"):  # cadeia societária (quem controla o acionista): fica de fora
                    continue
                pct = num(l.get("Percentual_Total_Acoes_Circulacao"))
                nome = (l.get("Acionista") or "").strip()
                if nome and (pct >= 5 or "outros" in nome.lower() or "tesouraria" in nome.lower()):
                    acionistas.append({"nome": nome[:80], "pct_total": round(pct, 2),
                                       "pct_on": round(num(l.get("Percentual_Acao_Ordinaria_Circulacao")), 2),
                                       "controlador": l.get("Acionista_Controlador") == "S"})
            acionistas.sort(key=lambda a: -a["pct_total"])
            controladas = []
            for l in linhas("participacao_sociedade"):
                sede = ", ".join(x for x in ((l.get("Municipio_Sede") or "").strip(), (l.get("UF_Sede") or "").strip(),
                                             (l.get("Pais_Sede") or "").strip()) if x)
                controladas.append({"nome": (l.get("Razao_Social") or "").strip()[:90], "participacao": round(num(l.get("Participacao_Emissor")), 2),
                                    "tipo": (l.get("Tipo_Sociedade") or "").strip(), "atividade": (l.get("Descricao_Atividades") or "").strip()[:160],
                                    "sede": sede})
            controladas.sort(key=lambda c: (-c["participacao"], c["nome"]))
            regioes = {"Norte": 0, "Nordeste": 0, "Centro-Oeste": 0, "Sudeste": 0, "Sul": 0, "Exterior": 0}
            for l in linhas("empregado_posicao_local"):
                for r in regioes:
                    regioes[r] += int(num(l.get(f"Quantidade_{r.replace('-', '_')}")))
            return {"acionistas": acionistas[:10], "controladas": controladas,
                    "empregados_regiao": {k: v for k, v in regioes.items() if v}}
    return {}


def _yahoo(ticker: str) -> dict[str, Any]:
    if not ticker:
        return {}
    try:
        import yfinance as yf

        i = yf.Ticker(f"{ticker}.SA").info or {}
    except Exception as e:  # noqa: BLE001
        logging.info("perfil sem Yahoo (%s)", type(e).__name__)
        return {}
    return {"setor": i.get("sector") or "", "industria": i.get("industry") or "", "funcionarios": i.get("fullTimeEmployees"),
            "negocio_original": (i.get("longBusinessSummary") or "").strip()}


def _traduzir(texto: str, config=None) -> str:
    if not texto:
        return ""
    from quiron.nucleo import cerebro

    try:
        r = cerebro.perguntar(texto[:3500], sistema="Traduza para o português do Brasil, fiel e sem acrescentar nada. "
                              "Devolva só a tradução, em um parágrafo.", config=config, temperatura=0.1, max_tokens=4000)
        return (r.texto or "").strip()
    except Exception as e:  # noqa: BLE001 — sem IA fica o original em inglês
        logging.info("perfil sem tradução (%s)", type(e).__name__)
        return ""


def perfil(termo: str | cvm_cias.Empresa, traduzir: bool = True, config=None) -> Perfil:
    e = termo if isinstance(termo, cvm_cias.Empresa) else cvm_cias.empresa(termo)
    cache = _pasta() / f"{e.cnpj}.json"
    if cache.exists() and cache.stat().st_mtime > time.time() - VALIDADE_S:
        try:
            return Perfil(**json.loads(cache.read_text(encoding="utf-8")))
        except (TypeError, ValueError):
            pass
    fca, fre, yh = _fca(e.cnpj), _fre(e.cnpj), _yahoo(e.ticker)
    p = Perfil(e.nome, list(e.tickers), fca.get("setor") or e.setor, fca.get("descricao") or e.descricao, fca.get("sede", ""),
               fca.get("fundacao", ""), fca.get("controle", ""), fca.get("site", ""), yh.get("setor", ""), yh.get("industria", ""),
               yh.get("funcionarios"), "", yh.get("negocio_original", ""), fre.get("acionistas", []), fre.get("controladas", []),
               fre.get("empregados_regiao", {}))
    traducao = _traduzir(p.negocio_original, config) if traduzir else ""
    p.negocio = traducao or p.negocio_original
    p.fontes = [f for f, ok in (("CVM FCA (cadastro)", fca), ("CVM FRE (Formulário de Referência)", fre),
                                ("Yahoo Finance (perfil)", yh.get("negocio_original") or yh.get("setor"))) if ok]
    completo = bool(fca and fre and yh.get("negocio_original")) and (bool(traducao) or not traduzir)
    if fca:  # perfil vazio (sem rede) não vai para o cache; incompleto (sem FRE/Yahoo/tradução) vale só 6 horas
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(p), ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)
        if not completo:
            os.utime(cache, (time.time() - VALIDADE_S + 6 * 3600,) * 2)
    return p


def secao(p: Perfil):
    """Seção "Perfil e atividades" para os relatórios (texto + tabelas)."""
    from quiron.servicos.analise.relatorio import Secao, Tabela

    quem = [["Setor (CVM)", p.setor_cvm or "—"], ["Setor / indústria (Yahoo)", " / ".join(x for x in (p.setor, p.industria) if x) or "—"],
            ["Sede", p.sede or "—"], ["Fundação", "/".join(reversed(p.fundacao.split("-"))) if p.fundacao else "—"],
            ["Controle acionário", p.controle or "—"],
            ["Funcionários", f"{p.funcionarios:,}".replace(",", ".") if p.funcionarios else "—"],
            ["Ações em bolsa", ", ".join(p.tickers) or "—"], ["Site", p.site or "—"]]
    tabelas = [Tabela("Quem é", ["Item", "Dado"], quem, ["texto", "texto"])]
    if p.acionistas:
        tabelas.append(Tabela("Principais acionistas (5% ou mais do capital, FRE)", ["Acionista", "% do capital", "% das ON", "Controlador"],
                              [[a["nome"], a["pct_total"], a["pct_on"], "sim" if a["controlador"] else ""] for a in p.acionistas],
                              ["texto", "pct", "pct", "texto"]))
    if p.controladas:
        tabelas.append(Tabela(f"Controladas e participações ({len(p.controladas)} no FRE; as 15 maiores)",
                              ["Sociedade", "Participação", "Atividade", "Sede"],
                              [[c["nome"], c["participacao"], c["atividade"] or "—", c["sede"] or "—"] for c in p.controladas[:15]],
                              ["texto", "pct", "texto", "texto"]))
    if p.empregados_regiao:
        total = sum(p.empregados_regiao.values())
        tabelas.append(Tabela("Empregados por região (FRE)", ["Região", "Empregados", "% do total"],
                              [[r, n, round(n / total * 100, 1)] for r, n in sorted(p.empregados_regiao.items(), key=lambda x: -x[1])],
                              ["texto", "int", "pct"]))
    texto = p.negocio or p.descricao_cvm
    if p.negocio and p.descricao_cvm and p.descricao_cvm not in texto:
        texto += f"\n\nNo cadastro da CVM: {p.descricao_cvm}"
    return Secao("Perfil e atividades", texto, tabelas)


def fatos(p: Perfil) -> dict[str, Any]:
    return {"setor_cvm": p.setor_cvm, "industria": p.industria, "sede": p.sede, "controle": p.controle,
            "funcionarios": p.funcionarios, "acionistas_5pct": [(a["nome"], a["pct_total"]) for a in p.acionistas[:5]],
            "n_controladas": len(p.controladas), "empregados_regiao": p.empregados_regiao}


def texto(p: Perfil) -> str:
    """Para o MCP/Telegram."""
    linhas = [f"🏢 **{p.nome}** ({', '.join(p.tickers) or 'sem ação em bolsa'})", p.resumo()]
    if p.setor_cvm or p.industria:
        linhas.append(f"Setor: {p.setor_cvm}{' · ' + p.industria if p.industria else ''}")
    if p.acionistas:
        linhas.append("Acionistas (≥ 5%): " + "; ".join(f"{a['nome']} {str(a['pct_total']).replace('.', ',')}%"
                                                       f"{' (controlador)' if a['controlador'] else ''}" for a in p.acionistas[:6]))
    if p.controladas:
        linhas.append(f"Controladas/participações: {len(p.controladas)} — ex.: " + "; ".join(
            c["nome"] + (f" ({c['atividade'][:60]})" if c["atividade"] else "") for c in p.controladas[:6]))
    if p.empregados_regiao:
        linhas.append("Empregados por região: " + " · ".join(f"{r} {n:,}".replace(",", ".") for r, n in
                                                             sorted(p.empregados_regiao.items(), key=lambda x: -x[1])))
    linhas.append("📊 " + " · ".join(p.fontes))
    return "\n".join(linhas)
