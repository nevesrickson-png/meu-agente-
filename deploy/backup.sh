#!/usr/bin/env bash
# Backup do Quíron: dados, cérebro (workspace), livros, configurações, segredos (Google Agenda) e .env num único arquivo.
# Uso: bash deploy/backup.sh   (o instalar.sh agenda às 03:00). Guarda em ~/quiron-backups e mantém os 14 mais novos.
# Se o rclone tiver um destino chamado "gdrive" configurado (rclone config), também envia para o Google Drive.
set -euo pipefail
cd "$(dirname "$0")/.."
DESTINO="${QUIRON_BACKUPS:-$HOME/quiron-backups}"
MANTER="${QUIRON_BACKUPS_MANTER:-14}"
mkdir -p "$DESTINO"
ARQUIVO="$DESTINO/quiron-$(date +%Y%m%d-%H%M%S).tar.gz"

# bancos SQLite copiados com segurança mesmo com o Quíron rodando
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/dados"
for db in dados/*.db; do
  [[ -f "$db" ]] || continue
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$db" "$TMP/$db"
done
tar -czf "$ARQUIVO" --exclude='dados/*.db' --exclude='dados/modelos' --exclude='dados/hermes' \
    dados biblioteca config agente/workspace segredos .env -C "$TMP" dados 2>/dev/null || true
echo "Backup criado: $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"

ls -1t "$DESTINO"/quiron-*.tar.gz | tail -n +$((MANTER + 1)) | xargs -r rm -f
if command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
  rclone copy "$ARQUIVO" gdrive:quiron-backups && echo "Enviado ao Google Drive."
fi
