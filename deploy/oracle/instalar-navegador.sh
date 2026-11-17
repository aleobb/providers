#!/usr/bin/env bash
# Deja el Chromium de Playwright como navegador del escritorio remoto de la VM. Es idempotente:
# cada paso informa [ok] o [!!] y el script sigue. Uso:  bash deploy/oracle/instalar-navegador.sh
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
LAUNCHER="$ROOT/deploy/oracle/providers-browser.sh"
ENV_FILE="$HOME/.providers-agent.env"
ok() { echo "[ok] $*"; }
warn() { echo "[!!] $*"; }
chmod +x "$LAUNCHER"

# 1. Gestor de usuario de systemd siempre activo (lo necesitan Snap y servicios de usuario)
sudo loginctl enable-linger "$USER" && ok "linger activado para $USER" || warn "no se pudo activar linger"

# 2. Lanzador y entrada de menú
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/xfce4/helpers" "$HOME/.config/xfce4"
ln -sf "$LAUNCHER" "$HOME/.local/bin/providers-browser" && ok "comando providers-browser"
cat > "$HOME/.local/share/applications/providers-chromium.desktop" <<DESK
[Desktop Entry]
Version=1.0
Type=Application
Name=Chromium (providers)
Comment=Chromium de Playwright con perfil persistente
Exec=$LAUNCHER %U
Icon=web-browser
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;x-scheme-handler/http;x-scheme-handler/https;
StartupNotify=true
DESK
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
ok "entrada de menú Chromium (providers)"

# 3. Navegador predeterminado (xdg y helper de XFCE para "Web Browser")
xdg-settings set default-web-browser providers-chromium.desktop 2>/dev/null \
  && ok "navegador predeterminado (xdg)" || warn "xdg-settings falló"
cat > "$HOME/.local/share/xfce4/helpers/providers-chromium.desktop" <<HELP
[Desktop Entry]
NoDisplay=true
Version=1.0
Type=X-XFCE-Helper
X-XFCE-Category=WebBrowser
X-XFCE-Binaries=$LAUNCHER
X-XFCE-Commands=$LAUNCHER
X-XFCE-CommandsWithParameter=$LAUNCHER "%s"
Icon=web-browser
Name=Chromium (providers)
HELP
RC="$HOME/.config/xfce4/helpers.rc"
if grep -q '^WebBrowser=' "$RC" 2>/dev/null; then
  sed -i 's/^WebBrowser=.*/WebBrowser=providers-chromium/' "$RC"
else
  echo 'WebBrowser=providers-chromium' >> "$RC"
fi
ok "Web Browser de XFCE -> Chromium (providers)"

# 4. sensible-browser / x-www-browser
sudo update-alternatives --install /usr/bin/x-www-browser x-www-browser "$LAUNCHER" 200 >/dev/null \
  && sudo update-alternatives --set x-www-browser "$LAUNCHER" >/dev/null \
  && ok "x-www-browser (sensible-browser)" || warn "update-alternatives falló"

# 5. Variables del agente: canal Chromium y perfil propio si falta el clon de Chrome (Telecentro)
touch "$ENV_FILE"
grep -q '^PROVIDERS_BROWSER_CHANNEL=' "$ENV_FILE" || echo 'PROVIDERS_BROWSER_CHANNEL=chromium' >> "$ENV_FILE"
grep -q '^PROVIDERS_PROFILE_FALLBACK=' "$ENV_FILE" || echo 'PROVIDERS_PROFILE_FALLBACK=1' >> "$ENV_FILE"
ok "variables en $ENV_FILE"

# 6. Unidad del agente: ya no existe vnc.service (se usa KasmVNC)
UNIT=/etc/systemd/system/providers-agent.service
if [ -f "$UNIT" ]; then
  sudo sed -i 's/ vnc\.service/ kasmvnc.service/' "$UNIT" && sudo systemctl daemon-reload && ok "unidad del agente actualizada" \
    || warn "no se pudo editar $UNIT"
fi

# 7. DISPLAY del agente debe existir en el servidor X de KasmVNC
DISP="$(grep -E '^DISPLAY=' "$ENV_FILE" | tail -1 | cut -d= -f2)"
LIVE="$(ls /tmp/.X11-unix 2>/dev/null | sed 's/^X/:/' | tr '\n' ' ')"
if [ -n "$DISP" ] && echo " $LIVE " | grep -q " $DISP "; then ok "DISPLAY=$DISP existe"
else warn "DISPLAY='${DISP:-vacío}' no coincide con los displays activos: ${LIVE:-ninguno}. Corregí DISPLAY en $ENV_FILE"; fi

sudo systemctl restart providers-agent && ok "agente reiniciado" || warn "no se pudo reiniciar providers-agent"
systemctl is-active "user@$(id -u).service" | sed 's/^/[info] user@ -> /'
echo ">> Probar: desde el escritorio remoto, menú > Internet > Chromium (providers), o en una terminal: providers-browser"
