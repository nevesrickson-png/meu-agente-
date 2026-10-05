"""Pautas e peças de conteúdo (roteiro de reels/YouTube, carrossel, fio, artigo) a partir dos insumos com fonte.

O modelo escreve usando só os fatos numerados (marcando [n]); a revisão (`revisao.py`) confere compliance e números,
põe créditos e disclaimer. Alerta grave de compliance → uma reescrita automática. Sem modelo: pautas por regras."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quiron.nucleo import cerebro
from quiron.nucleo.config import pasta_dados
from quiron.servicos.conteudo import ideias, insumos, revisao

SISTEMA = ("Você é roteirista de conteúdo de finanças pessoais para um assessor de investimentos brasileiro. Regras: use SÓ os "
           "fatos numerados fornecidos e marque cada fato usado com [n]; nunca invente número, data ou notícia; nada de promessa "
           "de rentabilidade, 'sem risco' ou certezas sobre o futuro; rentabilidade passada só com a ressalva; sem recomendação "
           "de compra de ativo específico; sem nomes de clientes. Português do Brasil.")


def _json(texto: str) -> Any:
    b = re.sub(r"^```(?:json)?\s*|\s*```$", "", (texto or "").strip())
    ini = min([i for i in (b.find("{"), b.find("[")) if i >= 0], default=0)
    fim = max(b.rfind("}"), b.rfind("]"))
    return json.loads(b[ini:fim + 1])


# ---------------------------------------------------------------- pautas
@dataclass
class Pauta:
    titulo: str
    gancho: str
    angulo: str
    formato: str
    por_que_agora: str
    fontes: list[str] = field(default_factory=list)

    def descrever(self, n: int) -> str:
        return (f"{n}. {self.titulo} [{self.formato}]\n   Gancho: {self.gancho}\n   Ângulo: {self.angulo}\n   Por que agora: {self.por_que_agora}"
                + (f"\n   Fontes: {' · '.join(self.fontes)}" if self.fontes else ""))


PEDIDO_PAUTAS = """Público: {publico}. Tom: {tom}. Formatos possíveis: {formatos}.
{foco}
Fatos disponíveis (use os números entre colchetes):
{fatos}

Proponha {n} pautas diferentes entre si, úteis para o público, ligadas aos fatos. Responda SÓ JSON:
{{"pautas": [{{"titulo": "até 70 caracteres, sem clickbait enganoso", "gancho": "1 frase de abertura", "angulo": "o que o público aprende",
  "formato": um de {formatos_ids}, "por_que_agora": "1 frase ligada a um fato", "fatos": [números dos fatos usados]}}]}}"""


def _pautas_por_regras(itens: list[insumos.Insumo], n: int) -> list[Pauta]:
    pautas = []
    for i in [x for x in itens if x.tipo in {"norma", "agenda", "noticia"}][:n]:
        base = re.sub(r"^(Manchete|Norma/projeto|Agenda):\s*", "", i.texto).split(" — ")[0]
        pautas.append(Pauta(f"O que muda para o seu dinheiro: {base[:50]}", f"Você viu que {base[:80].lower()}?",
                            "explicar o fato e o impacto prático no bolso do investidor", "carrossel", "assunto da semana", [i.credito]))
    return pautas


def gerar_pautas(tema: str = "", n: int = 5, itens: list[insumos.Insumo] | None = None, **extras: Any) -> tuple[list[Pauta], str]:
    cfg = revisao.config()
    itens = itens if itens is not None else insumos.coletar(tema)
    if not itens:
        return [], "Sem insumos agora (notícias, Banco Central, radar e biblioteca indisponíveis)."
    try:
        r = cerebro.perguntar(PEDIDO_PAUTAS.format(publico=cfg["publico"], tom=cfg["tom"], formatos=", ".join(v["nome"] for v in cfg["formatos"].values()),
                                                   formatos_ids=list(cfg["formatos"]), foco=f"Tema pedido: {tema}." if tema else "Tema livre.",
                                                   fatos=insumos.listar_para_modelo(itens), n=n),
                              sistema=SISTEMA, temperatura=0.6, max_tokens=3000, response_format={"type": "json_object"}, **extras)
        d = _json(r.texto)
        bruto = d if isinstance(d, list) else (d.get("pautas") or next((v for v in d.values() if isinstance(v, list)), []))
        pautas = []
        por_id = {i.id: i for i in itens}
        for p in bruto[:n]:
            usados = [por_id[int(x)] for x in p.get("fatos", []) if str(x).isdigit() and int(x) in por_id]
            formato = p.get("formato") if p.get("formato") in cfg["formatos"] else "carrossel"
            limpo = lambda x: revisao.RE_MARCA.sub("", str(x or "")).strip()  # noqa: E731
            pautas.append(Pauta(limpo(p.get("titulo"))[:90], limpo(p.get("gancho")), limpo(p.get("angulo")), formato,
                                limpo(p.get("por_que_agora")), revisao.creditos(usados)))
        if pautas:
            return pautas, "ia"
    except (cerebro.CerebroIndisponivel, ValueError, json.JSONDecodeError, TypeError, AttributeError) as e:
        logging.warning("pautas sem IA (%s)", type(e).__name__)
    return _pautas_por_regras(itens, n), "regras"


def texto_pautas(pautas: list[Pauta], origem: str) -> str:
    if not pautas:
        return "Não consegui montar pautas agora."
    return ("🗞️ Pautas sugeridas" + (" (por regras, sem IA)" if origem == "regras" else "") + "\n\n"
            + "\n\n".join(p.descrever(i) for i, p in enumerate(pautas, 1))
            + "\n\nGuardar: /ideia salvar <nº> · Escrever: /roteiro <formato> <tema>")


# ---------------------------------------------------------------- peça (roteiro, carrossel, fio, artigo)
PEDIDO_PECA = """Formato: {formato_nome}. Estrutura: {estrutura}. Limite: ~{limite} palavras.
Público: {publico}. Tom: {tom}.
Tema: {tema}
Fatos disponíveis (marque [n] em cada fato usado; use pelo menos 2 fatos se houver):
{fatos}
{correcao}
Responda SÓ JSON: {{"titulo": "...", "texto": "a peça completa no formato pedido, com as marcas [n]; separe slides/posts/blocos com \\n\\n"}}"""


@dataclass
class Peca:
    titulo: str
    formato: str
    revisado: revisao.Revisado
    arquivo: str = ""
    ideia: int | None = None
    tentativas: int = 1

    def entrega(self) -> str:
        return self.revisado.final(self.titulo) + "\n\n———\nPara você (não publicar):\n" + self.revisado.notas() + \
            (f"\nGuardado como ideia #{self.ideia} (rascunho) em {self.arquivo}" if self.arquivo else "")


def gerar_peca(tema: str, formato: str = "carrossel", itens: list[insumos.Insumo] | None = None, **extras: Any) -> Peca:
    cfg = revisao.config()
    if formato not in cfg["formatos"]:
        raise ValueError(f"formato: {', '.join(cfg['formatos'])}")
    tema = (tema or "").strip()
    ideia_id = None
    if m := re.fullmatch(r"#?(\d+)", tema):  # roteiro a partir de uma ideia do banco
        ideia_id = int(m[1])
        i = ideias.obter(ideia_id)
        tema = f"{i.titulo}. {i.angulo}".strip()
    if len(tema) < 4:
        raise ValueError("diga o tema (ex.: /roteiro carrossel Tesouro Selic x poupança)")
    itens = itens if itens is not None else insumos.coletar(tema)
    f = cfg["formatos"][formato]
    correcao, tentativas, rev, titulo = "", 0, None, tema[:80]
    while tentativas < 2:
        tentativas += 1
        r = cerebro.perguntar(PEDIDO_PECA.format(formato_nome=f["nome"], estrutura=f["estrutura"], limite=f["limite_palavras"],
                                                 publico=cfg["publico"], tom=cfg["tom"], tema=tema,
                                                 fatos=insumos.listar_para_modelo(itens) or "(nenhum fato disponível: escreva sem números)",
                                                 correcao=correcao),
                              sistema=SISTEMA, temperatura=0.5, max_tokens=4000, response_format={"type": "json_object"}, **extras)
        d = _json(r.texto)
        titulo, corpo = str(d.get("titulo") or tema)[:120], str(d.get("texto") or "")
        rev = revisao.revisar(corpo, itens)
        if not (rev.graves or rev.numeros_sem_fonte):
            break
        problemas = rev.alertas + [f"número sem fonte: {x}" for x in rev.numeros_sem_fonte]
        correcao = "CORRIJA estes problemas da versão anterior (reescreva tudo):\n- " + "\n- ".join(problemas)
    peca = Peca(titulo, formato, rev, tentativas=tentativas)
    salvar(peca, ideia_id)
    return peca


def salvar(peca: Peca, ideia_id: int | None = None) -> None:
    pasta = pasta_dados() / "conteudo"
    pasta.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", revisao.compliance._norm(peca.titulo))[:50].strip("-")
    arq = pasta / f"{datetime.now():%Y%m%d-%H%M%S}-{peca.formato}-{slug}.md"
    arq.write_text(peca.entrega(), encoding="utf-8")
    if ideia_id:
        ideias.atualizar(ideia_id, situacao="rascunho", arquivo=str(arq), formato=peca.formato)
        peca.ideia = ideia_id
    else:
        peca.ideia = ideias.criar(peca.titulo, formato=peca.formato, fontes=peca.revisado.creditos, situacao="rascunho").id
        ideias.atualizar(peca.ideia, arquivo=str(arq))
    peca.arquivo = str(arq)


def conferir_texto(texto: str, tema: str = "") -> str:
    """Para um texto escrito pelo próprio Rickson: compliance, números e o disclaimer a acrescentar."""
    itens = insumos.coletar(tema, com_livros=False) if tema else []
    rev = revisao.revisar(texto, itens)
    partes = [rev.notas(), f"Disclaimer sugerido: {rev.disclaimer}"]
    if not tema and rev.numeros_sem_fonte:
        partes.append("(Sem tema informado não comparei os números com as fontes; diga o tema para conferir.)")
    return "\n\n".join(partes)


def caminho_rascunhos() -> Path:
    return pasta_dados() / "conteudo"
