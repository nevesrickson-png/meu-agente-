"""Operações de estudo independentes de canal (Telegram, Terminal, MCP): escolher/gerar questões, simulados e cards.

Tudo é por ÁREA (certificação como CFP ou campo como ECONOMIA, RISCO, COMERCIAL — `config/areas_conhecimento.yaml`).
Cada área tem um programa (módulos → tópicos) em `config/editais/<ID>.yaml`.
"""

from __future__ import annotations

import logging
import math
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from quiron.nucleo.config import ler_yaml_arquivo
from quiron.nucleo import cerebro
from quiron.servicos import areas
from quiron.servicos.academia import diagnostico, edital, gerador
from quiron.servicos.academia.banco import Banco, Questao

AREA_PADRAO = "CFP"
POR_LOTE = 4  # questões por chamada ao modelo


def area_ativa(banco: Banco) -> str:
    return banco.pref("area_ativa", AREA_PADRAO)


def definir_area_ativa(banco: Banco, area: str) -> None:
    banco.definir_pref("area_ativa", area)
    usadas = [a for a in banco.pref("areas_estudo", [AREA_PADRAO]) if a != area]
    banco.definir_pref("areas_estudo", [area, *usadas][:8])


def nome_area(area: str) -> str:
    a = areas.obter(area)
    return a.nome if a else area


@dataclass
class Filtro:
    """O que estudar: área + módulo (3), tópico (3.5 / 3.5.2) ou misto pela prioridade do diagnóstico."""

    area: str = AREA_PADRAO
    modulo: int | None = None
    topico: str | None = None

    @classmethod
    def ler(cls, texto: str, area_padrao: str = AREA_PADRAO) -> "Filtro":
        """'economia 2' · 'cfp 3.5' · 'renda fixa duration' · '3' (na área ativa) · '' → misto na área ativa."""
        achada, resto = areas.reconhecer(texto or "")
        area = achada.id if achada else area_padrao
        texto = (resto if achada else texto or "").strip()
        if len(texto) > 1 and texto[0] in "mM" and texto[1:].strip().isdigit():  # "m3" ou "M 3"
            texto = texto[1:].strip()
        if not texto:
            return cls(area)
        if texto.isdigit() and edital.topico(f"{texto}.1", area):
            return cls(area, modulo=int(texto))
        if edital.topico(texto, area):
            return cls(area, modulo=int(texto.split(".")[0]), topico=texto)
        achados = edital.buscar(texto, area, limite=1)
        if achados:
            return cls(area, modulo=achados[0]["modulo"], topico=achados[0]["codigo"])
        return cls(area)

    def codigo(self) -> str:
        """Para caber num botão do Telegram: 'CFP|x', 'ECONOMIA|m3' ou 'CFP|t3.5.2'."""
        sufixo = f"t{self.topico}" if self.topico else f"m{self.modulo}" if self.modulo else "x"
        return f"{self.area}|{sufixo}"

    @classmethod
    def do_codigo(cls, c: str) -> "Filtro":
        area, _, c = c.rpartition("|")
        area = area or AREA_PADRAO
        if c.startswith("t"):
            return cls(area, modulo=int(c[1:].split(".")[0]), topico=c[1:])
        if c.startswith("m") and c[1:].isdigit():
            return cls(area, modulo=int(c[1:]))
        return cls(area)

    def descrever(self) -> str:
        if self.topico:
            t = edital.topico(self.topico, self.area)
            return f"{nome_area(self.area)} · tópico {self.topico} {t['titulo'] if t else ''}"
        if self.modulo:
            m = next((m for m in edital.modulos(self.area) if m["numero"] == self.modulo), None)
            return f"{nome_area(self.area)} · módulo {self.modulo} {m['titulo'] if m else ''}"
        return f"{nome_area(self.area)} · misto (pelos seus pontos fracos)"


def _modulo_por_prioridade(banco: Banco, area: str) -> int:
    mods = diagnostico.diagnosticar(banco, area)
    return random.choices([m.numero for m in mods], weights=[m.prioridade for m in mods])[0]


def gerar_lote(banco: Banco, modulo: int, quantas: int, topico: str | None = None, area: str = AREA_PADRAO) -> list[int]:
    """Gera ao menos `quantas` questões novas (em lotes), respeitando os limites dos modelos grátis."""
    ids: list[int] = []
    alvos = [topico] * math.ceil(quantas / POR_LOTE) if topico else \
        gerador.topicos_para_gerar(modulo, math.ceil(quantas / POR_LOTE) + 1, area, banco)
    for alvo in alvos:
        if len(ids) >= quantas:
            break
        try:
            ids += gerador.gerar_questoes(alvo, POR_LOTE, area, banco)["gravadas"]
        except cerebro.CerebroIndisponivel:
            logging.warning("cérebro sem cota para gerar questões agora")
            break
        except Exception:  # noqa: BLE001
            logging.exception("falha ao gerar questões de %s %s", area, alvo)
    return ids


def _respondidas(banco: Banco) -> set[int]:
    with banco._con() as c:  # noqa: SLF001
        return {r["questao_id"] for r in c.execute("SELECT DISTINCT questao_id FROM respostas").fetchall()}


def _vencida(banco: Banco, qid: int, hoje: date) -> bool:
    with banco._con() as c:  # noqa: SLF001
        r = c.execute("SELECT revisar_em FROM questoes WHERE id=?", (qid,)).fetchone()
    return bool(r and r["revisar_em"] and r["revisar_em"] <= hoje.isoformat())


def disponiveis(banco: Banco, filtro: Filtro, hoje: date | None = None) -> list[Questao]:
    """Questões que valem a pena agora: revisões vencidas e nunca respondidas."""
    hoje = hoje or date.today()
    candidatas = banco.escolher_questoes(filtro.area, 50, modulo=filtro.modulo, topico=filtro.topico, hoje=hoje)
    respondidas = _respondidas(banco)
    return [q for q in candidatas if q.id not in respondidas or _vencida(banco, q.id, hoje)]


def proxima_questao(banco: Banco, filtro: Filtro, gerar: bool = True) -> Questao | None:
    """Revisão vencida → inédita do filtro → gera mais (se permitido) → qualquer uma do filtro."""
    if not filtro.modulo and not filtro.topico:
        vencidas = [q for q in disponiveis(banco, filtro) if _vencida(banco, q.id, date.today())]
        if vencidas:
            return vencidas[0]
        filtro = Filtro(filtro.area, modulo=_modulo_por_prioridade(banco, filtro.area))
    livres = disponiveis(banco, filtro)
    if livres:
        return livres[0]
    if gerar and filtro.modulo:
        ids = gerar_lote(banco, filtro.modulo, POR_LOTE, filtro.topico, filtro.area)
        if ids:
            return banco.questao(ids[0])
    todas = banco.escolher_questoes(filtro.area, 1, modulo=filtro.modulo, topico=filtro.topico)
    return todas[0] if todas else None


# ---------------------------------------------------------------- simulados
def tamanho(tipo: str, area: str) -> int:
    """'mini' = 2 por módulo · 'medio' = 40 · 'completo' = tamanho da prova (140 no CFP; 60 nos campos)."""
    mods = edital.modulos(area)
    if tipo.isdigit():
        return max(len(mods), min(140, int(tipo)))
    if tipo in {"medio", "médio"}:
        return 40
    if tipo == "completo":
        return int(edital.carregar(area).get("prova", {}).get("questoes", 60))
    return 2 * len(mods)


def distribuicao(n: int, area: str = AREA_PADRAO) -> dict[int, int]:
    """Quantas questões de cada módulo num simulado de n (proporcional ao peso; ao menos 1 por módulo)."""
    mods = edital.modulos(area)
    if n == 2 * len(mods):
        return {m["numero"]: 2 for m in mods}
    soma = sum(m["peso"] for m in mods)
    cotas = {m["numero"]: n * m["peso"] / soma for m in mods}
    base = {k: max(1 if n >= len(mods) else 0, int(v)) for k, v in cotas.items()}
    for k in sorted(cotas, key=lambda k: cotas[k] - int(cotas[k]), reverse=True):
        if sum(base.values()) >= n:
            break
        base[k] += 1
    while sum(base.values()) > n:
        k = max(base, key=base.get)
        base[k] -= 1
    return base


def montar_simulado(banco: Banco, n: int = 16, gerar: bool = True, paralelo: int = 2,
                    area: str = AREA_PADRAO) -> tuple[list[int], list[str]]:
    """Escolhe questões inéditas por módulo (gera as que faltarem). Devolve (ids, avisos)."""
    alvo = distribuicao(n, area)
    escolhidas: dict[int, list[int]] = {}
    faltam: dict[int, int] = {}
    respondidas = _respondidas(banco)
    for mod, k in alvo.items():
        qs = [q.id for q in banco.escolher_questoes(area, 200, modulo=mod) if q.id not in respondidas][:k]
        escolhidas[mod] = qs
        if len(qs) < k:
            faltam[mod] = k - len(qs)
    avisos = []
    if faltam and gerar:
        with ThreadPoolExecutor(max_workers=paralelo) as ex:
            novos_por_mod = ex.map(lambda m: gerar_lote(Banco(banco.caminho), m, faltam[m], None, area), faltam)
            for mod, novos in zip(faltam, novos_por_mod):
                escolhidas[mod] += novos[:faltam[mod]]
    for mod, k in alvo.items():
        if len(escolhidas[mod]) < k:  # completa com já respondidas (revisão) se ainda faltar
            extra = [q.id for q in banco.escolher_questoes(area, 50, modulo=mod) if q.id not in escolhidas[mod]]
            escolhidas[mod] += extra[:k - len(escolhidas[mod])]
        if len(escolhidas[mod]) < k:
            avisos.append(f"M{mod}: só {len(escolhidas[mod])} de {k} questões (limite dos modelos grátis agora)")
    ids = [i for mod in sorted(escolhidas) for i in escolhidas[mod]]
    random.shuffle(ids)
    return ids, avisos


def texto_resultado_simulado(banco: Banco, sid: int) -> str:
    s = banco.simulado(sid)
    area = s["cert"] if s else AREA_PADRAO
    r = diagnostico.resumo_simulado(banco, sid)
    if not r["total"]:
        return "Simulado sem respostas."
    pct = r["acertos"] / r["total"]
    nomes = {m["numero"]: m["titulo"] for m in edital.modulos(area)}
    meta = "Meta da prova: 70% no total e 50% em cada módulo." if area == "CFP" else "Referência: 70% de acerto."
    linhas = [f"🏁 Simulado #{sid} · {nome_area(area)}: {r['acertos']}/{r['total']} ({pct:.0%}) {diagnostico.barra(pct)}",
              meta, ""]
    for mod, (a, t) in r["por_modulo"].items():
        marca = "✅" if a / t >= 0.7 else "🟡" if a / t >= 0.5 else "🔴"
        linhas.append(f"{marca} M{mod} {nomes.get(mod, '')[:40]}: {a}/{t}")
    if r["erradas"]:
        linhas += ["", "Gabarito das que você errou:"]
        for qid in r["erradas"][:12]:
            q = banco.questao(qid)
            if q:
                linhas.append(f"• Q{qid} ({q.topico}): {q.letra_correta}) {diagnostico.resumir(q.alternativas[q.correta], 110)}\n"
                              f"  {diagnostico.resumir(q.explicacao.splitlines()[0])}")
        linhas.append("As erradas voltam em revisão espaçada nas próximas sessões de /questoes.")
    return "\n".join(linhas)


# ---------------------------------------------------------------- geração automática (madrugada)
def config_geracao() -> dict[str, Any]:

    from quiron.nucleo.config import PASTA_CONFIG

    arq = PASTA_CONFIG / "academia" / "geracao.yaml"
    return (ler_yaml_arquivo(arq) or {}).get("noturna", {}) if arq.exists() else {}


def areas_em_estudo(banco: Banco, dias: int = 30) -> list[str]:
    """Área ativa + as estudadas recentemente (são as que ganham questões novas de madrugada)."""
    desde = (date.today() - timedelta(days=dias)).isoformat()
    with banco._con() as c:  # noqa: SLF001
        recentes = [r[0] for r in c.execute(
            "SELECT DISTINCT q.cert FROM respostas r JOIN questoes q ON q.id=r.questao_id WHERE r.quando >= ?", (desde,))]
    ordem = [area_ativa(banco), *banco.pref("areas_estudo", [AREA_PADRAO]), *recentes]
    return [a for a in dict.fromkeys(ordem) if areas.obter(a)]


def lote_noturno(banco: Banco, agora_hhmm: str, cfg: dict[str, Any] | None = None) -> list[int]:
    """Na janela da madrugada, gera um lote no módulo mais carente (pelo peso) entre as áreas em estudo."""
    cfg = cfg if cfg is not None else config_geracao()
    if not cfg.get("ligada") or not (cfg.get("inicio", "01:00") <= agora_hhmm < cfg.get("fim", "06:00")):
        return []
    meta = int(cfg.get("meta_por_modulo", 60))
    carentes = []
    for area in areas_em_estudo(banco):
        contagem = banco.contar_questoes(area)
        # o mais carente em relação ao peso; empate → o de maior peso
        carentes += [(contagem.get(m["numero"], 0) / (m["peso"] or 1), -m["peso"], area, m["numero"])
                     for m in edital.modulos(area) if contagem.get(m["numero"], 0) < meta]
    if not carentes:
        return []
    _, _, area, modulo = min(carentes)
    return gerar_lote(banco, modulo, POR_LOTE, None, area)


def garantir_semente(banco: Banco) -> int:
    """Na primeira vez, importa o banco inicial de questões do CFP (se ainda não houver questões do CFP)."""
    if sum(banco.contar_questoes("CFP").values()):
        return 0
    from quiron.servicos.academia.cli import semear

    return semear(banco)
