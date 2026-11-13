#!/usr/bin/env bash
# Instala el agente de providers en una VM Ubuntu de Oracle Cloud (ARM o x86).
# Uso (como usuario normal, con sudo):  bash deploy/oracle/instalar.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO_DIR="$PWD"
ARCH="$(uname -m)"

sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git xfce4 xfce4-terminal dbus-x11 \
  tigervnc-standalone-server tigervnc-common novnc websockify

python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

# Navegador: Chrome en x86; Chromium de Playwright en ARM (Chrome no existe para Linux ARM).
if [ "$ARCH" = "x86_64" ]; then
  .venv/bin/playwright install chrome --with-deps
  CHANNEL=chrome
else
  .venv/bin/playwright install chromium --with-deps
  CHANNEL=chromium
fi

# Credenciales del agente (solo legibles por tu usuario). Se completa a mano.
ENV_FILE="$HOME/.providers-agent.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<ENV
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
AGENT_NAME=oracle-vm
DISPLAY=:1
PROVIDERS_BROWSER_CHANNEL=$CHANNEL
GOOGLE_DRIVE_FOLDER_ID=
GOOGLE_SERVICE_ACCOUNT_JSON=
ENV
  chmod 600 "$ENV_FILE"
  echo ">> Completá $ENV_FILE (SUPABASE_URL, SUPABASE_SERVICE_KEY, Google) y volvé a correr este script."
fi

# Contraseña de VNC (se pide una vez)
mkdir -p "$HOME/.vnc"
[ -f "$HOME/.vnc/passwd" ] || vncpasswd
cat > "$HOME/.vnc/xstartup" <<'XS'
#!/bin/sh
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS
exec startxfce4
XS
chmod +x "$HOME/.vnc/xstartup"

# Servicios systemd (se generan con tu usuario y esta carpeta)
for f in vnc novnc providers-agent; do
  sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$REPO_DIR|g" -e "s|__ENV__|$ENV_FILE|g" "deploy/oracle/$f.service" | sudo tee "/etc/systemd/system/$f.service" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now vnc novnc providers-agent
echo ">> Listo. Estado: systemctl status providers-agent | Logs: journalctl -u providers-agent -f"
echo ">> Escritorio: túnel SSH  ssh -L 6080:localhost:6080 $USER@<ip-vm>  y abrí http://localhost:6080/vnc.html"
