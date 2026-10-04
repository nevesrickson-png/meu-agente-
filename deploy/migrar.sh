#!/usr/bin/env bash
# Leva o Quíron para outro servidor em poucos minutos (meta do projeto: < 1 hora).
# Antes: no servidor novo, rode deploy/preparar_host.sh e clone o repositório em ~/quiron.
# Uso (no servidor ANTIGO): bash deploy/migrar.sh quiron@ip-ou-nome-tailscale-do-novo
set -euo pipefail
cd "$(dirname "$0")/.."
NOVO="${1:?Informe usuario@servidor-novo}"
bash deploy/backup.sh
ULTIMO=$(ls -1t "${QUIRON_BACKUPS:-$HOME/quiron-backups}"/quiron-*.tar.gz | head -1)
scp "$ULTIMO" "$NOVO:/tmp/quiron-migracao.tar.gz"
ssh "$NOVO" "cd ~/quiron && git pull && bash deploy/restaurar.sh /tmp/quiron-migracao.tar.gz"
docker compose down
echo "Migração concluída. O Quíron agora roda em $NOVO (o antigo foi desligado)."
