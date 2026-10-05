#!/usr/bin/env bash
# Restaura um backup do Quíron (no mesmo servidor ou num novo): bash deploy/restaurar.sh ~/quiron-backups/quiron-AAAAMMDD-HHMMSS.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
ARQUIVO="${1:?Informe o arquivo de backup (.tar.gz)}"
[[ -f "$ARQUIVO" ]] || { echo "Arquivo não encontrado: $ARQUIVO"; exit 1; }
docker compose down 2>/dev/null || true
tar -xzf "$ARQUIVO"
chmod 600 .env
chmod -R go-rwx segredos 2>/dev/null || true
docker compose up -d --build
echo "Restaurado de $ARQUIVO. Confira no Telegram com /agenda e /memoria."
