"""Cérebro do Quíron: um cofre de notas em Markdown (pasta `dados/cerebro/`) que o Rickson abre no Obsidian.

- `pasta.py`   → estrutura, modelos, configuração mínima do Obsidian e gravação segura (regras de quem escreve onde)
- `indice.py`  → índice de busca (FTS5) + links [[ ]] e quem cita cada nota, atualizado por data de modificação
- `diario.py`  → nota diária automática (Quíron/Diário/AAAA-MM-DD.md), sem tocar no que o Rickson escreve nela
- `notas.py`   → notas rápidas do `/nota` (viram arquivos em Minhas notas/Entrada) e migração das antigas
"""
