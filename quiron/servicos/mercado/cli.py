"""`uv run quiron-briefing` — mostra os dados do briefing no terminal (bom para conferir as fontes)."""

from quiron.servicos.mercado import painel


def main() -> None:
    print(painel.briefing())
