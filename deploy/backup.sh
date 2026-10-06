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
# 1º o resto (sem os .db vivos); depois as cópias seguras dos bancos — num tar separado, porque o --exclude valeria
# também para as cópias e o backup sairia sem nenhum banco
TAR="$TMP/backup.tar"
ITENS=()
for item in dados biblioteca config agente/workspace segredos .env; do [[ -e "$item" ]] && ITENS+=("$item"); done
tar -cf "$TAR" --exclude='dados/*.db' --exclude='dados/*.db-wal' --exclude='dados/*.db-shm' --exclude='dados/modelos' \
    --exclude='dados/hermes' "${ITENS[@]}"
tar -rf "$TAR" -C "$TMP" dados
(umask 077; gzip -c "$TAR" > "$ARQUIVO")  # o backup leva .env e segredos/: só o dono do servidor lê
tar -tzf "$ARQUIVO" | grep -q '^dados/.*\.db$' || echo "AVISO: o backup saiu sem nenhum banco (.db) — confira a pasta dados/."
echo "Backup criado: $ARQUIVO ($(du -h "$ARQUIVO" | cut -f1))"

ls -1t "$DESTINO"/quiron-*.tar.gz | tail -n +$((MANTER + 1)) | xargs -r rm -f
if command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -q "^gdrive:"; then
  rclone copy "$ARQUIVO" gdrive:quiron-backups && echo "Enviado ao Google Drive."
fi
