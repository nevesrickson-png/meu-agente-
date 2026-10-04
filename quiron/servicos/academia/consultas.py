"""Respostas em texto da Academia (usadas pelo MCP `quiron-academia`, pelo agente e pelo Claude Code)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import yaml

from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos.academia import diagnostico, edital, estudo, gerador
from quiron.servicos.academia.banco import LETRAS, Banco
from quiron.servicos.academia.estudo import CERT, Filtro


def trilha(banco: Banco | None = None) -> str:
    dados = yaml.safe_load((PASTA_CONFIG / "trilha_certificacoes.yaml").read_text(encoding="utf-8"))
    mapeados = {p.stem for p in edital.PASTA_EDITAIS.glob("*.yaml")}
    linhas = [f"🎓 Trilha de certificações (ritmo: {dados.get('ritmo_semanal_horas')} h/semana)"]
    for i, c in enumerate(dados["trilha"], 1):
        marca = "▶" if i == 1 else " "
        estado = "edital mapeado" if c["id"] in mapeados else "edital a mapear"
        linhas.append(f"{marca} {i}. {c['id']} ({c['entidade']}) — {estado}" + (f" · {c['motivo']}" if c.get("motivo") else ""))
    linhas += ["", diagnostico.painel(banco or Banco(), CERT)]
    return "\n".join(linhas)


def mapa_edital(cert: str = "CFP", modulo: int | None = None, busca: str | None = None) -> str:
    dados = edital.carregar(cert)
    if busca:
        achados = edital.buscar(busca, cert, 12)
        if not achados:
            return f"Nada no edital do {cert} parecido com “{busca}”."
        return "\n".join([f"Tópicos do edital {cert} para “{busca}”:"] +
                         [f"- {t['codigo']} {t['titulo']} (módulo {t['modulo']})" for t in achados])
    if modulo:
        m = next((m for m in dados["modulos"] if m["numero"] == modulo), None)
        if not m:
            return f"Módulo {modulo} não existe."
        linhas = [f"Módulo {m['numero']} — {m['titulo']} (peso {m['peso']}%, ~{m.get('questoes_estimadas', '?')} questões, "
                  f"{m.get('tempo_min', '?')} min)"]
        linhas += [f"{'  ' * (t['codigo'].count('.') - 1)}- {t['codigo']} {t['titulo']}"
                   for t in m["topicos"] if t["codigo"].count(".") <= 2]
        return "\n".join(linhas) + f"\n\n📚 {dados['fonte']} (verificado em {dados['verificado_em']})"
    p = dados.get("prova", {})
    linhas = [f"Exame {cert} ({dados['entidade']}): {p.get('questoes')} questões de {p.get('alternativas')} alternativas.",
              f"Aprovação: {p.get('aprovacao_completa')} · modular: {p.get('aprovacao_modular')}.",
              f"Legislação: {p.get('legislacao')}.", "Módulos:"]
    linhas += [f"- M{m['numero']} {m['titulo']} — peso {m['peso']}%, ~{m.get('questoes_estimadas')} questões, {m.get('tempo_min')} min"
               for m in dados["modulos"]]
    if p.get("exames_2026"):
        linhas.append("Exames 2026: " + "; ".join(p["exames_2026"]))
    return "\n".join(linhas) + f"\n\n📚 {dados['fonte']} (verificado em {dados['verificado_em']})"


def detalhar_topico(codigo: str, cert: str = "CFP", banco: Banco | None = None) -> str:
    t = edital.topico(codigo, cert)
    if not t:
        return f"Tópico {codigo} não existe no edital do {cert}."
    banco = banco or Banco()
    filhos = edital.filhos(codigo, cert)
    resp = [r for r in banco.desempenho(cert) if r["topico"] == codigo or r["topico"].startswith(codigo + ".")]
    linhas = [f"{t['codigo']} {t['titulo']} — módulo {t['modulo']} ({t['modulo_titulo']})"]
    if t.get("itens"):
        linhas.append("Itens: " + "; ".join(t["itens"]))
    linhas += [f"{'  ' * (f['codigo'].count('.') - codigo.count('.') - 1)}- {f['codigo']} {f['titulo']}" for f in filhos[:40]]
    linhas.append(f"Seu desempenho aqui: {sum(r['acertou'] for r in resp)}/{len(resp)}" if resp else "Ainda não praticado.")
    return "\n".join(linhas)


def configurar(data_prova: str | None = None, horas_semana: float | None = None, dias: list[str] | None = None,
               banco: Banco | None = None) -> str:
    banco = banco or Banco()
    feito = []
    if data_prova:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", data_prova.strip())
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else date.fromisoformat(data_prova.strip())
        except (ValueError, AttributeError):
            return "Data inválida: use dd/mm/aaaa."
        banco.definir_pref("data_prova", d.isoformat())
        feito.append(f"prova em {d:%d/%m/%Y}")
    if horas_semana:
        h = max(1.0, min(20.0, float(horas_semana)))
        banco.definir_pref("horas_semana", h)
        feito.append(f"{h:g} h por semana")
    if dias:
        validos = [d.lower() for d in dias if d.lower() in diagnostico.DIAS]
        if validos:
            banco.definir_pref("dias_estudo", validos)
            feito.append("dias: " + ", ".join(validos))
    return ("Anotado: " + "; ".join(feito) + ".") if feito else "Nada mudou (informe data_prova, horas_semana ou dias)."


def plano(horas: float | None = None, banco: Banco | None = None) -> str:
    banco = banco or Banco()
    if horas:
        banco.definir_pref("horas_semana", max(1.0, min(20.0, float(horas))))
    h = float(banco.pref("horas_semana", 5))
    mods = diagnostico.diagnosticar(banco, CERT)
    prova = banco.pref("data_prova")
    data_prova = date.fromisoformat(prova) if prova else None
    cartoes = len(banco.cards_vencidos(CERT, 999))
    return diagnostico.texto_plano(mods, diagnostico.plano_semana(mods, h, banco.pref("dias_estudo"), cartoes, data_prova),
                                   h, cartoes, data_prova)


def gerar(alvo: str = "", quantidade: int = 4, banco: Banco | None = None) -> str:
    banco = banco or Banco()
    f = Filtro.ler(alvo)
    if not f.modulo:
        return "Informe um módulo (1–8), um tópico (ex.: 6.2.1) ou um tema do edital."
    ids = estudo.gerar_lote(banco, f.modulo, max(1, min(12, quantidade)), f.topico)
    total = sum(banco.contar_questoes(CERT).values())
    return (f"{len(ids)} questão(ões) nova(s) em {f.descrever()} (aprovadas pelo revisor). Banco: {total} questões."
            if ids else "Nenhuma questão aprovada agora (limite dos modelos grátis ou o revisor recusou). Tente mais tarde.")


def questoes_texto(alvo: str = "", n: int = 3, banco: Banco | None = None) -> str:
    """Questões para responder na conversa, com o gabarito separado no fim."""
    banco = banco or Banco()
    f = Filtro.ler(alvo)
    qs = banco.escolher_questoes(CERT, max(1, min(10, n)), modulo=f.modulo, topico=f.topico)
    if len(qs) < n and f.modulo:
        estudo.gerar_lote(banco, f.modulo, n - len(qs), f.topico)
        qs = banco.escolher_questoes(CERT, n, modulo=f.modulo, topico=f.topico)
    if not qs:
        return "Ainda não há questões para isso (e não consegui gerar agora)."
    corpo = [f"Q{q.id} · " + q.texto() for q in qs]
    gabarito = [f"Q{q.id}: {q.letra_correta} — {q.explicacao.splitlines()[0][:200]}" for q in qs]
    return ("\n\n".join(corpo) + "\n\n— GABARITO (não mostre antes de o Rickson responder; registre com "
            "registrar_resposta) —\n" + "\n".join(gabarito))


def registrar(questao_id: int, letra: str, banco: Banco | None = None) -> str:
    banco = banco or Banco()
    letra = (letra or "").strip().upper()[:1]
    q = banco.questao(questao_id)
    if not q or letra not in LETRAS:
        return "Questão ou letra inválida."
    certo = banco.responder(questao_id, LETRAS.index(letra), "conversa")
    return (f"{'✅ Certo' if certo else f'❌ Errado (correta: {q.letra_correta})'} — {q.explicacao}")


def materiais(cert: str | None = None) -> str:
    arq = PASTA_CONFIG / "materiais_gratuitos.yaml"
    if not arq.exists():
        return "Catálogo de materiais gratuitos ainda não montado."
    dados: dict[str, Any] = yaml.safe_load(arq.read_text(encoding="utf-8"))
    itens = [i for i in dados["itens"] if not cert or cert.upper() in [c.upper() for c in i.get("certificacoes", [])]]
    linhas = [f"Materiais gratuitos (verificados em {dados.get('verificado_em')}):"]
    for i in itens:
        linhas.append(f"- {i['nome']} — {i.get('fonte', '')} · {', '.join(i.get('certificacoes', []))} · "
                      f"{i.get('situacao', '')}\n  {i['url']}")
    return "\n".join(linhas)


def agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")
