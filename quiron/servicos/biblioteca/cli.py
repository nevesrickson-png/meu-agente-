"""`uv run quiron-ingerir` — processa os livros de biblioteca/entrada pelo terminal (mostra o progresso)."""

import argparse

from quiron.servicos.biblioteca.ingestao import ingerir_pasta


def main() -> None:
    p = argparse.ArgumentParser(description="Ingere os livros de biblioteca/entrada")
    p.add_argument("--forcar", action="store_true", help="reprocessa livros já ingeridos")
    args = p.parse_args()
    print("Processando biblioteca/entrada (o primeiro uso baixa o modelo de embeddings, ~220 MB)...")
    rel = ingerir_pasta(forcar=args.forcar)
    for l in rel.livros:
        print(f"- {l.arquivo}: {l.situacao} — {l.detalhe}")
    print(f"\n{rel.resumo()}. Relatório: biblioteca/relatorio_ingestao.md")
