# AGENTS.md — providers

Repo `aleobb/providers` (rama **`master`**): descarga facturas de portales de servicios y tarjetas (CLI Python + Playwright), y contiene el **agente** que atiende los pedidos de la interfaz web del repo `aleobb/finanzas` y los comandos aprobados de la VM Oracle. Un único usuario: Ale. Idioma de trabajo: **español**. Respuestas concisas y directas.

Este repo es **autosuficiente**: toda su documentación está aquí. Solo la base de datos (esquema, migraciones) y la web las define `aleobb/finanzas`.

## Qué leer según la tarea (no leas todo)
Cada documento tiene `resumen` en el frontmatter y un **TL;DR** por sección.

| Si tu tarea es… | Lee |
|---|---|
| Entender la arquitectura, el CLI, las credenciales, las ejecuciones, el extractor o depurar | `docs/TECNICO.md` |
| Tocar un portal o agregar uno nuevo | `docs/PORTALES.md` |
| Operar la VM, el agente, los workflows, los comandos aprobados o rotar claves | `docs/OPERACIONES.md` |
| Saber por qué algo es como es | `docs/DECISIONES.md` |
| Saber qué falta | `docs/PENDIENTES.md` |
| Cambios recientes | `CHANGELOG.md` (lo más reciente arriba) |

Índice: `docs/README.md`. Uso rápido y puesta en marcha: `README.md`. `CLAUDE.md` y `.github/copilot-instructions.md` apuntan a este archivo, para las herramientas que no lo leen solas.

## Protocolo de cambios (obligatorio)
1. Partir **siempre del repo** (clonar con el token que Ale pega en el chat; con git local en la PC, las credenciales de la PC); nunca de zips viejos. Ale trabaja solo y en secuencia desde distintas IAs: al empezar, leer los últimos commits y la cabecera de `CHANGELOG.md` para saber qué hizo la IA anterior.
2. Antes de cerrar: `python -m pytest` y `git diff --check` (línea base 2026-11-19: 200 pasaron, 30 omitidos).
3. Actualizar `CHANGELOG.md` (una entrada por cambio, la más reciente arriba) y el documento de `docs/` afectado **en el mismo commit**. No dupliques información entre documentos.
4. Commit y push directo a `master`, **sin ramas ni PRs**, sea cual sea la IA o persona. Si el push es rechazado: `git pull --rebase`, verificar de nuevo y reintentar; nunca `--force`. Mantener actualizados ambos repos: cada cambio se commitea y se sube. Commits en español con prefijo (`Providers: …`, `Docs: …`, `CI: …`).
5. Los cambios **solo agregan funciones**: no cambian la forma de ejecutar desde la consola local.
6. Si un cambio toca tablas, columnas o buckets que usa este repo (`docs/TECNICO.md` §9), coordinarlo con `aleobb/finanzas`.
7. Cierre de sesión: lo hecho → `CHANGELOG.md`; lo pendiente de este repo → `docs/PENDIENTES.md`; las decisiones → `docs/DECISIONES.md`. La memoria del asistente guarda solo punteros a estos archivos.

## Reglas de diseño (frontera de proveedores)
- `core/` e `integrations/` son **agnósticos**: sin ramas, búsquedas, etiquetas, nombres de variables de entorno ni casos especiales por nombre de proveedor.
- Lo específico de un portal (login y sesión, opciones de ejecución, navegador, metadatos de credenciales, fechas, nombres de Drive, integraciones propias) va en `providers/<portal>/`.
- El comportamiento opcional se expone por el contrato `Provider` como hooks o capacidades tipadas con defaults genéricos; el core orquesta los hooks (nada de `if provider.name == …`, `hasattr` ni fallbacks por nombre).
- Las integraciones compartidas pasan el comportamiento por el contrato y no importan módulos de portales.
- Al cambiar un portal, buscar en `core/`, `integrations/` y otros portales manejo duplicado o por nombre, y agregar tests que protejan la frontera además del comportamiento.
- Los módulos de test tienen **nombres únicos** en todo el árbol.

## Secretos y archivos sensibles — reglas duras
- **Nunca** escribas tokens, claves ni contraseñas en archivos, commits, docs, logs, memoria ni salida de herramientas. Si Ale pega un token en el chat, úsalo en el entorno del comando y no lo repitas; no clones con el token en la URL guardada (usa `git -c http.extraHeader=…`).
- Nunca imprimas credenciales, cookies, `Authorization` ni JWT: los logs de ejecución solo redactan los secretos que el proceso conoce (`core/redact.py`), no cookies ni otros datos sensibles.
- No agregues credenciales de portales a `.env`.
- `.sessions/`, `.chrome_profile/` y `.credentials/` son sensibles: no borrarlos ni subirlos.
- Documenta secretos solo por **nombre y ubicación**; `tools/docs_check.py` busca patrones de secretos.

## Operar la VM (aprobación humana)
Claude no tiene acceso directo. Para ejecutar algo: insertar una fila en `public.vm_comandos` (`comando`, `motivo`, `timeout_s` 5–1800) con el conector de Supabase; Ale la revisa y aprueba en `/vm-comandos`; el agente la ejecuta una vez y Claude lee `estado`, `codigo_salida` y `salida`. Claude no puede aprobar. Detalle: `docs/OPERACIONES.md` §5.

## Verificar antes de afirmar
- Esquema real: conector de Supabase (`list_tables`, `get_advisors`, `list_migrations`).
- El sandbox alcanza `github.com` y `api.github.com`, no `supabase.co` ni `api.cloudflare.com`.
- Si algo no se pudo verificar, decirlo y marcarlo `⚠ A verificar` en la documentación.

## Perfil del usuario
Ale se define como aficionado en desarrollo y despliegue: no domina GitHub y no quiere depender de tareas manuales complejas. Los pasos manuales (Zero Trust, Oracle) se dan **didácticos y paso a paso, sin códigos internos**.
