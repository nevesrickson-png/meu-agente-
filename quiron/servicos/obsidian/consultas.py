"""Textos prontos do Cérebro para o agente, o bot e o Terminal."""

from __future__ import annotations

from quiron.servicos.obsidian import indice
from quiron.servicos.obsidian import pasta as P

LIMITE = 6000


def detalhe(nota: str) -> dict | None:
    """Nota + ligações (para o Terminal e para o texto do agente)."""
    from quiron.servicos.obsidian import rotina

    rotina.preparar()
    achada = indice.obter(nota)
    if not achada:
        return None
    n, texto = achada
    fm, corpo = P.ler_frontmatter(texto)
    saem, faltam = indice.ligacoes(n)
    return {"caminho": n.caminho, "titulo": n.titulo, "pasta": n.pasta, "tags": n.tags, "alterada": n.alterada,
            "propriedades": {k: v for k, v in fm.items()}, "texto": corpo,
            "cita": [{"titulo": x.titulo, "caminho": x.caminho} for x in saem], "sem_nota": faltam,
            "citada_por": [{"titulo": x.titulo, "caminho": x.caminho} for x in indice.quem_cita(n)],
            "obsidian": P.link_obsidian(n.caminho)}


def texto_nota(nota: str) -> str:
    d = detalhe(nota)
    if not d:
        return f"Não achei a nota “{nota}” no Cérebro. Procure antes com buscar_no_cerebro."
    corpo = d["texto"].strip()
    if len(corpo) > LIMITE:
        corpo = corpo[:LIMITE] + "\n[… nota cortada]"
    partes = [f"# [[{d['titulo']}]] ({d['pasta'] or 'raiz'} · alterada em {d['alterada']})", corpo]
    if d["cita"]:
        partes.append("Cita: " + ", ".join(f"[[{x['titulo']}]]" for x in d["cita"]))
    if d["citada_por"]:
        partes.append("Citada por: " + ", ".join(f"[[{x['titulo']}]]" for x in d["citada_por"]))
    return "\n\n".join(partes)
