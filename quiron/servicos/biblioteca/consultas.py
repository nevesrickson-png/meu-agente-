"""Consultas à biblioteca, já formatadas em Markdown (usadas pelo MCP e, depois, pelo Terminal).

As ferramentas devolvem TRECHOS com citação; quem redige a explicação é o agente (Claude Code, Hermes...),
seguindo as skills em `agente/skills/`. Assim a resposta sempre se apoia no texto dos livros.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from quiron.servicos.biblioteca.blocos import Guia, carregar_guia
from quiron.servicos.biblioteca.fichas import texto_cobertura, texto_ficha
from quiron.servicos.biblioteca.indice import Indice, Resultado
from quiron.servicos.biblioteca.trechos import chave

VAZIA = "A biblioteca está vazia. Coloque livros em `biblioteca/entrada/` e rode a ferramenta `ingerir`."


def _bloco_txt(guia: Guia, meta: dict) -> str:
    return f" · {guia.nome(int(meta['bloco']))}" if int(meta.get("bloco") or 0) else ""


def _formatar(resultados: list[Resultado], guia: Guia, limite_texto: int = 900) -> str:
    saida = []
    for i, r in enumerate(resultados, 1):
        texto = r.texto if len(r.texto) <= limite_texto else r.texto[:limite_texto].rsplit(" ", 1)[0] + " […]"
        saida.append(f"**[{i}]** {r.citacao}{_bloco_txt(guia, r.meta)} · semelhança {r.semelhanca:.2f}\n> {texto}")
    return "\n\n".join(saida)


def _resolver_livro(indice: Indice, livro: str | None) -> tuple[str | None, str | None]:
    if not livro:
        return None, None
    info = indice.achar_livro(livro)
    return (info["id"], None) if info else (None, f"Livro não encontrado: {livro}. Use `listar_livros`.")


def _id_area(area: str | None) -> str | None:
    if not area:
        return None
    from quiron.servicos import areas

    a = areas.obter(area) or areas.reconhecer(area)[0]
    return a.id if a else area.upper()


def buscar(pergunta: str, n: int = 6, livro: str | None = None, autor: str | None = None, bloco: int | None = None,
           indice: Indice | None = None, area: str | None = None) -> str:
    indice = indice or Indice()
    if indice.total_trechos() == 0:
        return VAZIA
    livro_id, erro = _resolver_livro(indice, livro)
    if erro:
        return erro
    guia = carregar_guia()
    res = indice.buscar(pergunta, n, livro_id=livro_id, autor=autor, bloco=bloco, area=_id_area(area))
    if not res:
        return f"Nada encontrado para: {pergunta}" + (f" na área {area} (tente sem a área)" if area else "")
    return f"## Trechos para: {pergunta}\n\n{_formatar(res, guia)}\n\n_Cite as fontes no formato 📚 Livro — Autor, cap. X._"


def estudar_tema(tema: str, n: int = 12, indice: Indice | None = None, area: str | None = None) -> str:
    """Trechos agrupados por livro + blocos do guia em que o tema aparece."""
    indice = indice or Indice()
    if indice.total_trechos() == 0:
        return VAZIA
    guia = carregar_guia()
    res = [r for r in indice.buscar(tema, n, area=_id_area(area)) if r.semelhanca > 0.05]
    if not res:
        return f"Nada encontrado sobre: {tema}"
    por_livro: dict[str, list[Resultado]] = defaultdict(list)
    blocos: dict[str, int] = defaultdict(int)
    for r in res:
        por_livro[f"{r.meta['titulo']} — {r.meta['autor']}"].append(r)
        if int(r.meta.get("bloco") or 0):
            blocos[guia.nome(int(r.meta["bloco"]))] += 1
    partes = [f"# Estudo: {tema}"]
    if blocos:
        partes.append("**Blocos do guia relacionados:** " + ", ".join(f"{b} ({q})" for b, q in sorted(blocos.items(), key=lambda x: -x[1])))
    for livro, lista in por_livro.items():
        caps = sorted({r.meta["capitulo"] for r in lista if r.meta.get("capitulo")})
        partes.append(f"## {livro}" + (f"\nCapítulos para ler: {'; '.join(caps)}" if caps else ""))
        partes.append(_formatar(lista, guia))
    return "\n\n".join(partes)


def debate_autores(tema: str, autores: list[str] | None = None, por_autor: int = 2, indice: Indice | None = None) -> str:
    """O que cada autor da biblioteca diz sobre o tema (base para a mesa-redonda)."""
    indice = indice or Indice()
    if indice.total_trechos() == 0:
        return VAZIA
    guia = carregar_guia()
    todos = sorted({l["autor"] for l in indice.catalogo().values()})
    if autores:
        pedidos = {chave(a) for a in autores}
        todos = [a for a in todos if chave(a) in pedidos or any(p in chave(a) for p in pedidos)]
    partes = [f"# Mesa-redonda: {tema}"]
    sem_material = []
    for autor in todos:
        res = [r for r in indice.buscar(tema, por_autor, autor=autor) if r.semelhanca > 0.1]
        if res:
            partes.append(f"## {autor}\n\n{_formatar(res, guia, 700)}")
        else:
            sem_material.append(autor)
    if len(partes) == 1:
        return f"Nenhum autor da biblioteca trata de: {tema}"
    if sem_material:
        partes.append("_Sem trechos relevantes: " + ", ".join(sem_material) + "_")
    return "\n\n".join(partes)


def mapa_autor(autor: str, indice: Indice | None = None) -> str:
    indice = indice or Indice()
    guia = carregar_guia()
    k = chave(autor)
    livros = [l for l in indice.catalogo().values() if k in chave(l["autor"])]
    if not livros:
        return f"Nenhum livro de {autor} na biblioteca."
    partes = [f"# Mapa do autor: {livros[0]['autor']}"]
    blocos: dict[int, int] = defaultdict(int)
    for l in livros:
        partes.append(f"## {l['titulo']} ({l['paginas'] or '—'} p., {l['trechos']} trechos)")
        if l.get("capitulos"):
            partes.append("Capítulos: " + "; ".join(l["capitulos"][:30]))
        for b, q in l["blocos"].items():
            if b != "0":
                blocos[int(b)] += q
    if blocos:
        partes.append("## Temas (blocos do guia) em que mais escreve")
        partes += [f"- {guia.nome(b)}: {q} trechos" for b, q in sorted(blocos.items(), key=lambda x: -x[1])]
    return "\n\n".join(partes)


def ficha(livro: str, indice: Indice | None = None) -> str:
    indice = indice or Indice()
    info = indice.achar_livro(livro)
    if not info:
        return f"Livro não encontrado: {livro}. Use `listar_livros`."
    return texto_ficha(info, carregar_guia())


def conectar_conceitos(conceito_a: str, conceito_b: str, n: int = 6, indice: Indice | None = None) -> str:
    """Trechos que ligam dois conceitos (aparecem juntos) + a melhor explicação de cada um."""
    indice = indice or Indice()
    if indice.total_trechos() == 0:
        return VAZIA
    guia = carregar_guia()

    def menciona(texto: str, conceito: str) -> bool:
        raiz = [p[:6] for p in re.findall(r"\w+", chave(conceito)) if len(p) > 3] or [chave(conceito)]
        t = chave(texto)
        return all(r in t for r in raiz)

    juntos = [r for r in indice.buscar(f"{conceito_a} {conceito_b}", n * 3) if menciona(r.texto, conceito_a) and menciona(r.texto, conceito_b)][:n]
    partes = [f"# Conexão: {conceito_a} ↔ {conceito_b}"]
    partes.append("## Trechos que tratam dos dois juntos\n\n" + (_formatar(juntos, guia) if juntos else "_Nenhum trecho fala dos dois ao mesmo tempo._"))
    for c in (conceito_a, conceito_b):
        partes.append(f"## {c}\n\n" + _formatar(indice.buscar(c, 2), guia, 600))
    return "\n\n".join(partes)


def cobertura(indice: Indice | None = None) -> str:
    indice = indice or Indice()
    return "# Cobertura dos 22 blocos\n\n" + texto_cobertura(indice.catalogo(), carregar_guia())


def listar_livros(indice: Indice | None = None) -> str:
    indice = indice or Indice()
    cat = indice.catalogo()
    if not cat:
        return VAZIA
    linhas = ["| Livro | Autor | Páginas | Trechos | Id |", "|---|---|---:|---:|---|"]
    linhas += [f"| {l['titulo']} | {l['autor']} | {l['paginas'] or '—'} | {l['trechos']} | `{l['id']}` |" for l in sorted(cat.values(), key=lambda x: x["titulo"])]
    return "\n".join(linhas)


def pilula(bloco: int | None = None, dia: date | None = None, indice: Indice | None = None) -> str:
    """Um trecho do dia (escolha fixa por data) para virar a pílula diária de estudo."""
    indice = indice or Indice()
    if indice.total_trechos() == 0:
        return VAZIA
    dados = indice.todos(where={"bloco": int(bloco)} if bloco else None)
    if not dados["ids"]:
        return f"Nenhum trecho no bloco {bloco}."
    dia = dia or date.today()
    # trechos muito curtos rendem pílulas fracas: prefere os maiores
    candidatos = sorted(range(len(dados["ids"])), key=lambda i: (-len(dados["documents"][i]), dados["ids"][i]))
    candidatos = candidatos[: max(1, len(candidatos) * 2 // 3)]
    i = candidatos[dia.toordinal() % len(candidatos)]
    meta, texto = dados["metadatas"][i], dados["documents"][i]
    guia = carregar_guia()
    from quiron.servicos.biblioteca.indice import citacao

    return f"# Pílula de {dia:%d/%m/%Y}\n{citacao(meta)}{_bloco_txt(guia, meta)}\n\n> {texto}"
