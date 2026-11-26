---
id: PRV-DEC
titulo: Decisiones vigentes de providers
estado: vigente
ultima_revision: 2026-11-21
resumen: Decisiones técnicas vigentes del repo providers (qué y por qué), lo descartado en una línea y los riesgos aceptados.
fuentes: [código, pedidos de Ale 2026-11, registro del repo finanzas]
relacionados: [PRV-TEC, PRV-OPS, PRV-PEN]
---

# Decisiones

> Una fila por decisión; si cambia, editar la fila (estado + fecha). El detalle histórico está en Git.

## 1. Vigentes
> **TL;DR:** núcleo agnóstico, navegador decidido en un lugar, credenciales cifradas con Fernet, agente portable con Actions de respaldo y comandos de la VM con aprobación humana.

| # | Decisión | Estado | Fecha |
|---|---|---|---|
| P-01 | **Playwright async** (necesario por captchas y flujos complejos) + httpx para descargas por API cuando el portal lo permite | aceptado | — |
| P-02 | **`core/` e `integrations/` agnósticos del proveedor**; lo específico va en `providers/<portal>/` por hooks del contrato `Provider` | aceptado | 2026-11 |
| P-03 | **Un solo lugar decide el navegador:** `browser_channel()` (Chrome del sistema; Chromium de Playwright en Linux ARM); sin CDP | aceptado | 2026-11-17 |
| P-04 | **Credenciales cifradas con Fernet** (SQLite local y `portal_perfiles.credenciales_enc`), clave siempre fuera de la base; reemplaza a Vault | aceptado | 2026-11-15 |
| P-05 | **Agente portable** (PC y VM) con GitHub Actions de respaldo para portales de nube sin 2FA | aceptado | 2026-11 |
| P-06 | **Escritorio KasmVNC** tras Cloudflare Tunnel + Access (sin noVNC); SSH 22 de respaldo | aceptado | 2026-11-16 |
| P-07 | **Comandos de la VM con aprobación humana y firma HMAC**, un solo uso | aceptado | 2026-11-17 |
| P-08 | **Rama `master`**, push directo, sin PRs; los cambios solo agregan funciones (no alteran la ejecución por consola) | aceptado | 2026-11-15 |
| P-09 | **Logs de ejecución en Supabase** (`ejecucion_logs` + bucket); en la VM, journal | aceptado (límites ⚠) | 2026-11 |
| P-10 | **La sincronización nunca crea conceptos**; un comprobante = concepto + vencimiento actual | aceptado | 2026-11 |
| P-11 | **Autonomía documental:** este repo mantiene su propia documentación (aunque repita algo de finanzas) | aceptado | 2026-11-21 |

## 2. Descartado (una línea)
> **TL;DR:** lo siguiente se evaluó y se descartó.

Vault de Supabase para credenciales · noVNC/TigerVNC como escritorio principal · flujo mensual `Descargar Facturas` con credenciales planas en Secrets (eliminado el 2026-11-21) · lanzar navegadores por cuenta propia o usar CDP · stealth global (solo por portal que lo necesite).

## 3. Riesgos aceptados
> **TL;DR:** los logs solo redactan los secretos que el proceso conoce y los comandos de la VM pueden usar `sudo`.

Logs de ejecución con redacción parcial (`core/redact.py` tapa credenciales, claves del entorno, OTP/MFA y tokens conocidos; un dato sensible de otro tipo, como una cookie, sí queda guardado) · `sudo` sin contraseña en comandos de la VM, mitigado por la aprobación manual · SSH 22 abierto como respaldo · una misma clave Fernet para todo (admite rotación con varias claves, ver `docs/OPERACIONES.md` §8).
