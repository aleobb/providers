---
id: PRV-OPS
titulo: Operaciones de providers (agente, VM Oracle y workflows)
estado: vigente
ultima_revision: 2026-11-21
resumen: Cómo operar el agente de providers: instalación y mantenimiento de la VM Oracle (KasmVNC, Cloudflare Tunnel, navegador, comandos con aprobación), línea base verificada de la VM, workflows de GitHub Actions, alta de portales y perfiles, ejecuciones fallidas y rotación de claves.
fuentes: [deploy/oracle (scripts), workflows, línea base de la VM del 2026-11-21, README anterior de deploy/oracle]
relacionados: [PRV-TEC, PRV-POR, PRV-DEC, PRV-PEN]
---

# Operaciones

> Cada sección empieza con un **TL;DR**. ⚠ = no verificado. No pegues valores de secretos en documentos, commits ni chats guardados.

## 1. Workflows de GitHub Actions
> **TL;DR:** dos workflows: pruebas y ejecución de la interfaz web. Ya no existe el flujo mensual «Descargar Facturas» (eliminado el 2026-11-21).

| Workflow | Disparador | Qué hace |
|---|---|---|
| `tests.yml` | push/PR a `master` (salvo cambios solo de `*.md` o `docs/**`) y manual | Python 3.12, `pip install -r requirements.txt pytest`, `python -m pytest -q` |
| `ejecutar-ejecucion.yml` | `workflow_dispatch` con `ejecucion_id` (lo dispara el Worker de finanzas) | `playwright install chrome --with-deps`, `python agent.py --ejecucion <id>`; solo portales de nube sin 2FA/captcha; timeout 30 min; run-name «Ejecución <id>» |
| `docs-check.yml` | cambios en `docs/**`, `AGENTS.md`, `README.md`, `CHANGELOG.md` | `python tools/docs_check.py` |

Secrets del repo: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `PROVIDERS_CREDENTIALS_KEY`; opcionales `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`. Los secrets de credenciales planas del flujo mensual (`EDENOR_*`, `METROGAS_*`, `EDESUR_*`, `TELECENTRO_*`, `CLARO_*`, `VISA_*`, `MASTERCARD_*`) ya no se usan: borrarlos si quedan. Versiones de acciones: `checkout`, `setup-python` y `upload-artifact` en v6.

## 2. VM Oracle: datos y línea base
> **TL;DR:** Ubuntu 24.04 ARM, 2 CPU, 11 GiB, sin swap ni Docker; servicios `kasmvnc`, `cloudflared` y `providers-agent` activos; apagada de 23:45 a 06:45 (hora Buenos Aires) por el Resource Scheduler.

Línea base verificada el **2026-11-21** (comando de solo lectura aprobado desde `/vm-comandos`): hostname `ab-finanzas-vnic`; Ubuntu 24.04.5 LTS, kernel `7.0.0-1016-oracle`; RAM 11 GiB (1,1 GiB en uso), **sin swap**; disco 96 GB (12 GB usados, 13 %); los tres servicios `active`; escuchan en toda la interfaz solo SSH 22 y `rpcbind` 111 (⚠ cerrar `rpcbind` si no se usa), el resto en localhost (KasmVNC 8444, cups 631, cloudflared 20241); journal de 241,9 MB sin límite configurado; `logrotate.d` sin entradas de providers; sin timers de backup locales (los backups son de Oracle); Python 3.12.3, Node 18.19.1, sin Docker; 27 paquetes por actualizar. El uptime coincide con el encendido de las 06:45.

- **Escritorio:** XFCE + KasmVNC (puerto 8444, servicio `kasmvnc`, solo localhost) publicado en `https://vm.finanzas.pp.ua` por Cloudflare Tunnel (`cloudflared`) con una app de Access (email + PIN) delante; **sin la app de Access el escritorio quedaría expuesto**. SSH 22 queda como respaldo (clave `ab-finanzas_ssh-key.key`, en la PC de Ale).
- **Agente:** unidad `providers-agent` (usuario `ubuntu`, `After=network-online.target kasmvnc.service`, `Restart=always`, `RestartSec=10`), `ExecStart=<repo>/.venv/bin/python agent.py`, `EnvironmentFile=~/.providers-agent.env` (modo 600; variables: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `PROVIDERS_CREDENTIALS_KEY`, `VM_APPROVAL_KEY`, `AGENT_NAME`, `DISPLAY`, `PROVIDERS_BROWSER_CHANNEL`, `PROVIDERS_PROFILE_FALLBACK=1`, Google vacías). Código en `~/providers` (rama `master`), venv `.venv`.
- **Horario:** apagada 23:45–06:45 (Buenos Aires). No programar descargas con runner `agente` en esa franja.
- **Estado y reinicio:** `systemctl status kasmvnc cloudflared providers-agent` · `journalctl -u providers-agent -f` · `sudo systemctl restart providers-agent`. Un apagado no requiere detener servicios: systemd los levanta al encender.
- **Actualizar el agente:** `cd ~/providers && git pull && sudo systemctl restart providers-agent` (si cambió `requirements.txt`: `~/providers/.venv/bin/pip install -r requirements.txt` antes). Enviado como comando de la VM, se interrumpe a sí mismo (queda `error: Interrumpido`): es esperado.
- **Costo:** el agente solo consulta Supabase cada 5 s; sin costos adicionales en el Always Free.

## 3. Instalación desde cero
> **TL;DR:** clonar, correr `instalar.sh`, instalar el navegador, el túnel y la aprobación de comandos. ⚠ La instalación de KasmVNC no está versionada.

1. Crear la instancia ARM (Ubuntu 24.04) y cargar la clave SSH. En la VM: `git clone https://github.com/aleobb/providers && cd providers && bash deploy/oracle/instalar.sh` (la primera vez crea `~/.providers-agent.env`; completarlo y volver a correr).
2. **Navegador del escritorio:** `bash deploy/oracle/instalar-navegador.sh` (idempotente, informa `[ok]`/`[!!]`): activa `linger`, instala el lanzador `providers-browser` y la entrada de menú *Chromium (providers)*, lo fija como predeterminado (xdg, XFCE, `sensible-browser`), agrega `PROVIDERS_PROFILE_FALLBACK=1` al env del agente, corrige `After=` de la unidad y comprueba `DISPLAY`. En Linux ARM se usa el Chromium de Playwright sin variable.
3. **Túnel (requiere un dominio propio en Cloudflare; los `*.workers.dev` no sirven para Public hostnames):** Zero Trust → Networks → Tunnels → Create tunnel (Cloudflared), copiar el token → en la VM `bash deploy/oracle/instalar-tunnel.sh` (pegar el token) → Public hostname `vm.<dominio>` → servicio `HTTP` `localhost:8444` → Zero Trust → Access → Applications: app self-hosted para `vm.<dominio>` con una policy *Allow* solo para el email de Ale. Verificar `systemctl status cloudflared`; quitar con `sudo cloudflared service uninstall`.
4. **Comandos con aprobación:** `bash deploy/oracle/configurar-aprobacion.sh` genera `VM_APPROVAL_KEY` si no existe, reinicia el agente y la muestra una vez; esa misma clave va como secret `VM_APPROVAL_KEY` del Worker `finanzas`. Si ya existe **no la cambia**.
5. ⚠ **Brecha:** `instalar.sh` todavía instala TigerVNC + noVNC (`vnc.service`, `novnc.service`, puerto 6080) como **legado**; KasmVNC (unidad `kasmvnc`, puerto 8444) está instalado a mano y falta versionarlo en `deploy/oracle/`.

## 4. Navegador y perfiles de la VM
> **TL;DR:** el agente usa un perfil por portal/perfil con nombre `<alias>-<id>-<hash>`; no se abre dos veces ni se borra como «caché».

- Perfiles en `~/providers/.chrome_profile/` (`ls` para verlos; p. ej. `telecentro-1-f95a514dbb61`). `providers-browser` abre `escritorio`; `providers-browser <nombre-exacto-del-directorio>` abre ese perfil para iniciar sesión a mano (MFA/CAPTCHA). Un nombre inexistente crea un perfil vacío que el agente no usa: lo más simple es «Ingresar al portal» desde la web de finanzas. Perfil huérfano conocido: `telecentro` (vacío; borrar con un comando aprobado tras comprobarlo).
- **Sesión manual:** pedir **Ingresar** o **Debug** desde la web, abrir `https://vm.finanzas.pp.ua`, resolver la verificación (la sesión persiste en el perfil) y cerrar el navegador antes de una descarga automática del mismo portal.
- `PROVIDERS_PROFILE_FALLBACK=1`: si falta `telecentro_default_clone`, Debug/Ingresar usan el perfil propio del proveedor.
- Para depurar: pedir Debug/Ingresar desde la web con el agente activo y mirar el navegador por KasmVNC. `--supabase` y `--perfil` no leen credenciales de Supabase.

## 5. Comandos de la VM con aprobación
> **TL;DR:** Claude inserta una fila en `vm_comandos`, Ale la aprueba en `/vm-comandos` (web de finanzas), el agente la ejecuta una vez y Claude lee el resultado. Claude no puede aprobar.

- Solicitar: `insert into public.vm_comandos (comando, motivo, timeout_s) values (…) returning id;` (1–20 000 caracteres; `timeout_s` 5–1800; una acción por comando, de solo lectura cuando alcance). Leer: `select estado, codigo_salida, salida from public.vm_comandos where id = <id>;`.
- Estados: `solicitado` → `aprobado` → `ejecutando` → `ok`/`error`; `rechazado`; `expirado` (venció la aprobación). Límites y modelo de firma: `TECNICO.md` §5.
- **No hacer:** rotar `VM_APPROVAL_KEY` por este canal (la clave nueva quedaría en `salida` sin redactar: borrar la línea de `~/.providers-agent.env` y correr `configurar-aprobacion.sh` desde la terminal del escritorio); imprimir `~/.providers-agent.env` (usar `sed -E 's/=.*/=<oculto>/'`); pegar credenciales de terceros; tocar `authorized_keys` sin verificación independiente.
- Revisar antes de aprobar (Ale): `sudo`, `rm -rf`, `curl … | bash`, `chmod/chown` masivos, cambios en `~/.ssh`, en el env del agente, servicios o firewall, y todo lo que imprima secretos.
- Fallas: queda `aprobado` ⇒ agente caído o VM apagada; `expirado` ⇒ volver a pedir; `error` con «Interrumpido» ⇒ reinició el agente (esperado); timeout ⇒ subir `timeout_s` o dividir.

## 6. Alta de portales y perfiles
> **TL;DR:** el módulo se escribe aquí (`PORTALES.md` §11); el portal y los perfiles se dan de alta en Supabase y en la web de finanzas.

- **Portal nuevo:** `insert` en `proveedor_portales` (`proveedor_id`, `codigo` único = `name` del módulo, `url_login`, `modo` `nube|local_asistido`, `requiere_2fa`, `activo`, `campos_login`, `config`). Cambiar `campos_login` de un portal existente: solo por SQL (`update proveedor_portales set campos_login = '[…]'::jsonb where codigo = '…'`); después reabrir los perfiles y completar los campos nuevos.
- **Perfiles:** «Perfiles y credenciales» en `/proveedores` (finanzas): campos separados, secretos enmascarados, en blanco al editar = sin cambio; se guardan cifrados. Cambiar una credencial en el portal ⇒ actualizar el perfil el mismo día.

## 7. Ejecuciones fallidas
> **TL;DR:** abrir la ejecución en la web, leer `resumen` y seguir el runner.

- `actions`: buscar «Ejecución <id>» en Actions de este repo. Sin corrida a los 15 min el Worker la marca `error` (causas: `GITHUB_TOKEN` del Worker vencido o sin permiso, `PROVIDERS_REPO`/`PROVIDERS_BRANCH` incorrectos, workflow desactivado). Corrida fallida: leer el job (Python, Playwright, secrets faltantes).
- `agente`: `systemctl status providers-agent`, `journalctl -u providers-agent -n 100`; `pendiente` eterno ⇒ agente caído, VM apagada (23:45–06:45) o runner distinto; «El agente se reinició durante la ejecución» ⇒ relanzar; «El proceso terminó sin informar estado (código N)» ⇒ ver los logs de consola y `journalctl`. `esperando_input` ⇒ responder el OTP/MFA o cancelar.
- Errores frecuentes: ver `TECNICO.md` §11 y `PORTALES.md`. Consultas útiles (solo lectura, SQL editor de Supabase): `select id, portal, perfil, accion, runner, estado, resumen, duracion_seg from v_ejecuciones order by id desc limit 20;` · `select ts, nivel, linea from ejecucion_logs where ejecucion_id = <id> order by id;` · `select * from ejecucion_prompts where estado = 'pendiente';`. Log completo: bucket `ejecucion-logs`.

## 8. Rotación de claves de este repo
> **TL;DR:** crear la nueva → actualizar todos los lugares → verificar → revocar la vieja.

- **`PROVIDERS_CREDENTIALS_KEY` (Fernet):** vive en la VM (`~/.providers-agent.env`), en Secrets de este repo, en el Worker de finanzas (`CREDENTIALS_KEY`/`PROVIDERS_CREDENTIALS_KEY`) y en la PC de Ale. Rotarla exige recifrar los `credenciales_enc` de todos los perfiles y actualizar todo a la vez; este repo admite una sola clave. ⚠ Falta la herramienta de recifrado. Perder la clave = recargar las credenciales a mano.
- **`SUPABASE_SERVICE_KEY`:** crear la nueva en Supabase → Secrets de este repo, `~/.providers-agent.env` y Worker → verificar con una ejecución → revocar la vieja.
- **Clave SSH:** agregar la pública nueva a `authorized_keys`, probar y recién entonces quitar la vieja.
