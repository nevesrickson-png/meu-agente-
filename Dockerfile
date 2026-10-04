# Quíron — imagem única usada pelo agente do Telegram e pelo Terminal (Fase 5).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Sao_Paulo \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never

# OCR para livros escaneados (Tesseract por+eng, Ghostscript) e fuso de Brasília
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng ghostscript tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /usr/local/bin/

RUN useradd --create-home --uid 1000 quiron && install -d -o quiron -g quiron /app
USER quiron
WORKDIR /app
# dependências primeiro (camada em cache), depois o código — tudo já pertencendo ao usuário quiron
COPY --chown=quiron:quiron pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=quiron:quiron . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
CMD ["quiron-telegram"]
