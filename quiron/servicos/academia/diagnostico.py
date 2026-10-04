"""Diagnóstico por módulo/tópico, prontidão estimada para a prova e plano de estudo semanal (3–7 h/semana).

Tudo calculado em Python a partir das respostas gravadas:
- acerto estimado por módulo = (acertos + 1) / (respostas + 2)  (suaviza quando há poucas respostas);
- prontidão = média dos acertos estimados ponderada pelo peso oficial de cada módulo;
- prioridade = peso × distância até a meta (70%) + bônus para módulo pouco praticado;
- o plano distribui as horas da semana pela prioridade, em blocos de 30 min.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from quiron.servicos import areas
from quiron.servicos.academia import edital
from quiron.servicos.academia.banco import Banco

META = 0.70  # aprovação modular/global do CFP
MINIMO_MODULO = 0.50  # prova completa: mínimo por módulo
POUCAS_RESPOSTAS = 8
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


@dataclass
class Modulo:
    numero: int
    titulo: str
    peso: int
    respostas: int = 0
    acertos: int = 0
    topicos: dict[str, list[int]] = field(default_factory=dict)  # tópico nível 1 → [acertos, respostas]
    cert: str = "CFP"  # área (certificação ou campo) a que o módulo pertence

    @property
    def acerto_bruto(self) -> float | None:
        return self.acertos / self.respostas if self.respostas else None

    @property
    def acerto_estimado(self) -> float:
        return (self.acertos + 1) / (self.respostas + 2)

    @property
    def situacao(self) -> str:
        if self.respostas < POUCAS_RESPOSTAS:
            return "pouco praticado"
        a = self.acerto_estimado
        return "acima da meta" if a >= META else "perto da meta" if a >= 0.6 else "abaixo do mínimo" if a < MINIMO_MODULO else "abaixo da meta"

    @property
    def prioridade(self) -> float:
        lacuna = max(0.0, META + 0.05 - self.acerto_estimado)  # mira 75% para ter folga
        pouco = 0.15 if self.respostas < POUCAS_RESPOSTAS else 0.0
        return self.peso * (lacuna + pouco) + 0.5  # +0,5: todo módulo recebe um pouco (revisão)

    def piores_topicos(self, n: int = 2) -> list[str]:
        """Tópicos (nível 1, ex.: 3.5) com menor acerto estimado; os nunca praticados entram como 50%."""
        todos = [t["codigo"] for t in edital.topicos(self.cert, modulo=self.numero, nivel_max=1)]
        def nota(c: str) -> tuple[float, int]:
            a, r = self.topicos.get(c, [0, 0])
            return ((a + 1) / (r + 2), r)
        return sorted(todos, key=nota)[:n]


def diagnosticar(banco: Banco | None = None, cert: str = "CFP", desde: str | None = None) -> list[Modulo]:
    banco = banco or Banco()
    mods = {m["numero"]: Modulo(m["numero"], m["titulo"], m["peso"], cert=cert) for m in edital.modulos(cert)}
    for r in banco.desempenho(cert, desde):
        m = mods.get(r["modulo"])
        if not m:
            continue
        m.respostas += 1
        m.acertos += r["acertou"]
        nivel1 = ".".join(r["topico"].split(".")[:2])
        par = m.topicos.setdefault(nivel1, [0, 0])
        par[0] += r["acertou"]
        par[1] += 1
    return [mods[k] for k in sorted(mods)]


def prontidao(mods: list[Modulo]) -> float:
    total = sum(m.peso for m in mods)
    return sum(m.peso * m.acerto_estimado for m in mods) / total if total else 0.0


def barra(fracao: float, largura: int = 10) -> str:
    cheios = round(max(0.0, min(1.0, fracao)) * largura)
    return "▰" * cheios + "▱" * (largura - cheios)


def nome_area(cert: str) -> str:
    a = areas.obter(cert)
    return a.nome if a else cert


def comando_area(cert: str) -> str:
    """Como digitar a área num comando (/questoes renda fixa 2)."""
    return cert.lower().replace("_", " ")


def data_prova(banco: Banco, cert: str) -> date | None:
    valor = banco.pref(f"data_prova:{cert}") or (banco.pref("data_prova") if cert == "CFP" else None)
    return date.fromisoformat(valor) if valor else None


def texto_diagnostico(mods: list[Modulo], titulo: str | None = None) -> str:
    cert = mods[0].cert if mods else "CFP"
    titulo = titulo or f"Diagnóstico · {nome_area(cert)}"
    respondidas = sum(m.respostas for m in mods)
    if not respondidas:
        return (f"🎯 {titulo}\nAinda não há respostas. Comece com /simulado {comando_area(cert)} "
                f"(mini, {2 * len(mods)} questões) ou /questoes {comando_area(cert)}.")
    p = prontidao(mods)
    regra = "meta 70%; mínimo 50% por módulo na prova completa" if cert == "CFP" else "referência: 70%"
    linhas = [f"🎯 {titulo} — {respondidas} respostas", f"Domínio estimado: {p:.0%} {barra(p)} ({regra})", ""]
    for m in mods:
        bruto = f"{m.acertos}/{m.respostas}" if m.respostas else "—"
        marca = "✅" if m.situacao == "acima da meta" else "🟡" if m.situacao == "perto da meta" else "⚪" if m.situacao == "pouco praticado" else "🔴"
        linhas.append(f"{marca} M{m.numero} {m.titulo[:38]} (peso {m.peso}%): {bruto} · est. {m.acerto_estimado:.0%} — {m.situacao}")
    criticos = sorted([m for m in mods if m.respostas], key=lambda m: m.acerto_estimado)[:3]
    if criticos:
        linhas += ["", "Pontos fracos (tópicos):"]
        for m in criticos:
            for c in m.piores_topicos(1):
                t = edital.topico(c, cert)
                a, r = m.topicos.get(c, [0, 0])
                linhas.append(f"• {c} {t['titulo'] if t else ''} — {a}/{r}" if r else f"• {c} {t['titulo'] if t else ''} — ainda não praticado")
    linhas.append("\nℹ️ Estimativa com suavização: com poucas respostas, o número muda rápido. 📊 Quíron — respostas gravadas")
    return "\n".join(linhas)


# ---------------------------------------------------------------- plano de estudo
@dataclass
class Bloco:
    dia: str
    minutos: int
    modulo: int
    topicos: list[str]
    atividade: str


def plano_semana(mods: list[Modulo], horas: float = 5.0, dias: list[str] | None = None, cartoes: int = 0,
                 data_prova: date | None = None, hoje: date | None = None) -> list[Bloco]:
    """Distribui `horas` pela prioridade de cada módulo, em blocos de 30 min, alternando atividades."""
    dias = dias or ["segunda", "terça", "quarta", "quinta", "sábado"]
    hoje = hoje or date.today()
    blocos_total = max(2, int(round(horas * 2)))  # blocos de 30 min
    prioridades = {m.numero: m.prioridade for m in mods}
    soma = sum(prioridades.values())
    cotas = {k: v / soma * blocos_total for k, v in prioridades.items()}
    alocados = {k: int(v) for k, v in cotas.items()}
    for k in sorted(cotas, key=lambda k: cotas[k] - alocados[k], reverse=True)[:blocos_total - sum(alocados.values())]:
        alocados[k] += 1
    por_mod = {m.numero: m for m in mods}
    fila: list[tuple[int, str]] = []
    for k in sorted(alocados, key=lambda k: -prioridades[k]):
        m = por_mod[k]
        atividades = (["aula", "questões"] if m.respostas < POUCAS_RESPOSTAS else ["questões", "aula"]) + ["questões"] * 10
        fila += [(k, atividades[i]) for i in range(alocados[k])]
    if data_prova and (data_prova - hoje).days <= 21:
        fila = [(k, "simulado" if i % 3 == 2 else a) for i, (k, a) in enumerate(fila)]  # reta final: mais simulado
    blocos: list[Bloco] = []
    for i, (k, atividade) in enumerate(fila):
        dia = dias[i % len(dias)]
        if blocos and blocos[-1].dia == dia and blocos[-1].modulo == k and blocos[-1].atividade == atividade:
            blocos[-1].minutos += 30
            continue
        blocos.append(Bloco(dia, 30, k, por_mod[k].piores_topicos(2), atividade))
    blocos.sort(key=lambda b: DIAS.index(b.dia) if b.dia in DIAS else 9)
    return blocos


def inicio_semana(hoje: date) -> date:
    """Segunda-feira da semana do plano; no domingo, já planeja a semana que começa amanhã."""
    return hoje + timedelta(days=1) if hoje.weekday() == 6 else hoje - timedelta(days=hoje.weekday())


def resumir(texto: str, limite: int = 260) -> str:
    """Primeira(s) frase(s) até o limite, sem cortar palavra no meio."""
    texto = " ".join(texto.split())
    if len(texto) <= limite:
        return texto
    corte = texto.rfind(". ", 0, limite)
    if corte > limite // 3:
        return texto[:corte + 1]
    return texto[:texto.rfind(" ", 0, limite)] + "…"


def texto_plano(mods: list[Modulo], blocos: list[Bloco], horas: float, cartoes: int = 0,
                data_prova: date | None = None, hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    segunda = inicio_semana(hoje)
    cert = mods[0].cert if mods else "CFP"
    area = areas.obter(cert)
    linhas = [f"🗓️ Plano de estudo · {nome_area(cert)} — semana de {segunda:%d/%m} ({horas:g} h)"]
    if data_prova:
        dias = (data_prova - hoje).days
        linhas.append(f"Prova em {data_prova:%d/%m/%Y} — faltam {dias} dias ({dias // 7} semanas).")
    elif area and area.tipo == "certificacao":
        linhas.append(f"Data da prova ainda não definida (diga “minha prova do {cert} é em dd/mm/aaaa”).")
    linhas.append("")
    for dia in DIAS:
        do_dia = [b for b in blocos if b.dia == dia]
        if not do_dia:
            continue
        linhas.append(f"▸ {dia.capitalize()}")
        for b in do_dia:
            m = next(x for x in mods if x.numero == b.modulo)
            tops = ", ".join(f"{c} {(edital.topico(c, cert) or {}).get('titulo', '')[:40]}" for c in b.topicos)
            tema = (edital.topico(b.topicos[0], cert) or {}).get("titulo", "") if b.topicos else m.titulo
            cmd = {"aula": f"/aula {tema[:40]} ({nome_area(cert)})", "questões": f"/questoes {comando_area(cert)} {b.modulo}",
                   "simulado": f"/simulado {comando_area(cert)}"}[b.atividade]
            linhas.append(f"  • {b.minutos} min — {b.atividade} M{b.modulo} ({m.titulo[:30]}): {tops} → {cmd}")
    linhas.append("")
    linhas.append(f"🔁 Todo dia: 10 min de /flashcards" + (f" ({cartoes} para revisar hoje)" if cartoes else "") + " e as questões erradas que voltarem.")
    foco = sorted(mods, key=lambda m: -m.prioridade)[:3]
    linhas.append("Por quê: mais tempo em " + ", ".join(f"M{m.numero} ({m.situacao}, peso {m.peso}%)" for m in foco) + ".")
    return "\n".join(linhas)


def painel(banco: Banco | None = None, cert: str = "CFP", hoje: date | None = None) -> str:
    """Resumo de uma área: domínio, ritmo da semana, banco e revisões pendentes."""
    banco = banco or Banco()
    hoje = hoje or date.today()
    mods = diagnosticar(banco, cert)
    semana = inicio_semana(hoje).isoformat() if hoje.weekday() != 6 else (hoje - timedelta(days=6)).isoformat()
    da_semana = banco.desempenho(cert, desde=semana)
    contagem = banco.contar_questoes(cert)
    prova = data_prova(banco, cert)
    programa = "" if edital.tem_programa(cert) else " · programa ainda não mapeado (questões gerais)"
    linhas = [f"📘 {nome_area(cert)} ({cert}){programa}",
              f"Domínio estimado: {prontidao(mods):.0%} {barra(prontidao(mods))}" if any(m.respostas for m in mods)
              else f"Domínio: faça um /simulado {comando_area(cert)} para medir.",
              f"Esta semana: {len(da_semana)} questões ({sum(r['acertou'] for r in da_semana)} certas)",
              f"Banco: {sum(contagem.values())} questões · {banco.contar_cards(cert)} flashcards · "
              f"revisões para hoje: {banco.revisoes_vencidas(cert, hoje)} questões, {len(banco.cards_vencidos(cert, 999, hoje))} cards"]
    if prova:
        linhas.append(f"Prova: {prova:%d/%m/%Y} (faltam {(prova - hoje).days} dias)")
    linhas.append("")
    for m in mods:
        linhas.append(f"M{m.numero} {barra(m.acerto_estimado if m.respostas else 0, 8)} "
                      f"{(f'{m.acerto_estimado:.0%}' if m.respostas else '—'):>4} {m.titulo[:34]}")
    return "\n".join(linhas)


def painel_geral(banco: Banco | None = None, ativa: str = "CFP", hoje: date | None = None) -> str:
    """Visão de todas as áreas: a ativa em detalhe + as já praticadas + o que existe para estudar."""
    banco = banco or Banco()
    hoje = hoje or date.today()
    dias = banco.dias_estudados()
    seq, d = 0, hoje
    while d.isoformat() in dias:
        seq += 1
        d -= timedelta(days=1)
    todas = areas.listar()
    praticadas = []
    for a in todas:
        mods = diagnosticar(banco, a.id)
        n = sum(m.respostas for m in mods)
        if n and a.id != ativa:
            praticadas.append(f"• {a.nome}: {prontidao(mods):.0%} {barra(prontidao(mods), 6)} ({n} respostas)")
    linhas = [f"🎓 Academia do Quíron — sequência de estudo: {seq} dia(s)", "", painel(banco, ativa, hoje)]
    if praticadas:
        linhas += ["", "Outras áreas praticadas:", *praticadas]
    campos = [a.nome for a in todas if a.tipo == "campo"]
    certs = [a.id.replace("_", " ") for a in todas if a.tipo == "certificacao"]
    linhas += ["", f"Campos ({len(campos)}): " + ", ".join(campos), f"Certificações: " + ", ".join(certs),
               "", "Trocar de área: /area <nome> · /questoes [área] [módulo|tema] · /simulado [área] · /flashcards · "
               "/diagnostico · /plano · /aula <tema> · /caso"]
    return "\n".join(linhas)


def resumo_simulado(banco: Banco, sid: int) -> dict[str, Any]:
    resp = banco.respostas_simulado(sid)
    por_mod: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for r in resp:
        por_mod[r["modulo"]][0] += r["acertou"]
        por_mod[r["modulo"]][1] += 1
    acertos = sum(r["acertou"] for r in resp)
    return {"total": len(resp), "acertos": acertos, "por_modulo": dict(sorted(por_mod.items())),
            "erradas": [r["questao_id"] for r in resp if not r["acertou"]]}
