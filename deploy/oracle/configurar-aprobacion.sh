#!/usr/bin/env bash
# Activa en la VM los comandos con aprobación: genera VM_APPROVAL_KEY (si no existe), la guarda en el env
# del agente y reinicia el agente. Muestra la clave UNA vez para pegarla como secret del Worker "finanzas".
# Uso:  bash deploy/oracle/configurar-aprobacion.sh
set -euo pipefail
ENV_FILE="$HOME/.providers-agent.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
if grep -q '^VM_APPROVAL_KEY=' "$ENV_FILE"; then
  echo "[ok] VM_APPROVAL_KEY ya existe en $ENV_FILE (no se cambia)."
  echo "     Para verla: grep '^VM_APPROVAL_KEY=' $ENV_FILE"
else
  KEY="$(openssl rand -hex 32)"
  echo "VM_APPROVAL_KEY=$KEY" >> "$ENV_FILE"
  echo "[ok] Clave generada y guardada en $ENV_FILE"
  echo
  echo "Copiala ahora y pegala como secret VM_APPROVAL_KEY del Worker finanzas:"
  echo
  echo "    $KEY"
  echo
fi
sudo systemctl restart providers-agent && echo "[ok] agente reiniciado"
sleep 2
journalctl -u providers-agent -n 5 --no-pager | grep -i "aprobación" || echo "[!!] no aparece 'Comandos de la VM con aprobación: activados' en el log; revisá: journalctl -u providers-agent -n 30"
