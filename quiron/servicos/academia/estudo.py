"""Operações de estudo independentes de canal (Telegram, Terminal, MCP): escolher/gerar questões, simulados e cards."""

from __future__ import annotations

import logging
import math
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from quiron.nucleo import cerebro
from quiron.servicos.academia import diagnostico, edital, gerador
from quiron.servicos.academia.banco import Banco, Questao

CERT = "CFP"
POR_LOTE = 4  # questões por chamada ao modelo


@dataclass
class Filtro:
    """O que estudar: um módulo (3), um tópico (3.5 / 3.5.2) ou misto pela prioridade do diagnóstico."""

    modulo: int | None = None
    topico: str | None = None

    @classmethod
    def ler(cls, texto: str) -> "Filtro":
        """'3' → módulo 3 · '3.5' → tópico · 'tributação de fundos' → tópico mais parecido · '' → misto."""
        texto = (texto or "").strip()
        if len(texto) > 1 and texto[0] in "mM" and texto[1:].strip().isdigit():  # "m3" ou "M 3"
            texto = texto[1:].strip()
        if not texto:
            return cls()
        if texto.isdigit() and edital.topico(f"{texto}.1"):
            return cls(modulo=int(texto))
        if edital.topico(texto):
            return cls(modulo=int(texto.split(".")[0]), topico=texto)
        achados = edital.buscar(texto, limite=1)
        if achados:
            return cls(modulo=achados[0]["modulo"], topico=achados[0]["codigo"])
        return cls()

    def codigo(self) -> str:
        """Para caber num botão do Telegram: 'x', 'm3' ou 't3.5.2'."""
        return f"t{self.topico}" if self.topico else f"m{self.modulo}" if self.modulo else "x"

    @classmethod
    def do_codigo(cls, c: str) -> "Filtro":
        if c.startswith("t"):
            return cls(modulo=int(c[1:].split(".")[0]), topico=c[1:])
        if c.startswith("m") and c[1:].isdigit():
            return cls(modulo=int(c[1:]))
        return cls()

    def descrever(self) -> str:
        if self.topico:
            t = edital.topico(self.topico)
            return f"tópico {self.topico} {t['titulo'] if t else ''}"
        if self.modulo:
            m = next((m for m in edital.modulos(CERT) if m["numero"] == self.modulo), None)
            return f"módulo {self.modulo} {m['titulo'] if m else ''}"
        return "misto (pelos seus pontos fracos)"


def _modulo_por_prioridade(banco: Banco) -> int:
    mods = diagnostico.diagnosticar(banco, CERT)
    return random.choices([m.numero for m in mods], weights=[m.prioridade for m in mods])[0]


def gerar_lote(banco: Banco, modulo: int, quantas: int, topico: str | None = None) -> list[int]:
    """Gera ao menos `quantas` questões novas (em lotes), respeitando os limites dos modelos grátis."""
    ids: list[int] = []
    alvos = [topico] * math.ceil(quantas / POR_LOTE) if topico else \
        gerador.topicos_para_gerar(modulo, math.ceil(quantas / POR_LOTE) + 1, CERT, banco)
    for alvo in alvos:
        if len(ids) >= quantas:
            break
        try:
            ids += gerador.gerar_questoes(alvo, POR_LOTE, CERT, banco)["gravadas"]
        except cerebro.CerebroIndisponivel:
            logging.warning("cérebro sem cota para gerar questões agora")
            break
        except Exception:  # noqa: BLE001
            logging.exception("falha ao gerar questões de %s", alvo)
    return ids


def disponiveis(banco: Banco, filtro: Filtro, hoje: date | None = None) -> list[Questao]:
    """Questões que valem a pena agora: revisões vencidas e nunca respondidas."""
    hoje = hoje or date.today()
    candidatas = banco.escolher_questoes(CERT, 50, modulo=filtro.modulo, topico=filtro.topico, hoje=hoje)
    respondidas = {r["questao_id"] for r in _respostas(banco)}
    return [q for q in candidatas if q.id not in respondidas or _vencida(banco, q.id, hoje)]


def _respostas(banco: Banco) -> list[dict[str, Any]]:
    with banco._con() as c:  # noqa: SLF001
        return [dict(r) for r in c.execute("SELECT questao_id FROM respostas").fetchall()]


def _vencida(banco: Banco, qid: int, hoje: date) -> bool:
    with banco._con() as c:  # noqa: SLF001
        r = c.execute("SELECT revisar_em FROM questoes WHERE id=?", (qid,)).fetchone()
    return bool(r and r["revisar_em"] and r["revisar_em"] <= hoje.isoformat())


def proxima_questao(banco: Banco, filtro: Filtro, gerar: bool = True) -> Questao | None:
    """Revisão vencida → inédita do filtro → gera mais (se permitido) → qualquer uma do filtro."""
    if not filtro.modulo and not filtro.topico:
        vencidas = [q for q in disponiveis(banco, filtro) if _vencida(banco, q.id, date.today())]
        if vencidas:
            return vencidas[0]
        filtro = Filtro(modulo=_modulo_por_prioridade(banco))
    livres = disponiveis(banco, filtro)
    if livres:
        return livres[0]
    if gerar and filtro.modulo:
        ids = gerar_lote(banco, filtro.modulo, POR_LOTE, filtro.topico)
        if ids:
            return banco.questao(ids[0])
    todas = banco.escolher_questoes(CERT, 1, modulo=filtro.modulo, topico=filtro.topico)
    return todas[0] if todas else None


# ---------------------------------------------------------------- simulados
TIPOS = {"mini": 16, "medio": 40, "completo": 140}


def distribuicao(n: int, cert: str = CERT) -> dict[int, int]:
    """Quantas questões de cada módulo num simulado de n (proporcional ao peso; ao menos 1 por módulo se n ≥ 8)."""
    mods = edital.modulos(cert)
    if n == 16:
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


def montar_simulado(banco: Banco, n: int = 16, gerar: bool = True, paralelo: int = 2) -> tuple[list[int], list[str]]:
    """Escolhe questões inéditas por módulo (gera as que faltarem). Devolve (ids, avisos)."""
    alvo = distribuicao(n)
    escolhidas: dict[int, list[int]] = {}
    faltam: dict[int, int] = {}
    respondidas = {r["questao_id"] for r in _respostas(banco)}
    for mod, k in alvo.items():
        qs = [q.id for q in banco.escolher_questoes(CERT, 200, modulo=mod) if q.id not in respondidas][:k]
        escolhidas[mod] = qs
        if len(qs) < k:
            faltam[mod] = k - len(qs)
    avisos = []
    if faltam and gerar:
        with ThreadPoolExecutor(max_workers=paralelo) as ex:
            for mod, novos in zip(faltam, ex.map(lambda m: gerar_lote(Banco(banco.caminho), m, faltam[m]), faltam)):
                escolhidas[mod] += novos[:faltam[mod]]
    for mod, k in alvo.items():
        if len(escolhidas[mod]) < k:  # completa com já respondidas (revisão) se ainda faltar
            extra = [q.id for q in banco.escolher_questoes(CERT, 50, modulo=mod) if q.id not in escolhidas[mod]]
            escolhidas[mod] += extra[:k - len(escolhidas[mod])]
        if len(escolhidas[mod]) < k:
            avisos.append(f"M{mod}: só {len(escolhidas[mod])} de {k} questões (limite dos modelos grátis agora)")
    ids = [i for mod in sorted(escolhidas) for i in escolhidas[mod]]
    random.shuffle(ids)
    return ids, avisos


def texto_resultado_simulado(banco: Banco, sid: int) -> str:
    r = diagnostico.resumo_simulado(banco, sid)
    if not r["total"]:
        return "Simulado sem respostas."
    pct = r["acertos"] / r["total"]
    nomes = {m["numero"]: m["titulo"] for m in edital.modulos(CERT)}
    linhas = [f"🏁 Simulado #{sid}: {r['acertos']}/{r['total']} ({pct:.0%}) {diagnostico.barra(pct)}",
              "Meta da prova: 70% no total e 50% em cada módulo.", ""]
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
    import yaml

    from quiron.nucleo.config import PASTA_CONFIG

    arq = PASTA_CONFIG / "academia" / "geracao.yaml"
    return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}).get("noturna", {}) if arq.exists() else {}


def lote_noturno(banco: Banco, agora_hhmm: str, cfg: dict[str, Any] | None = None) -> list[int]:
    """Se estiver na janela e algum módulo abaixo da meta, gera um lote no módulo mais carente (pelo peso)."""
    cfg = cfg if cfg is not None else config_geracao()
    if not cfg.get("ligada") or not (cfg.get("inicio", "01:00") <= agora_hhmm < cfg.get("fim", "06:00")):
        return []
    meta = int(cfg.get("meta_por_modulo", 60))
    contagem = banco.contar_questoes(CERT)
    # o mais carente em relação ao peso; empate → o de maior peso
    carentes = [(contagem.get(m["numero"], 0) / (m["peso"] or 1), -m["peso"], m["numero"]) for m in edital.modulos(CERT)
                if contagem.get(m["numero"], 0) < meta]
    if not carentes:
        return []
    return gerar_lote(banco, min(carentes)[2], POR_LOTE)


def garantir_semente(banco: Banco) -> int:
    """Na primeira vez, importa o banco inicial de questões (se o banco estiver vazio)."""
    if sum(banco.contar_questoes(CERT).values()):
        return 0
    from quiron.servicos.academia.cli import semear

    return semear(banco)
