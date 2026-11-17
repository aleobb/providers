#!/usr/bin/env bash
# Abre el Chromium de Playwright (el mismo binario que usa el agente) en el escritorio remoto.
# Uso: providers-browser.sh [perfil] [url]     perfil por defecto: escritorio
# Con un perfil de proveedor (p. ej. telecentro) se ve/usa el mismo perfil del agente,
# pero solo si el agente no lo está usando.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
PERFIL="escritorio"
if [ -n "${1:-}" ] && [[ "$1" != *://* ]]; then PERFIL="$1"; shift; fi
PROFILE_DIR="$ROOT/.chrome_profile/$PERFIL"
mkdir -p "$PROFILE_DIR"

avisar() { echo "$*" >&2; command -v notify-send >/dev/null 2>&1 && notify-send "Navegador providers" "$*" || true; }

LOCK="$PROFILE_DIR/SingletonLock"
if [ -L "$LOCK" ]; then
  PID="$(readlink "$LOCK" | sed 's/.*-//')"
  if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
    avisar "El perfil '$PERFIL' ya está abierto (pid $PID). Cerralo antes de abrirlo de nuevo."
    exit 1
  fi
fi

if [ -z "${DISPLAY:-}" ] && [ -f "$HOME/.providers-agent.env" ]; then
  DISPLAY="$(grep -E '^DISPLAY=' "$HOME/.providers-agent.env" | tail -1 | cut -d= -f2 || true)"
  export DISPLAY
fi
export TZ="America/Argentina/Buenos_Aires"

EXE="$("$ROOT/.venv/bin/python" - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print(p.chromium.executable_path)
PY
)"
[ -x "$EXE" ] || { avisar "No se encontró el Chromium de Playwright ($EXE). Ejecutá: .venv/bin/playwright install chromium"; exit 1; }

# Mismos flags que usa Playwright en Linux: sin sandbox (Ubuntu 24.04 restringe los user namespaces)
# y almacén de contraseñas básico, para que las cookies del perfil se lean igual desde el agente.
exec "$EXE" --user-data-dir="$PROFILE_DIR" --no-sandbox --password-store=basic \
  --lang=es-AR --no-first-run --no-default-browser-check "$@"
