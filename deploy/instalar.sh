#!/usr/bin/env bash
# Sobe o Quíron no servidor (rodar dentro da pasta do projeto, como usuário quiron): bash deploy/instalar.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env && chmod 600 .env
  echo "Criei o .env a partir do modelo. Preencha as chaves (GEMINI_API_KEY, GROQ_API_KEY, TELEGRAM_BOT_TOKEN,"
  echo "TELEGRAM_ALLOWED_USER_IDS, TERMINAL_SENHA) com:  nano .env   — e rode este script de novo."
  exit 0
fi
grep -q "^TERMINAL_SENHA=.\+" .env || { echo "Defina TERMINAL_SENHA no .env (o Terminal no servidor exige senha)."; exit 1; }

mkdir -p dados biblioteca/entrada
docker compose up -d --build
docker compose ps

echo "==> Backup noturno às 03:00 (mantém 14 cópias; envia ao Google Drive se o rclone estiver configurado)"
LINHA="0 3 * * * cd $PWD && bash deploy/backup.sh >> dados/backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v "deploy/backup.sh"; echo "$LINHA" ) | crontab -

if command -v tailscale >/dev/null; then
  sudo tailscale serve --bg 8765 >/dev/null 2>&1 && echo "Terminal no ar só para a sua rede Tailscale: $(tailscale serve status 2>/dev/null | head -1)"
fi
echo "Quíron no ar. Mande /ajuda no Telegram."
