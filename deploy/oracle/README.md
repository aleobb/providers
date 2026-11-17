# Agente de providers en la VM de Oracle

1. En la VM: `git clone https://github.com/aleobb/providers && cd providers && bash deploy/oracle/instalar.sh`
   (la primera vez crea `~/.providers-agent.env`; completalo y volvé a correr el script).
2. Ver el navegador (para `Debug` e `Ingresar`): `ssh -L 6080:localhost:6080 <usuario>@<ip-vm>` y abrir
   `http://localhost:6080/vnc.html`. VNC/noVNC escuchan solo en localhost: no abras puertos en Oracle.
3. Operación: `systemctl status providers-agent`, `journalctl -u providers-agent -f`.
4. Actualizar: `git pull && sudo systemctl restart providers-agent`.

Free tier: el agente solo consulta Supabase cada 5 s y no consume nada más; no hay costos adicionales.
En Linux ARM se usa automáticamente el Chromium de Playwright (sin variable); en otros equipos, Chrome. `PROVIDERS_BROWSER_CHANNEL` fuerza otro canal y `PROVIDERS_BROWSER_EXECUTABLE` un binario concreto. Si el canal pedido no está instalado, se cae al Chromium de Playwright.

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

## Navegador del escritorio (mismo binario que el agente)

`bash deploy/oracle/instalar-navegador.sh` (idempotente; informa `[ok]`/`[!!]` por paso):
activa `linger`, instala el lanzador `providers-browser` y la entrada de menú *Chromium (providers)*,
lo fija como navegador predeterminado (xdg, XFCE y `sensible-browser`), agrega `PROVIDERS_PROFILE_FALLBACK=1`
al env del agente, corrige `After=` de la unidad (KasmVNC) y comprueba que `DISPLAY` exista.

- Perfiles en `.chrome_profile/<perfil>`; el agente usa el de cada proveedor (persisten entre ejecuciones).
  `providers-browser` abre `escritorio`; `providers-browser telecentro` abre el perfil de Telecentro para
  iniciar sesión a mano (MFA/CAPTCHA) y que el agente lo reutilice. Un perfil no se puede abrir dos veces:
  si el agente lo usa, el lanzador avisa; si el navegador del escritorio lo tiene abierto, el agente
  falla con un mensaje claro en lugar de un error de Playwright.
- `PROVIDERS_PROFILE_FALLBACK=1`: si falta el clon de perfil de Chrome de Telecentro (`telecentro_default_clone`),
  `Debug`/`Ingresar` usan el perfil propio del proveedor en vez de fallar.
