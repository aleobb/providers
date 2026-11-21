---
id: PRV-PEN
titulo: Pendientes de providers
estado: vigente
ultima_revision: 2026-11-21
resumen: Backlog priorizado del repo providers (validación de portales, Drive, recifrado, redacción de logs, KasmVNC versionado, pruebas) y datos por verificar.
fuentes: [pedidos de Ale 2026-11, línea base de la VM 2026-11-21]
relacionados: [PRV-TEC, PRV-POR, PRV-OPS, PRV-DEC]
---

# Pendientes

> Lo más importante: validar los 9 portales de punta a punta, configurar Drive, versionar KasmVNC y redactar secretos en los logs. Prioridad: **P1** antes del switch desde Airtable · **P2** valioso · **P3** idea.

## 1. Backlog
> **TL;DR:** el seguimiento global del proyecto está en el repo finanzas; aquí solo lo que se resuelve en este repo.

| ID | Ítem | Prio | Estado |
|---|---|---|---|
| PV-01 | Validar de punta a punta los 9 portales y marcarlos «estables» (hoy solo Metrogas con descarga registrada vía interfaz) | P1 | Abierto |
| PV-02 | Configurar Drive en la VM (`GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`) y verificar la copia permanente | P1 | Abierto |
| PV-03 | Redacción global de secretos en los logs de ejecución (`core/managed.py`) | P1 | Abierto |
| PV-04 | `tools/recifrar_credenciales.py` y soporte multi-clave Fernet en el agente Python | P1 | Abierto |
| PV-05 | Versionar la instalación de KasmVNC en `deploy/oracle/` y retirar noVNC/TigerVNC de `instalar.sh` | P1 | Abierto |
| PV-06 | Medifé y Telecentro: confirmar estabilidad del runner `actions` o pasarlos a `agente` | P2 | Abierto |
| PV-07 | PDFs sintéticos para recuperar los 30 tests omitidos y `pytest` en `requirements-dev.txt` | P3 | Abierto |
| PV-08 | `tools/paridad_airtable.py` (comparar un CSV exportado de Airtable contra Supabase) | P2 | Idea |
| PV-09 | Cerrar `rpcbind` (111) en la VM si no se usa; evaluar swap, límite del journal y logrotate de logs propios | P2 | Abierto (hallazgo de la línea base 2026-11-21) |
| PV-10 | Unificar métodos de navegador sin perder lo que funciona | P2 | Parcial (`browser_channel()` hecho) |
| PV-11 | Evaluar orquestador (n8n vs LangGraph/CrewAI/AutoGen); requeriría Docker y swap | P3 | Sin decidir |

## 2. ⚠ por verificar
> **TL;DR:** datos que faltan para cerrar la documentación.

Estado real de los backups de la VM (política de Oracle) · si la VM necesita swap · cobertura de pruebas de cada portal tras PV-01 · si `Node 18` de la VM se usa para algo.
