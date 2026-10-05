"""Simulação de entrevista para os cargos-alvo (`config/entrevista.yaml`): o modelo faz o papel do entrevistador, uma
pergunta por vez; no fim, feedback com métricas calculadas aqui + rubrica do modelo (nota ponderada aqui)."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from quiron.nucleo import cerebro
from quiron.nucleo.config import ler_yaml
from quiron.servicos.carreira.banco import conectar


class EntrevistaInvalida(ValueError):
    pass


def config() -> dict[str, Any]:
    return ler_yaml("entrevista")


@dataclass
class Sessao:
    id: int
    cargo: str
    iniciada_em: str
    encerrada_em: str = ""
    mensagens: list[dict[str, str]] = field(default_factory=list)  # {"papel": "entrevistador"|"candidato", "texto"}
    feedback: dict[str, Any] | None = None


def _de(r) -> Sessao:
    return Sessao(r["id"], r["cargo"], r["iniciada_em"], r["encerrada_em"] or "", json.loads(r["mensagens"]),
                  json.loads(r["feedback"]) if r["feedback"] else None)


def _gravar(s: Sessao) -> None:
    with conectar() as con:
        con.execute("UPDATE entrevistas SET mensagens = ?, encerrada_em = ?, feedback = ? WHERE id = ?",
                    (json.dumps(s.mensagens, ensure_ascii=False), s.encerrada_em,
                     json.dumps(s.feedback, ensure_ascii=False) if s.feedback is not None else None, s.id))


def ativa() -> Sessao | None:
    with conectar() as con:
        r = con.execute("SELECT * FROM entrevistas WHERE encerrada_em = '' ORDER BY id DESC LIMIT 1").fetchone()
    return _de(r) if r else None


def opcoes() -> str:
    return "Cargos:\n" + "\n".join(f"• {k} — {v['nome']}" for k, v in config()["cargos"].items()) + \
        "\n\nEx.: /entrevista estrategista · /entrevista fim (feedback)"


def _sistema(s: Sessao) -> str:
    c = config()["cargos"][s.cargo]
    return ("Você é o ENTREVISTADOR numa simulação de entrevista de emprego no mercado financeiro brasileiro. "
            f"Cargo: {c['nome']}. Você é: {c['entrevistador']}. Temas a cobrir: {'; '.join(c['temas'])}. "
            "Regras: uma pergunta por vez, curta (1–3 frases); aprofunde quando a resposta for vaga; misture técnica e "
            "comportamental; não dê a resposta nem elogie à toa; português do Brasil. Depois de umas 6 perguntas, diga que "
            "a entrevista terminou e que o candidato pode digitar /entrevista fim para o feedback.")


def _falar(s: Sessao, **extras: Any) -> str:
    msgs: list[dict[str, Any]] = [{"role": "system", "content": _sistema(s)}]
    if not s.mensagens:
        msgs.append({"role": "user", "content": "(O candidato entrou na sala. Cumprimente rapidamente e faça a primeira pergunta.)"})
    for m in s.mensagens:
        msgs.append({"role": "user" if m["papel"] == "candidato" else "assistant", "content": m["texto"]})
    t = cerebro.conversar(msgs, temperatura=0.7, **extras)
    return re.sub(r"^\s*\**\s*Entrevistador\s*\**\s*:\s*\**\s*", "", (t.texto or "").strip(), flags=re.I) or "…"


def iniciar(pedido: str = "", **extras: Any) -> tuple[Sessao, str]:
    cargos = config()["cargos"]
    pedido = (pedido or "").lower()
    cargo = next((k for k in cargos if k in pedido), None) or random.choice(list(cargos))
    if (a := ativa()) is not None:
        a.encerrada_em = datetime.now().isoformat(timespec="seconds")
        _gravar(a)
    with conectar() as con:
        cur = con.execute("INSERT INTO entrevistas(cargo, iniciada_em) VALUES (?,?)", (cargo, datetime.now().isoformat(timespec="seconds")))
        r = con.execute("SELECT * FROM entrevistas WHERE id = ?", (cur.lastrowid,)).fetchone()
    s = _de(r)
    try:
        abertura = _falar(s, **extras)
    except Exception:  # sem IA agora: não deixa uma sessão aberta capturando as próximas mensagens
        s.encerrada_em = datetime.now().isoformat(timespec="seconds")
        _gravar(s)
        raise
    s.mensagens.append({"papel": "entrevistador", "texto": abertura})
    _gravar(s)
    return s, (f"💼 Entrevista #{s.id} — {cargos[cargo]['nome']}\nResponda como na entrevista (texto ou áudio). "
               f"/entrevista fim encerra e traz o feedback.\n\n🎤 {abertura}")


def responder(fala: str, **extras: Any) -> str:
    s = ativa()
    if s is None:
        raise EntrevistaInvalida("nenhuma entrevista ativa — comece com /entrevista")
    s.mensagens.append({"papel": "candidato", "texto": (fala or "").strip()[:4000]})
    resposta = _falar(s, **extras)
    s.mensagens.append({"papel": "entrevistador", "texto": resposta})
    _gravar(s)
    return f"🎤 {resposta}"


def metricas(s: Sessao) -> dict[str, Any]:
    respostas = [m["texto"] for m in s.mensagens if m["papel"] == "candidato"]
    palavras = [len(r.split()) for r in respostas]
    estrutura = r"\b(primeiro|segundo|terceiro|em resumo|resumindo|conclus|por um lado|três pontos|tres pontos|dois pontos)\b"
    return {
        "respostas": len(respostas),
        "palavras_media": round(sum(palavras) / len(palavras), 0) if palavras else 0,
        "com_numeros_pct": round(100 * sum(bool(re.search(r"\d", r)) for r in respostas) / len(respostas), 0) if respostas else 0,
        "estruturadas": sum(bool(re.search(estrutura, r, re.I)) for r in respostas),
        "fala_de_risco": sum(bool(re.search(r"\b(risco|premissa|incerteza|cenário|cenario)\w*", r, re.I)) for r in respostas),
    }


PEDIDO = """Avalie o CANDIDATO nesta simulação de entrevista para {cargo}, como um entrevistador sênior franco.
Métricas calculadas: {metricas}
Rubrica (0 a 10 cada): {rubrica}
Conversa:
{conversa}

Responda SÓ com JSON: {{"criterios": {{"<id>": {{"nota": 0-10, "evidencia": "...", "melhoria": "..."}}}},
 "pontos_fortes": ["..."], "melhorar": ["até 3"], "resposta_modelo": {{"pergunta": "a pergunta mais importante", "resposta": "como um candidato excelente responderia, em 5-8 linhas"}},
 "veredito": "avançaria para a próxima fase? sim/talvez/não + 1 frase"}}"""


def abandonar() -> Sessao | None:
    """Fecha a sessão aberta sem feedback (inatividade, /sair ou outro modo começou). Devolve a sessão fechada."""
    s = ativa()
    if s is not None:
        s.encerrada_em = datetime.now().isoformat(timespec="seconds")
        _gravar(s)
    return s


def encerrar(**extras: Any) -> tuple[Sessao, str]:
    s = ativa()
    if s is None:
        raise EntrevistaInvalida("nenhuma entrevista ativa — comece com /entrevista")
    s.encerrada_em = datetime.now().isoformat(timespec="seconds")
    cfg = config()
    met = metricas(s)
    fb: dict[str, Any] = {"metricas": met, "origem": "regras"}
    if met["respostas"] >= 2:
        conversa = "\n".join(f"{'ENTREVISTADOR' if m['papel'] == 'entrevistador' else 'CANDIDATO'}: {m['texto']}" for m in s.mensagens)
        try:
            r = cerebro.perguntar(PEDIDO.format(cargo=cfg["cargos"][s.cargo]["nome"], metricas=json.dumps(met, ensure_ascii=False),
                                                rubrica="; ".join(f"{k} = {v['nome']}: {v['descricao']}" for k, v in cfg["rubrica"].items()),
                                                conversa=conversa[-15000:]),
                                  sistema="Você avalia candidatos do mercado financeiro. Responda só JSON válido.", temperatura=0.2,
                                  max_tokens=3000, response_format={"type": "json_object"}, **extras)
            b = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.texto.strip())
            fb.update(json.loads(b[b.find("{"):b.rfind("}") + 1]))
            fb["origem"] = "ia"
        except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError) as e:
            logging.warning("feedback da entrevista sem IA (%s)", type(e).__name__)
    soma = pesos = 0.0
    for k, v in cfg["rubrica"].items():
        try:
            nota = max(0.0, min(10.0, float(((fb.get("criterios") or {}).get(k) or {}).get("nota"))))
        except (TypeError, ValueError):
            continue
        soma, pesos = soma + nota * v["peso"], pesos + v["peso"]
    fb["nota_final"] = round(soma / pesos, 1) if pesos else None
    s.feedback = fb
    _gravar(s)
    return s, texto_feedback(s)


def texto_feedback(s: Sessao) -> str:
    cfg, fb = config(), s.feedback or {}
    met = fb.get("metricas", {})
    linhas = [f"📋 Feedback da entrevista #{s.id} — {cfg['cargos'][s.cargo]['nome']}"]
    if fb.get("nota_final") is not None:
        linhas.append(f"Nota geral: {fb['nota_final']:.1f}/10".replace(".", ","))
    if fb.get("veredito"):
        linhas.append(f"Veredito: {fb['veredito']}")
    for k, v in cfg["rubrica"].items():
        c = (fb.get("criterios") or {}).get(k) or {}
        if c.get("nota") is not None:
            linhas.append(f"• {v['nome']}: {float(c['nota']):.0f}/10 — {c.get('melhoria') or c.get('evidencia') or ''}".rstrip(" —"))
    linhas += ["", "Números (calculados):",
               f"• {met.get('respostas', 0)} respostas, média de {met.get('palavras_media', 0):.0f} palavras · "
               f"{met.get('com_numeros_pct', 0):.0f}% com números · {met.get('estruturadas', 0)} estruturadas · "
               f"{met.get('fala_de_risco', 0)} falando de risco/premissas"]
    if fb.get("pontos_fortes"):
        linhas += ["", "Mandou bem:"] + [f"• {x}" for x in fb["pontos_fortes"][:3]]
    if fb.get("melhorar"):
        linhas += ["", "Para a próxima:"] + [f"• {x}" for x in fb["melhorar"][:3]]
    rm = fb.get("resposta_modelo") or {}
    if rm.get("resposta"):
        linhas += ["", f"Resposta-modelo para “{rm.get('pergunta', '')}”:", rm["resposta"],
                   "(números da resposta-modelo são ilustrativos, escritos pela IA — confira com dados antes de usar)"]
    if fb.get("origem") == "regras":
        linhas += ["", "⚠️ Sem IA no momento (ou respostas de menos): só os números calculados."]
    return "\n".join(linhas)
