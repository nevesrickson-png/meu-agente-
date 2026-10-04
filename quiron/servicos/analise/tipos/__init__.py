"""Tipos de análise registrados na fila (cada módulo usa o decorador `@tipo`). Fases 8–11 acrescentam módulos aqui."""

from quiron.servicos.analise.tipos import renda_fixa  # noqa: F401
from quiron.servicos.analise.tipos import carteira  # noqa: F401,E402
from quiron.servicos.analise.tipos import planejamento  # noqa: F401,E402
