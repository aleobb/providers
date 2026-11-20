# Guía: agregar un portal de proveedor (DEV-08)

Objetivo: sumar un proveedor nuevo sin romper los existentes. Contexto: `core/` e `integrations/` son **agnósticos del proveedor**; todo lo específico va en `providers/<portal>/` mediante hooks del contrato `Provider` (`core/provider.py`).

## 1. Estructura del módulo (modelo: `providers/metrogas/`)
```text
providers/<portal>/
├── __init__.py     # clase <Portal>Provider(Provider) + register(...)
├── config.py       # configuración del portal (URLs, selectores, tiempos)
├── login.py        # lógica de login (orquestador)
├── accounts.py     # fetch_accounts(): cuentas/servicios del cliente
├── invoice.py      # descarga de la factura (PDF)
└── tests/          # test_<portal>_*.py (nombres únicos en todo el árbol)
```

## 2. Contrato `Provider`
- Atributos de clase: `name` (código, p. ej. `"metrogas"`), `display_name`, `requires_credentials`, `can_resume_session`, `invoice_date_patterns`, `invoice_data_patterns` (regex para extraer datos del PDF), `estimated_next_due_date_months`, `credential_fields` (por defecto `email` y `password` con `secret=True`).
- Métodos **obligatorios**: `get_config()`, `login(page, context)`, `fetch_accounts(page, context) -> list[Account]`, `download_invoice(page, context, account) -> Path`.
- Hooks opcionales: `configure_credentials`, `configure_profile_session`, `apply_run_options`, `extract_invoice_date`, `extract_card_statement_data`, `drive_target`, `is_session_error`, `try_resume_session`, `save_session`, `logout`, `close`.
- Los **campos de login** deben coincidir con `proveedor_portales.campos_login` (`name`, `label`, `required`, `secret`).

## 3. Pasos
1. **Crear el módulo** copiando la estructura de un portal parecido (nube sin 2FA: Metrogas; con 2FA/MFA: Visa/Mastercard/Edesur).
2. **Registrar:** `register(<Portal>Provider)` al final de `providers/<portal>/__init__.py` y agregar `from . import <portal>  # noqa: F401` en `providers/__init__.py`.
3. **Navegador:** usar siempre `core.browser` (la decisión de canal es única: `browser_channel()`); no lanzar navegadores por cuenta propia. Si el portal necesita perfil persistente, `can_resume_session = True`.
4. **Datos del PDF:** definir `invoice_data_patterns` (identificador de cuenta, vencimiento actual y próximo, importes) y probarlos con PDFs de muestra **sintéticos** (los reales tienen datos personales y no van al repo).
5. **Pruebas:** `providers/<portal>/tests/test_<portal>_*.py`. Nombres de módulo únicos. Probar login (con mocks), cuentas, descarga y extracción. Ejecutar `python -m pytest`.
6. **Alta en Supabase** (desde finanzas; ver `docs/operaciones/runbook-proveedores-y-perfiles.md` §4): fila en `proveedor_portales` (`codigo` = `name`, `modo`, `requiere_2fa`, `campos_login`) y perfil de credenciales por la UI.
7. **Probar en la VM:** acción **Debug** (navegador visible) → **Descargar** → verificar el comprobante creado (concepto + vencimiento, sin duplicar) y el PDF en Storage.
8. **Criterio de «estable»:** ver `docs/qa/plan-pruebas-providers.md` §5. No programar hasta cumplirlo.
9. **Documentar:** CHANGELOG, `docs/arquitectura/modelo-de-datos.md` (lista de portales), matriz de `plan-pruebas-providers.md`.

## 4. Reglas
- No tocar `core/` para resolver algo de un solo portal: usar un hook.
- Los cambios en este repo **solo agregan funciones**; no cambian la forma de ejecutar desde la consola local.
- Nunca imprimir credenciales ni cookies en consola: los logs de ejecución se guardan **sin redacción global**.
- No borrar `.sessions/` ni `.chrome_profile/`.
- Un portal con captcha o 2FA va con `modo = local_asistido` y `requiere_2fa = true` (corre en el agente, no en Actions).
