---
id: PRV-TEC
titulo: Documento técnico de providers
estado: vigente
ultima_revision: 2026-11-21
resumen: Cómo está construido el repo providers: estructura, contrato Provider, CLI, credenciales (SQLite local y Supabase/Fernet), ejecuciones gestionadas y agente, sincronización con Supabase/Airtable/Drive, extractor de PDF, navegador, configuración, pruebas y troubleshooting.
fuentes: [código del repo, README y CLAUDE.md anteriores, esquema de Supabase (propiedad del repo finanzas)]
relacionados: [PRV-POR, PRV-OPS, PRV-DEC, PRV-PEN]
---

# Técnico

> Cada sección empieza con un **TL;DR**. ⚠ = no verificado. Nunca se documentan valores de secretos.

## 1. Qué es y cómo está organizado
> **TL;DR:** CLI Python (Playwright + httpx) que inicia sesión en portales de servicios y tarjetas, descarga la última factura en PDF, extrae sus datos y los sincroniza (Supabase, Airtable, Drive). Además un agente que atiende los pedidos de la interfaz web del repo `aleobb/finanzas` y los comandos aprobados de la VM.

```text
main.py                 # entrada → core.cli.main()
agent.py                # agente: toma ejecuciones runner=agente y comandos de la VM (PC o VM)
vm_exec.py              # ejecuta comandos aprobados (firma HMAC, una sola vez)
core/                   # núcleo agnóstico del proveedor
  provider.py registry.py hooks.py accounts.py config.py exceptions.py dates.py
  browser.py            # BrowserSession y browser_channel() (único lugar que decide el navegador)
  cli.py                # CLI unificado
  credential_store.py credential_cli.py   # perfiles cifrados en SQLite local
  managed.py prompts.py                    # ejecución gestionada (Supabase): logs, heartbeat, OTP/MFA
  run_log.py session_store.py network_diagnostics.py utils.py
integrations/           # mecánicas genéricas, sin lógica por proveedor
  pdf_extractor/ supabase_sync/ airtable/ google_drive/
providers/<portal>/     # aysa claro edenor edesur mastercard medife metrogas telecentro visa (ver PORTALES.md)
deploy/oracle/          # scripts de instalación de la VM (ver OPERACIONES.md)
tools/                  # exportar_credenciales_supabase.py, docs_check.py
tests/                  # pruebas compartidas; las de cada portal en providers/<portal>/tests/
_legacy/                # paquetes independientes viejos (edenor_downloader, metrogas_downloader)
```
Salidas locales: `facturas/` (PDF `{proveedor}_{periodo}_{cliente}_factura.pdf`), `ejecucion.log`, `.credentials/providers.sqlite3`, `.sessions/`, `.chrome_profile/`.

## 2. Contrato `Provider` y reglas de diseño
> **TL;DR:** el core orquesta hooks tipados del proveedor; nunca hay `if provider.name == …` en `core/` ni en `integrations/`.

- **Frontera:** `core/` e `integrations/` son agnósticos. Lo específico de un portal (login y ciclo de sesión, opciones de ejecución, navegador, metadatos de credenciales, fechas de factura, nombres de Drive, integraciones propias) vive en `providers/<portal>/`. El comportamiento opcional se expone como hooks o capacidades del contrato con defaults genéricos; no usar `hasattr` ni fallbacks por nombre. Al cambiar un portal, buscar en `core/`, `integrations/` y otros portales manejo duplicado o por nombre, y agregar tests que protejan la frontera además del comportamiento.
- **Registro:** cada `providers/<portal>/__init__.py` llama `register(...)`; `providers/__init__.py` importa todos (`from . import <portal>  # noqa: F401`).
- **Atributos de clase:** `name` (código), `display_name`, `requires_credentials`, `can_resume_session`, `invoice_date_patterns`, `invoice_data_patterns`, `estimated_next_due_date_months`, `credential_fields` (por defecto `email` y `password` con `secret=True`).
- **Métodos obligatorios:** `get_config()`, `login(page, context)`, `fetch_accounts(page, context) -> list[Account]`, `download_invoice(page, context, account) -> Path`.
- **Hooks opcionales:** `configure_credentials`, `configure_profile_session`, `apply_run_options`, `extract_invoice_date`, `extract_card_statement_data`, `drive_target`, `is_session_error`, `try_resume_session`, `save_session`, `logout`, `close`. Cada portal declara si soporta reanudar sesión.
- **Configuración:** `BaseProviderConfig` (pydantic-settings, `env_prefix="<NOMBRE>_"`) solo con opciones no secretas; las credenciales se inyectan desde el perfil.
- **Errores:** jerarquía `InvoiceDownloaderError` (`LoginError`, `NavigationError`, `DownloadError`, `InvoiceNotFoundError`, `ConfigurationError`, `ServerUnavailableError`). `ServerUnavailableError` es un fallo transitorio del servidor: se registra y se sigue con el siguiente proveedor.
- Los servicios HTTP que descargan varias cuentas reutilizan su `httpx.AsyncClient` durante el ciclo del proveedor; el core los libera al terminar. Claro y Telecentro comparten `core/network_diagnostics.py` (filtrado de dominios, resumen de respuestas, **redacción de secretos**).

## 3. CLI (`python main.py …`)
> **TL;DR:** `--proveedor <código> --todas` descarga; `--listar` muestra cuentas; `--debug` abre el navegador visible; `--ingresar` deja el portal abierto.

| Flag | Efecto |
|---|---|
| `--proveedor <código>` / `--todos-proveedores` | Un proveedor o todos |
| `--todas` / `--cuenta <n>` / `--listar` | Todas las cuentas, una, o solo listarlas |
| `--debug` | Chrome visible para resolver verificaciones humanas |
| `--ingresar` | Login automático y navegador abierto (sin descarga, consulta de cuentas ni logout); la terminal queda activa hasta cerrar la ventana |
| `--nosession` | Perfil temporal vacío; no carga ni reemplaza la sesión guardada; se elimina al terminar |
| `--gestionar-credenciales` | Gestor interactivo de perfiles locales (`V. Ver perfil` pide confirmación antes de mostrar valores) |
| `--perfil <alias>` | Elige el perfil sin preguntar (ver §4) |
| `--datos-pdf-csv <ruta>` | Guarda en CSV los datos extraídos |
| `--supabase` | Sincroniza cada comprobante con Supabase |
| `--airtable`, `--airtable-documento <pdf>`, `--banco <b>`, `--url` | Sincronización con Airtable (§6) |
| `--ejecucion-id <id>` | Ejecución gestionada pedida desde la web (§5); solo esta toma credenciales de Supabase |

Si un proveedor tiene varios perfiles, el programa pregunta cuál usar (con uno solo, lo elige). Procesar PDFs existentes: `python -m integrations.pdf_extractor.cli <pdfs> [--dir <carpeta> --proveedor <p>] --csv datos.csv`.

## 4. Credenciales
> **TL;DR:** dos almacenes con la misma clave Fernet (`PROVIDERS_CREDENTIALS_KEY`, siempre fuera de la base): SQLite local para uso por consola y `portal_perfiles.credenciales_enc` en Supabase para ejecuciones gestionadas.

- **Local:** `.credentials/providers.sqlite3` (ignorada por Git). Tablas `providers`→`clients` (un proveedor, varios perfiles con alias) y `provider_credential_fields` (campos requeridos, etiquetas, obligatoriedad, secretos; las clases de cada módulo declaran los iniciales y no se sobrescriben los ya guardados). `CredentialStore.request_credentials(nombre)` resuelve campos, elige perfil y valida obligatorios antes de inyectarlos en la config. La migración desde `.env` corre una sola vez y quita esas líneas. **No agregar credenciales a `.env`.**
- **Supabase:** `portal_perfiles.credenciales_enc` = token Fernet de un JSON `{campo: valor}`; los campos de cada portal se definen en `proveedor_portales.campos_login` (`[{name,label,required,secret}]`, sin valores) y deben coincidir con `credential_fields` del módulo. `core/managed.py` descifra al ejecutar. `tools/exportar_credenciales_supabase.py [--dry-run]` cifra y sube los perfiles locales. Reemplaza al esquema anterior con Vault.
- **Clave:** una sola clave Fernet en este repo (`Fernet(PROVIDERS_CREDENTIALS_KEY)`); el Worker de finanzas admite varias separadas por coma. Perder la clave = perder los perfiles. ⚠ No existe herramienta de recifrado masivo (`tools/recifrar_credenciales.py` pendiente).
- ⚠ `--supabase` y `--perfil` **no** leen credenciales de Supabase (solo eligen alias en la SQLite local; vacía en la VM).

## 5. Ejecuciones gestionadas y agente
> **TL;DR:** la web crea una fila en `ejecuciones`; la toma GitHub Actions (portales `nube` sin 2FA) o el agente (todo lo demás); `core/managed.py` guarda logs, heartbeat y pide OTP/MFA.

- **Quién corre:** `actions` solo si la acción es `descargar`, el portal es `modo = nube` y no requiere 2FA; en otro caso `agente` (decide el Worker de finanzas con `runnerPara`). Workflow `ejecutar-ejecucion.yml`: `workflow_dispatch` con `ejecucion_id`, Python 3.12, `playwright install chrome --with-deps`, `python agent.py --ejecucion <id>`, timeout 30 min, run-name «Ejecución <id>».
- **Agente (`agent.py`):** sondea Supabase cada **5 s**; `claim()` toma la `pendiente` más antigua con `UPDATE … WHERE estado = pendiente` (atómico, varios agentes no se pisan); arma `python main.py --ejecucion-id <id> --proveedor <código> [--supabase] [--debug|--ingresar] (--todas | --cuenta <c>) [--nosession] [--perfil <p>]`. Al arrancar marca `error` sus ejecuciones `en_curso/esperando_input` con heartbeat > 2 min («El agente se reinició durante la ejecución»); si `main.py` muere sin cerrar estado, `error` con el código. Las descargas tienen **tiempo máximo** (`AGENT_RUN_TIMEOUT_MIN`: 45 min en el agente, 25 en GitHub Actions, `0` = sin límite; `debug` e `ingresar` son interactivas y no vencen): al vencer corta el árbol de procesos (navegador incluido) y deja `error` «Superó el tiempo máximo». `--ejecucion <id>` solo acepta números. Atiende los comandos de la VM **entre** ejecuciones (las ejecuciones tienen prioridad).
- **`ManagedRun` (`core/managed.py`):** `start()` pone `en_curso`, `agente`, `heartbeat_at`, `inicio_at`, `github_run_id` y redirige stdout/stderr a archivo local y a `ejecucion_logs` (lotes de 500 cada 2 s, líneas ≤ 2000 caracteres); descifra los perfiles del portal; **heartbeat cada 20 s** y si la fila pasó a `cancelada` interrumpe el proceso; los prompts (`otp`, `mfa`, `perfil`, `cuenta`, `texto`) se insertan en `ejecucion_prompts`, la ejecución queda `esperando_input` hasta `PROVIDERS_PROMPT_TIMEOUT` (600 s por defecto), la respuesta se borra al consumirse y si vence queda `expirado` y error de timeout; `finish(code)` deja `ok` (código 0 y sin errores de sync), `error` o `cancelada`, guarda `resumen` («N comprobante(s) sincronizado(s); M error(es) de sincronización; código de salida X»), sube el log completo a `ejecucion-logs/<id>.log` y escribe `log_storage_path`.
- **Redacción de logs (`core/redact.py`):** antes de guardar cada línea en `ejecucion_logs` y en el log de Storage se tapan con `***` los campos secretos de las credenciales cargadas (marcados `secret` o con nombre de clave), los valores de variables de entorno con nombre de secreto (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`), las respuestas OTP/MFA y los formatos JWT, `Bearer`/`Basic`, token Fernet, token de GitHub y `sb_…`. ⚠ Un dato sensible que no encaje en esas reglas (p. ej. una cookie) sí queda guardado: nunca imprimir credenciales, cookies, `Authorization` ni JWT. La consola local no se redacta.
- **Resiliencia:** `SupabaseClient` reintenta (2 veces, espera 0,5 s y 1 s) las lecturas ante error de red, 429 o 5xx; las escrituras solo si no llegaron a conectar o hubo 429; la subida con `upsert` también. Si Supabase falla un momento mientras se espera un OTP, la corrida sigue esperando hasta `PROVIDERS_PROMPT_TIMEOUT`.
- **Comandos de la VM (`vm_exec.py`):** el agente ejecuta una fila de `vm_comandos` solo si la firma HMAC-SHA256 de `id|timeout_s|expira_epoch|comando` (clave `VM_APPROVAL_KEY`) es válida y no venció (1–60 min); la reclama atómicamente y la corre **una vez** con `bash -lc`, sin los secretos del agente en el entorno, con tiempo máximo (5–1800 s), salida redactada (`***` para valores de 8+ caracteres de esos secretos) y recortada a los últimos 100 000 caracteres (se lee con un tope: un comando con salida enorme no llena la memoria). Un comando que reinicia el agente queda en `error` «Interrumpido». Sin `VM_APPROVAL_KEY` la función está desactivada.

## 6. Sincronización y extracción
> **TL;DR:** nunca se crean conceptos; un comprobante se identifica por concepto + vencimiento actual; el PDF va a Storage y, si hay Drive, también allí.

- **Supabase (`integrations/supabase_sync`):** el concepto se busca por proveedor (+ banco) y se valida contra `conceptos."Identificador"` (nº de cliente/cuenta/servicio extraído del PDF); si falta o no coincide, se detiene. Una coincidencia de comprobante actualiza, ninguna crea, varias detienen sin modificar nada; los campos ausentes no sobrescriben datos. PDF → bucket `Comprobantes/<comprobante_id>/<nombre>` (`doc_storage_path`); con Drive configurado, copia y `doc_drive_file_id`/`doc_drive_link`; si ya hay documento, no se vuelve a subir; un fallo de Storage no impide registrar el comprobante (aviso en el log).
- **Airtable (opcional, vigente durante el paralelo con la app):** `AIRTABLE_TOKEN` y `AIRTABLE_BASE_ID`; tablas `Comprobantes` y `Conceptos` (ajustables con `AIRTABLE_*` de `.env.example`); `Comprobantes` enlaza a `Conceptos` por `Concepto`; el concepto se busca por `Nombre` con los términos de proveedor y banco y se valida `Conceptos.Identificador`; no se usa el titular ni se crean conceptos. Guarda `Fecha Vto.`, `Importe Pesos`, `Importe USD`, `Prox.Vto.`, `Cierre Actual`, `Prox.Cierre`; mismo upsert que arriba; el PDF se carga directo al campo `Doc.` con la API de carga (sin URL pública) y se omite si el registro ya tiene adjuntos. `--airtable-documento <pdf> [--proveedor p] [--banco b]` crea o actualiza desde un PDF local; los layouts Visa/Mastercard se detectan solos, para otros hay que indicar `--proveedor`.
- **Google Drive (opcional):** `GOOGLE_DRIVE_FOLDER_ID` y `GOOGLE_SERVICE_ACCOUNT_JSON` (contenido o ruta); nombres y rutas en `integrations/google_drive/naming.py` + hook `drive_target`. Google bloquea el acceso a Drive desde IPs de datacenter (HTTP 403): el agente y Actions usan la API con cuenta de servicio.
- **Extractor de PDF (`integrations/pdf_extractor`):** `pdfplumber` sobre la capa de texto (**no es OCR**); en una descarga lee las 2 primeras páginas, en lote todo el PDF. Reglas comunes en `invoice_data.py`; cada proveedor agrega patrones prioritarios con `invoice_data_patterns` (importe, vencimiento actual, próximo, identificador), con los comunes como alternativa; patrones específicos para AySA, Claro, Edenor, Edesur y Metrogas (en Metrogas se prioriza la fecha de pago junto a `FECHA DE VENCIMIENTO` sobre la fecha CESP del pie). Tarjetas (`card_statement.py`): parsers de Visa, Visa Nación y Mastercard BBVA/ICBC (el ICBC también reconoce `Estado de cuenta al`, `Saldo actual` y fechas de vencimiento/cierre) con banco, importes ARS/USD y cierres; un layout no reconocido no se asume Visa; durante una descarga manda el banco de la cuenta seleccionada. Importes como `Decimal`, fechas `YYYY-MM-DD`. `estimated_next_due_date_months` estima el próximo vencimiento solo si no hay uno explícito y sí el actual (si el día no existe en el mes destino, último día; Medifé: 1 mes). Hay `parsing.py` (importes) y `csv_export.py`.

## 7. Navegador y sesiones
> **TL;DR:** `core.browser.browser_channel()` decide el navegador en un solo lugar; los perfiles persistentes no se borran.

- Canal: Chrome del sistema por defecto (evita el error de VC++ en Windows); en Linux ARM, Chromium de Playwright; `PROVIDERS_BROWSER_CHANNEL` y `PROVIDERS_BROWSER_EXECUTABLE` lo fuerzan; si el canal pedido no existe, cae a Chromium de Playwright. No lanzar navegadores por cuenta propia ni usar CDP.
- Windows: `asyncio.ProactorEventLoop()` (el selector no soporta subprocesos de Playwright); no usar Unicode especial en `print()` (consola cp1252).
- Perfiles persistentes: `.chrome_profile/<alias>-<id>-<hash>` (agente) y `.sessions/`; contienen cookies y sesiones: **no borrarlos como limpieza**. `.pytest_cache/` y `.tmp/` sí son regenerables. Un perfil no se abre dos veces (`SingletonLock`; el agente falla con un mensaje claro).
- `playwright-stealth` se importa de forma diferida solo para portales que lo piden (Medifé); es un hallazgo por portal, no un default.

## 8. Configuración y secretos
> **TL;DR:** `.env` solo con opciones no secretas; las claves van por entorno.

| Variable | Uso |
|---|---|
| `PROVIDERS_CREDENTIALS_KEY` | Clave Fernet (entorno del proceso; en la VM `~/.providers-agent.env`; en Actions, secret) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Sincronización y agente (acceso total: cuidarla) |
| `VM_APPROVAL_KEY` | Verifica la firma de los comandos de la VM |
| `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` | Drive (opcional) |
| `AIRTABLE_*` | Airtable (opcional) |
| `PROVIDERS_BROWSER_CHANNEL`, `PROVIDERS_BROWSER_EXECUTABLE`, `PROVIDERS_PROFILE_FALLBACK`, `PROVIDERS_PROMPT_TIMEOUT`, `AGENT_NAME`, `AGENT_RUN_TIMEOUT_MIN`, `MEDIFE_STEALTH_ENABLED`, `VISA_BANCO`, `MASTERCARD_BANCO` | Ajustes no secretos |

Generar la clave: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` y guardarla en el gestor de claves (PowerShell: `[Environment]::SetEnvironmentVariable("PROVIDERS_CREDENTIALS_KEY", $key, "User")`). Dependencias: `pip install -r requirements.txt` (Playwright ≥ 1.48, playwright-stealth, httpx, pydantic-settings, tenacity, pyairtable, google-api-python-client, cryptography, pdfplumber).

## 9. Contrato con la base (la define el repo finanzas)
> **TL;DR:** providers lee y escribe solo estas tablas; renombrarlas exige coordinar con `aleobb/finanzas`.

`comprobantes`, `conceptos` (`"Identificador"`), `proveedor_portales`, `portal_perfiles`, `ejecuciones`, `ejecucion_logs`, `ejecucion_prompts`, `vm_comandos`; buckets privados `Comprobantes` (10 MB) y `ejecucion-logs` (5 MB). `programaciones` y las vistas las usa solo la web. Esquema completo y migraciones: `docs/` de `aleobb/finanzas`.

## 10. Pruebas y calidad
> **TL;DR:** `python -m pytest` y `git diff --check` antes de cerrar; línea base 200 pasaron, 30 omitidos; CI en `tests.yml`.

- Compartidas en `tests/`; las de un portal en `providers/<portal>/tests/`. Como esas carpetas no son paquetes, **los módulos de test deben tener nombres únicos** en todo el árbol. `visa_debug_session.py` y `visa_test_switch.py` son utilitarios manuales, no pruebas.
- `pytest` no está en `requirements.txt` (`pip install pytest`). 30 tests quedan omitidos por falta de PDFs de muestra (tienen datos personales y no van al repo; usar PDFs sintéticos).
- Los cambios en este repo **solo agregan funciones**: no cambian la forma de ejecutar desde la consola local.

## 11. Troubleshooting
> **TL;DR:** causas ya vistas.

| Síntoma | Causa → solución |
|---|---|
| Login manual funciona y el automatizado falla | `--listar --debug --nosession` para separar login fresco de sesión/JWT cacheados; comparar manual vs automatizado (status, content-type, CORS de OPTIONS y POST, errores de consola); cambiar **una** señal a la vez (User-Agent, stealth, perfil, flags); nunca registrar passwords, cookies, `Authorization` ni JWT |
| Una API cross-origin falla en Chrome automatizado | Distinguir OPTIONS de POST: un OPTIONS correcto no prueba que el POST traiga los headers CORS; revisar status, content-type y `Access-Control-Allow-Origin`; un 200 puede ser HTML de error; no reemplazar el flujo del frontend por un POST directo sin verificar contrato, cookies y headers dinámicos |
| `BrowserType.launch: spawn UNKNOWN` | Usar `channel="chrome"` |
| `NotImplementedError` en Windows | `asyncio.ProactorEventLoop()` |
| `ModuleNotFoundError: playwright` | Activar `.venv` e instalar `requirements.txt` |
| `playwright install --with-deps` falla (`libasound2`, Ubuntu 24.04) | Paquetes `t64`; Playwright ≥ 1.48 |
| «Falta PROVIDERS_CREDENTIALS_KEY» / «No hay credenciales guardadas para X» | Falta la clave en el entorno, o `--supabase`/`--perfil` usan la SQLite local → lanzar desde la web (agente) o cargar el perfil local |
| El perfil está en uso | Navegador del escritorio y agente con el mismo perfil → cerrar uno |
| Errores GPU/`SharedImage`, `xdg-mime: command not found` | Inofensivos (`--disable-gpu`) |
| Un portal multi-cuenta devuelve la misma factura para cuentas distintas | La API depende de una «cuenta actual» del servidor: cambiarla en la UI antes de consumir la API, o interceptar las respuestas del portal (`NetworkInterceptor`) |
| 403 de Drive desde un servidor | Google bloquea IPs de datacenter → usar la API con cuenta de servicio |
| Airtable no acepta adjuntos por URL | Usar la API de carga directa (ya implementado) |
| pytest: colisión de módulos de test | Nombres únicos en todo el árbol |
