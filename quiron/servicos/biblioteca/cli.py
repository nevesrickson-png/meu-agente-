"""`uv run quiron-ingerir` — processa os livros de biblioteca/entrada pelo terminal (mostra o progresso)."""

import argparse

from quiron.nucleo.config import RAIZ
from quiron.servicos.biblioteca.ingestao import ingerir_pasta


def main() -> None:
    p = argparse.ArgumentParser(description="Ingere os livros de biblioteca/entrada")
    p.add_argument("--forcar", action="store_true", help="reprocessa livros já ingeridos")
    p.add_argument("--academia", action="store_true",
                   help="processa o material de certificação de academia/material/ (com subpastas por certificação)")
    args = p.parse_args()
    entrada = RAIZ / "academia" / "material" if args.academia else None
    print(f"Processando {'academia/material' if args.academia else 'biblioteca/entrada'} "
          "(o primeiro uso baixa o modelo de embeddings, ~220 MB)...")
    rel = ingerir_pasta(forcar=args.forcar, entrada=entrada, recursivo=args.academia)
    for l in rel.livros:
        print(f"- {l.arquivo}: {l.situacao} — {l.detalhe}")
    print(f"\n{rel.resumo()}. Relatório: biblioteca/relatorio_ingestao.md")
