"""`uv run quiron-noticias` — coleta e mostra as principais notícias; `--fontes` testa cada fonte."""

import argparse

from quiron.servicos.noticias import consultas


def main() -> None:
    p = argparse.ArgumentParser(description="Notícias do Quíron")
    p.add_argument("--fontes", action="store_true", help="testa todas as fontes")
    p.add_argument("termo", nargs="?", help="tema, ticker ou palavra (ex.: copom, PETR4)")
    a = p.parse_args()
    if a.fontes:
        print(consultas.status_fontes())
    elif a.termo:
        print(consultas.noticias(a.termo))
    else:
        print(consultas.top())
