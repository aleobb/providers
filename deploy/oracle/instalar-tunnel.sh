#!/usr/bin/env bash
# Instala cloudflared y registra el túnel de Cloudflare (acceso al escritorio noVNC sin abrir puertos).
# Uso: bash deploy/oracle/instalar-tunnel.sh [TOKEN]   (sin argumento, pide el token sin mostrarlo)
set -euo pipefail

case "$(uname -m)" in
  x86_64) ARCH=amd64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "Arquitectura no soportada: $(uname -m)" >&2; exit 1 ;;
esac

if ! command -v cloudflared >/dev/null; then
  DEB="$(mktemp --suffix=.deb)"
  curl -fsSL -o "$DEB" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  sudo dpkg -i "$DEB"
  rm -f "$DEB"
fi

TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  read -r -s -p "Token del túnel (Zero Trust > Networks > Tunnels): " TOKEN
  echo
fi
[ -n "$TOKEN" ] || { echo "Falta el token" >&2; exit 1; }

sudo cloudflared service uninstall >/dev/null 2>&1 || true
sudo cloudflared service install "$TOKEN"
sleep 3
systemctl is-active cloudflared
echo ">> Listo. En Zero Trust, Public hostname del túnel -> HTTP localhost:6080 y protegelo con una app de Access (solo tu email)."
