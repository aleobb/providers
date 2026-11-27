# Changelog

Una entrada por cambio, la más reciente arriba. El historial anterior está en Git.

## 2026-11-27 — Docs: pendiente de actualizar el agente en la VM (PV-08)
- Se registra en PENDIENTES (PV-08) la aprobación del comando #7 de la VM, que actualiza el agente con los cambios del 2026-11-26/27.

## 2026-11-27 — Providers: argparse, desempate por importe, claves únicas del CI y auditoría
- CLI: `core/cli.py` lee los flags con `argparse` (mismos nombres y mismo dict de `parse_args()`); un flag desconocido, abreviado o sin valor ahora termina con error en vez de ignorarse, y hay `--help`. El error inesperado imprime el traceback.
- Sync a Supabase: con varios comprobantes del mismo concepto y vencimiento elige el único cuyo importe coincide con el PDF (si no, se detiene nombrando los candidatos con su `nro_doc`); los conceptos se leen una vez por corrida.
- `credential_store`: la limpieza de campos de credenciales obsoletos es general (se quitan los que el proveedor ya no declara) en lugar del caso por nombre de Medife.
- Dependencias: `python-dotenv` sube a >=1.2.2 (vulnerabilidad PYSEC-2026-2270 detectada con pip-audit); nuevo `requirements-dev.txt` (pytest) y `constraints-ci.txt` (versiones exactas para el CI); workflow semanal `auditoria-dependencias.yml`.
- Se borra `_legacy/` (paquetes viejos sin uso; queda en el historial de Git). Tests nuevos: parser, sync con duplicados y caché de conceptos, `credential_store`, contrato del `run-name` y vector Fernet compartido con el Worker. Docs: TECNICO, OPERACIONES, PENDIENTES.

## 2026-11-26 — Providers: timeout del agente, reintentos, redacción de logs y multi-clave Fernet
- Agente: las descargas tienen tiempo máximo (`AGENT_RUN_TIMEOUT_MIN`, 45 min; 25 en GitHub Actions; `debug` e `ingresar` sin límite) y al vencer se corta el árbol de procesos; `--ejecucion` valida que el id sea numérico.
- `SupabaseClient`: reintentos acotados (lecturas ante red/429/5xx; escrituras solo si no llegó a conectar o 429); el broker de OTP/MFA sigue esperando si Supabase falla un momento.
- Nuevo `core/redact.py`: los logs de ejecución tapan campos secretos de credenciales, claves del entorno, respuestas OTP/MFA y tokens conocidos (PV-03).
- Nuevo `core/crypto_keys.py` (MultiFernet) y `tools/recifrar_credenciales.py`: `PROVIDERS_CREDENTIALS_KEY` admite varias claves separadas por coma (PV-04).
- `vm_exec.py`: la salida de los comandos se lee con tope (solo la cola) en vez de guardarse entera en memoria.
- `ejecutar-ejecucion.yml`: `permissions: contents: read` y el id de ejecución pasa por `env` con validación.
- Tests nuevos: redacción, claves, reintentos, timeout del agente, salida de la VM, broker y recifrado. Docs: TECNICO §5/§variables, DECISIONES §3, OPERACIONES §8, PENDIENTES (PV-03/PV-04), AGENTS.

## 2026-11-24 — Docs: trabajo secuencial entre IAs y permisos locales fuera de Git
- `AGENTS.md`: mismas reglas que en finanzas (leer los últimos commits al empezar, sin ramas ni PRs, push rechazado → `git pull --rebase` sin `--force`, cierre de sesión).
- `.claude/settings.local.json` (permisos locales de Claude Code, con comodines) deja de versionarse y se agrega al `.gitignore`; `.claude/launch.json` se mantiene.

## 2026-11-22 — VM: journal a 500 MB y pedidos #5/#6
- El límite del journal de la VM sube de 200 a 500 MB (30 días); los pedidos de actualización de paquetes y cierre de `rpcbind` (#5 y #6) terminaron ok. Docs: `docs/OPERACIONES.md` §2 y `docs/PENDIENTES.md` (PV-09).

## 2026-11-22 — VM: journal limitado
- El journal de la VM queda limitado a 200 MB y 30 días; se documenta en `docs/OPERACIONES.md` §2. Pedidos de actualización de paquetes y cierre de `rpcbind` en curso.

## 2026-11-21 — Documentación propia e independiente del repo
- Nueva documentación autosuficiente: `AGENTS.md` (guía y reglas), `README.md` (puesta en marcha y uso) y `docs/` con `TECNICO.md`, `PORTALES.md`, `OPERACIONES.md`, `DECISIONES.md` y `PENDIENTES.md` (versión productiva vigente, `resumen` en el frontmatter y TL;DR por sección).
- `CLAUDE.md` y `.github/copilot-instructions.md` pasan a ser punteros a `AGENTS.md`; la guía de portales y el README de `deploy/oracle/` se integran en `docs/PORTALES.md` y `docs/OPERACIONES.md`. Se corrigió contenido desactualizado (noVNC, Aysa y Medifé ausentes, referencias a documentos de finanzas inexistentes).
- `tools/docs_check.py` y workflow `docs-check.yml`: frontmatter, enlaces, IDs, TL;DR y patrones de secretos.
- Línea base de la VM verificada el 2026-11-21 (ver `docs/OPERACIONES.md` §2).

## 2026-11-21 — Se elimina el flujo mensual «Descargar Facturas»
- Se borra `.github/workflows/descargar-facturas.yml` (cron del día 5 con credenciales planas en Secrets); lo reemplaza la interfaz web de ejecuciones.
