# AGENTS.md — providers

Guía para asistentes de IA. Las normas de este repo están en [`CLAUDE.md`](CLAUDE.md) y [`.github/copilot-instructions.md`](.github/copilot-instructions.md): **léelas primero**.

- Proyecto completo y documentación: repo `aleobb/finanzas` (`AGENTS.md` y `docs/`). Arquitectura de Providers: `docs/arquitectura/providers-ejecuciones.md`.
- Rama por defecto: **`master`**. Cada cambio se commitea y se sube; los cambios aquí **solo agregan funciones** (no cambian la ejecución por consola).
- Antes de cerrar: `python -m pytest` y `git diff --check`. Línea base (2026-11-19): 200 pasaron, 30 omitidos.
- **Secretos:** nunca en archivos, commits ni logs. `.sessions/`, `.chrome_profile/` y `.credentials/` son sensibles: no borrarlos ni subirlos.
- Agregar un portal: [`docs/guia-agregar-portal.md`](docs/guia-agregar-portal.md).
- VM Oracle: [`deploy/oracle/README.md`](deploy/oracle/README.md). Las acciones en la VM se piden por `vm_comandos` y las aprueba Ale.
