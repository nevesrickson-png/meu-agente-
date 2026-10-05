"""Treino com cliente simulado: o modelo interpreta um cliente fictício (`config/treino.yaml`) e, no fim, o Quíron
avalia a conversa.

O feedback junta duas coisas:
- métricas calculadas em Python (quanto o assessor falou, perguntas abertas, alertas de compliance nas falas dele,
  se combinou próximo passo);
- a avaliação do modelo por critério da rubrica (nota 0–10 com evidência). A nota final é a média ponderada feita aqui;
  alerta grave de compliance limita a nota de compliance a 3.
Sessões em `dados/treino.db` (personagens fictícios — nada de cliente real)."""

from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quiron.nucleo import cerebro
from quiron.nucleo.config import ler_yaml, pasta_dados
from quiron.servicos.assessoria import compliance


class TreinoInvalido(ValueError):
    pass


def config() -> dict[str, Any]:
    return ler_yaml("treino")


@dataclass
class Sessao:
    id: int
    personagem: str
    cenario: str
    dificuldade: str
    iniciada_em: str
    mensagens: list[dict[str, str]] = field(default_factory=list)  # {"papel": "assessor"|"cliente", "texto"}
    encerrada_em: str = ""
    feedback: dict[str, Any] | None = None

    @property
    def ficha(self) -> dict[str, Any]:
        return config()["personagens"][self.personagem]


def _banco() -> sqlite3.Connection:
    caminho = pasta_dados() / "treino.db"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE IF NOT EXISTS sessoes (id INTEGER PRIMARY KEY, personagem TEXT, cenario TEXT, dificuldade TEXT, "
                "iniciada_em TEXT, encerrada_em TEXT DEFAULT '', mensagens TEXT DEFAULT '[]', feedback TEXT)")
    return con


def _ler(linha: tuple) -> Sessao:
    i, p, c, d, ini, fim, msgs, fb = linha
    return Sessao(i, p, c, d, ini, json.loads(msgs), fim or "", json.loads(fb) if fb else None)


def _gravar(s: Sessao) -> None:
    with _banco() as con:
        con.execute("UPDATE sessoes SET mensagens = ?, encerrada_em = ?, feedback = ? WHERE id = ?",
                    (json.dumps(s.mensagens, ensure_ascii=False), s.encerrada_em,
                     json.dumps(s.feedback, ensure_ascii=False) if s.feedback is not None else None, s.id))


def obter(ident: int) -> Sessao:
    with _banco() as con:
        linha = con.execute("SELECT * FROM sessoes WHERE id = ?", (ident,)).fetchone()
    if not linha:
        raise TreinoInvalido(f"treino #{ident} não existe")
    return _ler(linha)


def ativa() -> Sessao | None:
    with _banco() as con:
        linha = con.execute("SELECT * FROM sessoes WHERE encerrada_em = '' ORDER BY id DESC LIMIT 1").fetchone()
    return _ler(linha) if linha else None


def listar(limite: int = 10) -> list[Sessao]:
    with _banco() as con:
        return [_ler(x) for x in con.execute("SELECT * FROM sessoes ORDER BY id DESC LIMIT ?", (limite,))]


def opcoes() -> str:
    c = config()
    linhas = ["Personagens (fictícios):"]
    linhas += [f"• {k} — {p['nome']}: {p['resumo']}" for k, p in c["personagens"].items()]
    linhas += ["", "Cenários:"] + [f"• {k} — {v['nome']}" for k, v in c["cenarios"].items()]
    linhas += ["", "Dificuldade: " + " · ".join(c["dificuldades"]),
               "Ex.: /treino medico_ocupado primeira_reuniao dificil  (sem nada = sorteio)"]
    return "\n".join(linhas)


def _escolher(texto: str, opcoes_: dict[str, Any], padrao: str | None = None) -> str:
    for k in opcoes_:
        if re.search(rf"\b{re.escape(k)}\b", texto):
            return k
    return padrao or random.choice(list(opcoes_))


# ---------------------------------------------------------------- o cliente simulado
def _sistema(s: Sessao) -> str:
    c = config()
    p = s.ficha
    return (
        "Você é um CLIENTE FICTÍCIO num treino de um assessor de investimentos brasileiro. Interprete o personagem com "
        "realismo. Regras: fale só como o cliente, em português do Brasil coloquial, 1 a 4 frases por vez; nunca saia do "
        "personagem, nunca dê dicas ao assessor, nunca diga que é uma IA. Revele informações aos poucos, só quando o "
        "assessor perguntar bem ou criar confiança. Não aceite promessa de rentabilidade: desconfie. Não use nomes reais.\n\n"
        f"Personagem: {p['nome']} — {p['resumo']}.\nPatrimônio: {p['patrimonio']}.\nJeito: {p['estilo']}.\n"
        f"Perfil de risco real (não diga o rótulo): {p['perfil_real']}.\n"
        f"Objetivo OCULTO (só revele se o assessor investigar com perguntas abertas sobre vida/família/planos): {p['objetivo_oculto']}.\n"
        f"Objeções que você levanta no momento certo: {'; '.join(p['objecoes'])}.\n"
        f"Você se abre com: {p['abre_se_com']}. Você se fecha com: {p['fecha_se_com']}.\n"
        f"Cenário: {c['cenarios'][s.cenario]['nome']} — {c['cenarios'][s.cenario]['instrucao']}\n"
        f"Dificuldade: {c['dificuldades'][s.dificuldade]}"
    )


def _falar(s: Sessao, **extras: Any) -> str:
    msgs: list[dict[str, Any]] = [{"role": "system", "content": _sistema(s)}]
    if not s.mensagens:
        msgs.append({"role": "user", "content": "(O assessor acabou de te cumprimentar. Abra a conversa como o cliente.)"})
    for m in s.mensagens:
        msgs.append({"role": "user" if m["papel"] == "assessor" else "assistant", "content": m["texto"]})
    t = cerebro.conversar(msgs, temperatura=0.8, **extras)
    nome = re.escape(s.ficha["nome"])
    texto = re.sub(rf"^\s*\**\s*(?:{nome}|Cliente)\s*\**\s*:\s*\**\s*", "", (t.texto or "").strip(), flags=re.I)
    return texto or "…"


def iniciar(pedido: str = "", **extras: Any) -> tuple[Sessao, str]:
    """Começa um treino (encerra o anterior sem feedback). `pedido` pode citar personagem, cenário e dificuldade."""
    c = config()
    pedido = (pedido or "").lower()
    if (a := ativa()) is not None:
        a.encerrada_em = datetime.now().isoformat(timespec="seconds")
        _gravar(a)
    personagem = _escolher(pedido, c["personagens"])
    cenario = _escolher(pedido, c["cenarios"], "cliente_insatisfeito" if personagem == "cliente_insatisfeito" else None)
    dificuldade = _escolher(pedido, c["dificuldades"], "normal")
    with _banco() as con:
        cur = con.execute("INSERT INTO sessoes(personagem, cenario, dificuldade, iniciada_em) VALUES (?,?,?,?)",
                          (personagem, cenario, dificuldade, datetime.now().isoformat(timespec="seconds")))
    s = obter(cur.lastrowid)
    abertura = _falar(s, **extras)
    s.mensagens.append({"papel": "cliente", "texto": abertura})
    _gravar(s)
    p = s.ficha
    cab = (f"🎭 Treino #{s.id} — {c['cenarios'][cenario]['nome']} · dificuldade {dificuldade}\n"
           f"Cliente: {p['nome']}, {p['resumo']}.\nResponda como faria na reunião (texto ou áudio). "
           "/treino fim encerra e traz o feedback.")
    return s, f"{cab}\n\n🗣️ {p['nome']}: {abertura}"


def responder(fala: str, **extras: Any) -> str:
    s = ativa()
    if s is None:
        raise TreinoInvalido("nenhum treino ativo — comece com /treino")
    fala = (fala or "").strip()
    if not fala:
        return "…"
    s.mensagens.append({"papel": "assessor", "texto": fala[:3000]})
    resposta = _falar(s, **extras)
    s.mensagens.append({"papel": "cliente", "texto": resposta})
    _gravar(s)
    return f"🗣️ {s.ficha['nome']}: {resposta}"


# ---------------------------------------------------------------- feedback
_ABERTAS = r"^\s*(como|o que|o quê|por que|porque|pra que|para que|qual|quais|me conta|me conte|conta|fala|me fala|quando|onde|quem|de que forma|em que)\b"
_PROXIMO = r"\b(agend\w*|marc\w* (uma|a|outra|nova)? ?(reuni|convers|call|liga)|pr[oó]xim\w* (reuni|passo|encontro|conversa)|te mando|vou te (mandar|enviar)|envio .{0,20}(at[eé]|amanh)|semana que vem|na (segunda|terça|quarta|quinta|sexta))"


def metricas(s: Sessao) -> dict[str, Any]:
    falas = [m["texto"] for m in s.mensagens if m["papel"] == "assessor"]
    cliente = [m["texto"] for m in s.mensagens if m["papel"] == "cliente"]
    palavras_a = sum(len(f.split()) for f in falas)
    palavras_c = sum(len(f.split()) for f in cliente)
    perguntas, abertas = [], []
    for f in falas:
        for seg in re.findall(r"[^.!?]+[.!?]?", f):
            q = seg.strip()
            nucleo = re.sub(r"^(e|mas|então|entao|agora)\s+", "", re.split(r"[:;,]\s*", q)[-1].strip(), flags=re.I)
            if q.endswith("?"):
                perguntas.append(q)
                if re.search(_ABERTAS, nucleo, re.I) or re.search(_ABERTAS, q, re.I):
                    abertas.append(q)
            elif re.match(r"^(me )?(conta|conte|fala|explica|descreve)\b", nucleo, re.I):  # convite aberto sem "?"
                abertas.append(q)
    alertas = compliance.conferir("\n".join(falas))
    return {
        "falas_assessor": len(falas),
        "palavras_assessor": palavras_a,
        "fala_do_assessor_pct": round(100 * palavras_a / (palavras_a + palavras_c), 1) if palavras_a + palavras_c else 0.0,
        "perguntas": len(perguntas),
        "perguntas_abertas": len(abertas),
        "exemplos_abertas": abertas[:3],
        "proximo_passo": bool(re.search(_PROXIMO, " ".join(falas[-4:]), re.I)),
        "compliance": [a.descrever() for a in alertas],
        "compliance_grave": any(a.gravidade == "grave" for a in alertas),
    }


PEDIDO_FEEDBACK = """Avalie o desempenho do ASSESSOR neste treino com cliente simulado, como um coach sênior de assessores
de investimento (direto e franco, sem bajulação). Use só o que está na conversa; cite trechos curtos como evidência.

Personagem: {nome} — {resumo}. Objetivo oculto: {oculto}. Objeções previstas: {objecoes}.
Cenário: {cenario}.
Métricas calculadas: {metricas}

Rubrica (nota 0 a 10 cada): {rubrica}

Conversa:
{conversa}

Responda SÓ com JSON:
{{"criterios": {{"<id do critério>": {{"nota": 0-10, "evidencia": "trecho/observação", "melhoria": "o que fazer diferente"}}}},
 "objetivo_oculto_descoberto": true/false,
 "objecoes": [{{"objecao": "...", "tratada": true/false, "comentario": "..."}}],
 "pontos_fortes": ["..."], "melhorar": ["até 3, os mais importantes primeiro"],
 "reescritas": [{{"disse": "frase do assessor", "melhor": "como diria um assessor sênior"}}],
 "resumo": "2 frases"}}"""


def encerrar(**extras: Any) -> tuple[Sessao, str]:
    s = ativa()
    if s is None:
        raise TreinoInvalido("nenhum treino ativo — comece com /treino")
    s.encerrada_em = datetime.now().isoformat(timespec="seconds")
    met = metricas(s)
    fb: dict[str, Any] = {"metricas": met, "origem": "regras"}
    if met["falas_assessor"] >= 2:
        c, p = config(), s.ficha
        conversa = "\n".join(f"{'ASSESSOR' if m['papel'] == 'assessor' else 'CLIENTE'}: {m['texto']}" for m in s.mensagens)
        rubrica = "; ".join(f"{k} = {v['nome']}: {v['descricao']}" for k, v in c["rubrica"].items())
        try:
            r = cerebro.perguntar(
                PEDIDO_FEEDBACK.format(nome=p["nome"], resumo=p["resumo"], oculto=p["objetivo_oculto"], objecoes="; ".join(p["objecoes"]),
                                       cenario=c["cenarios"][s.cenario]["nome"], metricas=json.dumps(met, ensure_ascii=False),
                                       rubrica=rubrica, conversa=conversa[-15000:]),
                sistema="Você é um coach de assessores de investimento no Brasil. Responda só JSON válido.", temperatura=0.2,
                max_tokens=4000, response_format={"type": "json_object"}, **extras)
            bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.texto.strip())
            fb.update(json.loads(bruto[bruto.find("{"):bruto.rfind("}") + 1]))
            fb["origem"] = "ia"
        except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
            logging.warning("feedback do treino sem IA (%s)", type(e).__name__)
    fb["nota_final"] = nota_final(fb, met)
    s.feedback = fb
    _gravar(s)
    return s, texto_feedback(s)


def nota_final(fb: dict[str, Any], met: dict[str, Any]) -> float | None:
    """Média ponderada pela rubrica (0–10), com teto de 3 em compliance se houve alerta grave."""
    rub = config()["rubrica"]
    crit = fb.get("criterios") or {}
    soma = pesos = 0.0
    for k, v in rub.items():
        try:
            nota = float((crit.get(k) or {}).get("nota"))
        except (TypeError, ValueError):
            continue
        nota = max(0.0, min(10.0, nota))
        if k == "compliance" and met.get("compliance_grave"):
            nota = min(nota, 3.0)
            crit[k]["nota"] = nota
        soma += nota * v["peso"]
        pesos += v["peso"]
    return round(soma / pesos, 1) if pesos else None


def texto_feedback(s: Sessao) -> str:
    fb, rub = s.feedback or {}, config()["rubrica"]
    met = fb.get("metricas", {})
    p = s.ficha
    linhas = [f"📋 Feedback do treino #{s.id} — {p['nome']} ({config()['cenarios'][s.cenario]['nome']})"]
    if fb.get("nota_final") is not None:
        linhas.append(f"Nota geral: {fb['nota_final']:.1f}/10".replace(".", ","))
    if fb.get("resumo"):
        linhas.append(str(fb["resumo"]))
    crit = fb.get("criterios") or {}
    if crit:
        linhas.append("")
        for k, v in rub.items():
            c = crit.get(k) or {}
            if c.get("nota") is None:
                continue
            linhas.append(f"• {v['nome']}: {float(c['nota']):.0f}/10 — {c.get('melhoria') or c.get('evidencia') or ''}".strip(" —"))
    linhas += ["", "Números da conversa (calculados):",
               f"• Você falou {str(met.get('fala_do_assessor_pct', 0)).replace('.', ',')}% das palavras "
               f"(meta em descoberta: até ~40%) · {met.get('perguntas', 0)} perguntas · {met.get('perguntas_abertas', 0)} abertas (inclui convites como “me conta”)",
               f"• Próximo passo combinado: {'sim' if met.get('proximo_passo') else 'não'}"]
    if "objetivo_oculto_descoberto" in fb:
        linhas.append(f"• Objetivo oculto: {'descoberto ✅' if fb['objetivo_oculto_descoberto'] else 'não descoberto'} — era: {p['objetivo_oculto']}")
    for o in fb.get("objecoes") or []:
        linhas.append(f"• Objeção “{o.get('objecao', '')}”: {'tratada ✅' if o.get('tratada') else 'não tratada'}"
                      + (f" — {o['comentario']}" if o.get("comentario") else ""))
    if met.get("compliance"):
        linhas += ["", "Compliance nas suas falas:"] + met["compliance"]
    if fb.get("pontos_fortes"):
        linhas += ["", "Mandou bem:"] + [f"• {x}" for x in fb["pontos_fortes"][:3]]
    if fb.get("melhorar"):
        linhas += ["", "Para o próximo:"] + [f"• {x}" for x in fb["melhorar"][:3]]
    for r in (fb.get("reescritas") or [])[:2]:
        linhas += ["", f"Você disse: “{r.get('disse', '')}”", f"Melhor: “{r.get('melhor', '')}”"]
    if fb.get("origem") == "regras":
        linhas += ["", "⚠️ Sem IA no momento (ou conversa curta demais): só os números calculados."]
    return "\n".join(linhas)


def evolucao(limite: int = 20) -> str:
    """Notas dos últimos treinos e média por critério (para ver a evolução)."""
    sessoes = [s for s in listar(limite) if s.feedback and s.feedback.get("nota_final") is not None]
    if not sessoes:
        return "Nenhum treino avaliado ainda. Comece com /treino."
    rub = config()["rubrica"]
    linhas = ["Seus treinos (mais recentes primeiro):"]
    linhas += [f"• #{s.id} {s.iniciada_em[:10]} {s.ficha['nome']} ({s.dificuldade}): {s.feedback['nota_final']:.1f}".replace(".", ",")
               for s in sessoes[:10]]
    medias = []
    for k, v in rub.items():
        notas = [float(s.feedback["criterios"][k]["nota"]) for s in sessoes if (s.feedback.get("criterios") or {}).get(k, {}).get("nota") is not None]
        if notas:
            medias.append((sum(notas) / len(notas), v["nome"]))
    if medias:
        linhas += ["", "Média por critério (o mais fraco primeiro):"] + [f"• {n}: {m:.1f}".replace(".", ",") for m, n in sorted(medias)]
    return "\n".join(linhas)


def caminho_banco() -> Path:
    return pasta_dados() / "treino.db"
