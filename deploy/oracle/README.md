# Agente de providers en la VM de Oracle

1. En la VM: `git clone https://github.com/aleobb/providers && cd providers && bash deploy/oracle/instalar.sh`
   (la primera vez crea `~/.providers-agent.env`; completalo y volvé a correr el script).
2. Ver el navegador (para `Debug` e `Ingresar`): `ssh -L 6080:localhost:6080 <usuario>@<ip-vm>` y abrir
   `http://localhost:6080/vnc.html`. VNC/noVNC escuchan solo en localhost: no abras puertos en Oracle.
3. Operación: `systemctl status providers-agent`, `journalctl -u providers-agent -f`.
4. Actualizar: `git pull && sudo systemctl restart providers-agent`.

Free tier: el agente solo consulta Supabase cada 5 s y no consume nada más; no hay costos adicionales.
En ARM se usa Chromium de Playwright (`PROVIDERS_BROWSER_CHANNEL=chromium`); algunos portales podrían reaccionar distinto a Chrome.
