#!/usr/bin/env bash
# Prepara um servidor Ubuntu/Debian (mini PC ou VPS) para o Quíron. Rode como root UMA vez:
#   sudo bash deploy/preparar_host.sh "ssh-ed25519 AAAA... sua-chave-publica"
# Faz: atualizações automáticas, usuário `quiron`, SSH só com chave (sem senha/root), firewall só na porta 22,
# fail2ban, Docker, swap (se pouca memória), fuso de Brasília e Tailscale (acesso privado ao Terminal).
set -euo pipefail

CHAVE_PUBLICA="${1:-}"
if [[ $EUID -ne 0 ]]; then echo "Rode como root (sudo)."; exit 1; fi
if [[ -z "$CHAVE_PUBLICA" ]]; then echo "Informe sua chave SSH pública (ssh-ed25519 ...) como argumento."; exit 1; fi

echo "==> Atualizando o sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q && apt-get upgrade -y -q
apt-get install -y -q unattended-upgrades ufw fail2ban curl git ca-certificates
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Fuso de Brasília"
timedatectl set-timezone America/Sao_Paulo || ln -sf /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime

echo "==> Usuário quiron com acesso por chave SSH"
id quiron >/dev/null 2>&1 || adduser --disabled-password --gecos "" quiron
usermod -aG sudo quiron
install -d -m 700 -o quiron -g quiron /home/quiron/.ssh
grep -qxF "$CHAVE_PUBLICA" /home/quiron/.ssh/authorized_keys 2>/dev/null || echo "$CHAVE_PUBLICA" >> /home/quiron/.ssh/authorized_keys
chown quiron:quiron /home/quiron/.ssh/authorized_keys && chmod 600 /home/quiron/.ssh/authorized_keys
echo "quiron ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-quiron && chmod 440 /etc/sudoers.d/90-quiron

echo "==> SSH: sem senha e sem login de root"
cat > /etc/ssh/sshd_config.d/90-quiron.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
systemctl reload ssh 2>/dev/null || systemctl reload sshd

echo "==> Firewall: só a porta 22 (o Terminal passa pelo Tailscale)"
ufw default deny incoming && ufw default allow outgoing && ufw allow 22/tcp && ufw --force enable
systemctl enable --now fail2ban

echo "==> Docker"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
usermod -aG docker quiron

echo "==> Swap (se o servidor tiver menos de 8 GB de memória)"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $MEM_MB -lt 8000 && ! -f /swapfile ]]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

echo "==> Tailscale (rede privada entre o servidor, seu PC e seu celular)"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

cat <<'FIM'

Pronto. Próximos passos (como usuário quiron):
  1. sudo tailscale up            → abra o link que aparecer e entre com a sua conta do Tailscale
  2. git clone <seu repositório privado> ~/quiron && cd ~/quiron
  3. bash deploy/instalar.sh      → cria o .env, sobe o Quíron e agenda o backup noturno
FIM
