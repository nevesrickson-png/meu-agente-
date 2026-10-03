"""Ficha por livro (ligada aos 22 blocos) e relatório de ingestão e cobertura."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from quiron.servicos.biblioteca.blocos import Guia

if TYPE_CHECKING:
    from quiron.servicos.biblioteca.indice import Indice
    from quiron.servicos.biblioteca.ingestao import Relatorio


def texto_ficha(info: dict, guia: Guia) -> str:
    total = info["trechos"] or 1
    linhas = [
        f"# {info['titulo']}",
        f"**Autor:** {info['autor']}  ",
        f"**Arquivo:** {info['arquivo']} ({info['formato'].upper()}{', com OCR' if info.get('ocr') else ''})  ",
        f"**Páginas:** {info['paginas'] or '—'} · **Trechos indexados:** {info['trechos']}  ",
        f"**Id:** `{info['id']}` · **Ingerido em:** {info['ingerido_em']}",
        "",
        "## Ligação com os 22 blocos do guia",
    ]
    if not guia.blocos:
        linhas.append("_O guia dos 22 blocos ainda não foi preenchido (`config/guia_22_blocos.yaml`)._")
    else:
        linhas += ["| Bloco | Trechos | % do livro |", "|---|---:|---:|"]
        for b in guia.blocos:
            qtd = int(info["blocos"].get(str(b.id), 0))
            if qtd:
                linhas.append(f"| {b.id}. {b.nome} | {qtd} | {qtd / total:.0%} |")
        sem = int(info["blocos"].get("0", 0))
        linhas.append(f"| (sem bloco) | {sem} | {sem / total:.0%} |")
    linhas += ["", "## Capítulos"]
    linhas += [f"- {c}" for c in info.get("capitulos") or []] or ["_Sumário não encontrado no arquivo._"]
    return "\n".join(linhas) + "\n"


def gravar_ficha(info: dict, guia: Guia, indice: "Indice") -> None:
    pasta = indice.raiz / "fichas"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{info['id']}.md").write_text(texto_ficha(info, guia), encoding="utf-8")


def texto_cobertura(catalogo: dict[str, dict], guia: Guia) -> str:
    if not guia.blocos:
        return "O guia dos 22 blocos ainda não foi preenchido (`config/guia_22_blocos.yaml`)."
    linhas = ["| Bloco | Trechos | Livros |", "|---|---:|---|"]
    vazios = []
    for b in guia.blocos:
        por_livro = {l["titulo"]: int(l["blocos"].get(str(b.id), 0)) for l in catalogo.values()}
        total = sum(por_livro.values())
        livros = ", ".join(f"{t} ({q})" for t, q in sorted(por_livro.items(), key=lambda x: -x[1]) if q)
        linhas.append(f"| {b.id}. {b.nome} | {total} | {livros or '—'} |")
        if total == 0:
            vazios.append(f"{b.id}. {b.nome}")
    if vazios:
        linhas += ["", "**Blocos sem material na biblioteca:** " + "; ".join(vazios)]
    return "\n".join(linhas)


def gravar_relatorio(relatorio: "Relatorio", guia: Guia, indice: "Indice") -> None:
    cat = indice.catalogo()
    linhas = [
        "# Relatório de ingestão da biblioteca",
        f"_Gerado em {datetime.now():%d/%m/%Y %H:%M}_",
        "",
        f"**Resultado desta rodada:** {relatorio.resumo()}",
        "",
        "| Arquivo | Situação | Detalhe |",
        "|---|---|---|",
    ]
    linhas += [f"| {l.arquivo} | {l.situacao} | {l.detalhe} |" for l in relatorio.livros]
    linhas += [
        "",
        f"## Biblioteca: {len(cat)} livro(s), {sum(l['trechos'] for l in cat.values())} trechos",
        "",
        "## Cobertura dos 22 blocos",
        texto_cobertura(cat, guia),
    ]
    (indice.raiz / "relatorio_ingestao.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
