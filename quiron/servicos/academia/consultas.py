"""Respostas em texto da Academia (usadas pelo MCP `quiron-academia`, pelo agente e pelo Claude Code)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


from quiron.nucleo.config import ler_yaml_arquivo
from quiron.nucleo.config import PASTA_CONFIG
from quiron.servicos import areas
from quiron.servicos.academia import diagnostico, edital, estudo
from quiron.servicos.academia.banco import LETRAS, Banco
from quiron.servicos.academia.estudo import Filtro


def trilha(banco: Banco | None = None) -> str:
    banco = banco or Banco()
    dados = ler_yaml_arquivo((PASTA_CONFIG / "trilha_certificacoes.yaml"))
    linhas = [f"🎓 Trilha de certificações (ritmo: {dados.get('ritmo_semanal_horas')} h/semana)"]
    for i, c in enumerate(dados["trilha"], 1):
        marca = "▶" if i == 1 else " "
        estado = "edital mapeado" if edital.tem_programa(c["id"]) else "edital a mapear"
        linhas.append(f"{marca} {i}. {c['id']} ({c['entidade']}) — {estado}" + (f" · {c['motivo']}" if c.get("motivo") else ""))
    linhas += ["", diagnostico.painel_geral(banco, estudo.area_ativa(banco))]
    return "\n".join(linhas)


def listar_areas() -> str:
    linhas = ["Áreas de conhecimento (pasta no acervo · programa de estudo):"]
    for a in areas.listar():
        prog = "programa mapeado" if edital.tem_programa(a.id) else "sem programa (questões gerais)"
        linhas.append(f"- {a.id} — {a.nome} [{a.tipo}] · {prog}" + (f" · {a.descricao}" if a.descricao else ""))
    return "\n".join(linhas)


def _area(area: str | None, banco: Banco) -> str:
    a = areas.obter(area) if area else None
    if area and not a:
        achada, _ = areas.reconhecer(area)
        a = achada
    return a.id if a else estudo.area_ativa(banco)


def _id_area(nome: str) -> str:
    a = areas.obter(nome) or areas.reconhecer(nome)[0]
    return a.id if a else nome.upper()


def mapa_edital(cert: str = "CFP", modulo: int | None = None, busca: str | None = None) -> str:
    cert = _id_area(cert)
    dados = edital.carregar(cert)
    nome = estudo.nome_area(cert)
    if busca:
        achados = edital.buscar(busca, cert, 12)
        if not achados:
            return f"Nada no programa de {nome} parecido com “{busca}”."
        return "\n".join([f"Tópicos do programa de {nome} para “{busca}”:"] +
                         [f"- {t['codigo']} {t['titulo']} (módulo {t['modulo']})" for t in achados])
    fonte = f"\n\n📚 {dados['fonte']}" + (f" (verificado em {dados['verificado_em']})" if dados.get("verificado_em") else "")
    if modulo:
        m = next((m for m in dados["modulos"] if m["numero"] == modulo), None)
        if not m:
            return f"Módulo {modulo} não existe."
        extra = f", ~{m['questoes_estimadas']} questões, {m.get('tempo_min', '?')} min" if m.get("questoes_estimadas") else ""
        linhas = [f"{nome} · Módulo {m['numero']} — {m['titulo']} (peso {m['peso']}%{extra})"]
        linhas += [f"{'  ' * (t['codigo'].count('.') - 1)}- {t['codigo']} {t['titulo']}"
                   for t in m["topicos"] if t["codigo"].count(".") <= 2]
        return "\n".join(linhas) + fonte
    p = dados.get("prova") or {}
    if p:
        linhas = [f"Exame {cert} ({dados['entidade']}): {p.get('questoes')} questões de {p.get('alternativas')} alternativas.",
                  f"Aprovação: {p.get('aprovacao_completa')} · modular: {p.get('aprovacao_modular')}.",
                  f"Legislação: {p.get('legislacao')}.", "Módulos:"]
    else:
        linhas = [f"Programa de {nome} ({cert}) — módulos:"]
    linhas += [f"- M{m['numero']} {m['titulo']} — peso {m['peso']}%" +
               (f", ~{m['questoes_estimadas']} questões, {m.get('tempo_min')} min" if m.get("questoes_estimadas") else "")
               for m in dados["modulos"]]
    if p.get("exames_2026"):
        linhas.append("Exames 2026: " + "; ".join(p["exames_2026"]))
    return "\n".join(linhas) + fonte


def detalhar_topico(codigo: str, cert: str = "CFP", banco: Banco | None = None) -> str:
    cert = (areas.obter(cert).id if areas.obter(cert) else cert)
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
               banco: Banco | None = None, area: str | None = None) -> str:
    banco = banco or Banco()
    area_id = _area(area, banco)
    if area:
        estudo.definir_area_ativa(banco, area_id)
    feito = [f"área ativa {estudo.nome_area(area_id)}"] if area else []
    if data_prova:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", data_prova.strip())
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else date.fromisoformat(data_prova.strip())
        except (ValueError, AttributeError):
            return "Data inválida: use dd/mm/aaaa."
        banco.definir_pref(f"data_prova:{area_id}", d.isoformat())
        feito.append(f"prova de {estudo.nome_area(area_id)} em {d:%d/%m/%Y}")
    if horas_semana:
        h = max(1.0, min(20.0, float(horas_semana)))
        banco.definir_pref("horas_semana", h)
        feito.append(f"{h:g} h por semana")
    if dias:
        validos = [d.lower() for d in dias if d.lower() in diagnostico.DIAS]
        if validos:
            banco.definir_pref("dias_estudo", validos)
            feito.append("dias: " + ", ".join(validos))
    return ("Anotado: " + "; ".join(feito) + ".") if feito else "Nada mudou (informe área, data_prova, horas_semana ou dias)."


def plano(horas: float | None = None, banco: Banco | None = None, area: str | None = None) -> str:
    banco = banco or Banco()
    area_id = _area(area, banco)
    if horas:
        banco.definir_pref("horas_semana", max(1.0, min(20.0, float(horas))))
    h = float(banco.pref("horas_semana", 5))
    mods = diagnostico.diagnosticar(banco, area_id)
    prova = diagnostico.data_prova(banco, area_id)
    cartoes = len(banco.cards_vencidos(None, 999))
    return diagnostico.texto_plano(mods, diagnostico.plano_semana(mods, h, banco.pref("dias_estudo"), cartoes, prova),
                                   h, cartoes, prova)


def diagnostico_texto(area: str | None = None, banco: Banco | None = None) -> str:
    banco = banco or Banco()
    return diagnostico.texto_diagnostico(diagnostico.diagnosticar(banco, _area(area, banco)))


def gerar(alvo: str = "", quantidade: int = 4, banco: Banco | None = None) -> str:
    banco = banco or Banco()
    f = Filtro.ler(alvo, estudo.area_ativa(banco))
    if not f.modulo:
        f = Filtro(f.area, modulo=estudo._modulo_por_prioridade(banco, f.area))  # noqa: SLF001
    ids = estudo.gerar_lote(banco, f.modulo, max(1, min(12, quantidade)), f.topico, f.area)
    total = sum(banco.contar_questoes(f.area).values())
    return (f"{len(ids)} questão(ões) nova(s) em {f.descrever()} (aprovadas pelo revisor). Banco da área: {total} questões."
            if ids else "Nenhuma questão aprovada agora (limite dos modelos grátis ou o revisor recusou). Tente mais tarde.")


def questoes_texto(alvo: str = "", n: int = 3, banco: Banco | None = None) -> str:
    """Questões para responder na conversa, com o gabarito separado no fim."""
    banco = banco or Banco()
    f = Filtro.ler(alvo, estudo.area_ativa(banco))
    qs = banco.escolher_questoes(f.area, max(1, min(10, n)), modulo=f.modulo, topico=f.topico)
    if len(qs) < n:
        modulo = f.modulo or estudo._modulo_por_prioridade(banco, f.area)  # noqa: SLF001
        estudo.gerar_lote(banco, modulo, n - len(qs), f.topico, f.area)
        qs = banco.escolher_questoes(f.area, n, modulo=f.modulo, topico=f.topico)
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
    dados: dict[str, Any] = ler_yaml_arquivo(arq)
    itens = [i for i in dados["itens"] if not cert or cert.upper() in [c.upper() for c in i.get("certificacoes", [])]]
    linhas = [f"Materiais gratuitos (verificados em {dados.get('verificado_em')}):"]
    for i in itens:
        linhas.append(f"- {i['nome']} — {i.get('fonte', '')} · {', '.join(i.get('certificacoes', []))} · "
                      f"{i.get('situacao', '')}\n  {i['url']}")
    return "\n".join(linhas)


def agora() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M")
