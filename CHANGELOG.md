# Changelog

Una entrada por cambio, la más reciente arriba. El historial anterior está en Git.

## 2026-11-21 — Documentación propia e independiente del repo
- Nueva documentación autosuficiente: `AGENTS.md` (guía y reglas), `README.md` (puesta en marcha y uso) y `docs/` con `TECNICO.md`, `PORTALES.md`, `OPERACIONES.md`, `DECISIONES.md` y `PENDIENTES.md` (versión productiva vigente, `resumen` en el frontmatter y TL;DR por sección).
- `CLAUDE.md` y `.github/copilot-instructions.md` pasan a ser punteros a `AGENTS.md`; la guía de portales y el README de `deploy/oracle/` se integran en `docs/PORTALES.md` y `docs/OPERACIONES.md`. Se corrigió contenido desactualizado (noVNC, Aysa y Medifé ausentes, referencias a documentos de finanzas inexistentes).
- `tools/docs_check.py` y workflow `docs-check.yml`: frontmatter, enlaces, IDs, TL;DR y patrones de secretos.
- Línea base de la VM verificada el 2026-11-21 (ver `docs/OPERACIONES.md` §2).

## 2026-11-21 — Se elimina el flujo mensual «Descargar Facturas»
- Se borra `.github/workflows/descargar-facturas.yml` (cron del día 5 con credenciales planas en Secrets); lo reemplaza la interfaz web de ejecuciones.
