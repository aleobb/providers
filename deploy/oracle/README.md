# Agente de providers en la VM de Oracle

1. En la VM: `git clone https://github.com/aleobb/providers && cd providers && bash deploy/oracle/instalar.sh`
   (la primera vez crea `~/.providers-agent.env`; completalo y volvé a correr el script).
2. Ver el navegador (para `Debug` e `Ingresar`): `ssh -L 6080:localhost:6080 <usuario>@<ip-vm>` y abrir
   `http://localhost:6080/vnc.html`. VNC/noVNC escuchan solo en localhost: no abras puertos en Oracle.
3. Operación: `systemctl status providers-agent`, `journalctl -u providers-agent -f`.
4. Actualizar: `git pull && sudo systemctl restart providers-agent`.

Free tier: el agente solo consulta Supabase cada 5 s y no consume nada más; no hay costos adicionales.
En ARM se usa Chromium de Playwright (`PROVIDERS_BROWSER_CHANNEL=chromium`); algunos portales podrían reaccionar distinto a Chrome.

## Escritorio por Cloudflare Tunnel (opcional, alternativa al túnel SSH)

Requiere un dominio propio gestionado en Cloudflare (los `*.workers.dev` no sirven para Public hostnames).

1. Zero Trust > Networks > Tunnels > Create tunnel (Cloudflared); copiar el token.
2. En la VM: `cd ~/providers && git pull && bash deploy/oracle/instalar-tunnel.sh` (pega el token).
3. En el túnel, Public hostname: `vm.<tu-dominio>` -> Service `HTTP` `localhost:6080`.
4. Zero Trust > Access > Applications: app self-hosted para `vm.<tu-dominio>` con una policy Allow solo para tu email. Sin esta app el escritorio quedaría expuesto.
5. Abrir `https://vm.<tu-dominio>/vnc.html`.

Verificar: `systemctl status cloudflared`. Quitar: `sudo cloudflared service uninstall`.

## Probar a mano en la VM

`--supabase` y `--perfil` NO leen credenciales de Supabase (`--perfil` solo elige el alias en la sqlite local `.credentials/`, vacía en la VM).
Solo `--ejecucion-id`, que usa el agente, las toma de Supabase. Para depurar: pedir Debug/Ingresar desde `/proveedores`
con el agente activo y ver el navegador por noVNC.
