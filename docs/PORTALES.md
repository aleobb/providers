---
id: PRV-POR
titulo: Portales de proveedores y cómo agregar uno
estado: vigente
ultima_revision: 2026-11-21
resumen: Notas técnicas de cada portal soportado (Aysa, Claro, Edenor, Edesur, Mastercard, Medifé, Metrogas, Telecentro, Visa: login, API, descarga, particularidades) y guía paso a paso para agregar un portal nuevo.
fuentes: [código de providers/<portal>/, CLAUDE.md y README anteriores]
relacionados: [PRV-TEC, PRV-OPS, PRV-PEN]
---

# Portales

> Cada sección empieza con un **TL;DR**. Estado de validación de punta a punta vía interfaz web (2026-11-19): solo Metrogas tiene una descarga exitosa registrada; los demás están sin validar (ver `PENDIENTES.md`).

## 1. Resumen
> **TL;DR:** nueve portales; los de nube sin 2FA pueden correr en GitHub Actions, los que piden 2FA, captcha o verificación humana corren en el agente de la VM.

| Portal | Acceso | Descarga | Particularidad |
|---|---|---|---|
| Aysa | Playwright (modal «INICIÁ SESIÓN») | API REST con CSRF + cookies | `AysaOvServiceHub` |
| Claro | OAuth2/OIDC (Keycloak), 2 pasos | popup + httpx con cookies | Stealth desactivado, 403 si hay fingerprint |
| Edenor | email + password | API Widergy con job polling | JWT sin «Bearer», reCAPTCHA v3 |
| Edesur | email + password | Docuprint | Verificación humana → `--debug` |
| Mastercard | email + password + MFA | API REST + cookies | Código Authenticator por consola/web |
| Medifé | documento + password | UI de facturación | `playwright-stealth`, perfil persistente |
| Metrogas | SAML 2.0 (SAP Cloud Identity) | GET directo | `verify=False`, hash routing |
| Telecentro | email + password (solo para el JWT) | 100 % httpx | JWT por cuenta |
| Visa | documento + usuario + password + OTP | API REST | Backend intermitente |

## 2. Aysa (oficinavirtual.web.aysa.com.ar)
> **TL;DR:** API REST con token CSRF y cookies del navegador; archivo `aysa_{AAAA-MM}_{cuenta}_factura.pdf`.
- **Login:** `index.html` → «INICIÁ SESIÓN» (modal) → credenciales → espera del portal autenticado (`portal.web.aysa.com.ar`).
- **API:** `https://portal.web.aysa.com.ar/AysaOvServiceHub/api/v1/ov` con las cookies del navegador. Primero `GET /cuentas` con `X-CSRF-Token: Fetch` para obtener el token; `POST /facturacion/facturas/{cuenta}` lista las facturas (se toma la de mayor `FAEDN`); PDF: `GET /facturacion/factura/pdf/{cuenta}/{NUMERO_INT}/{EXBEL}?action=download`.
- **Archivo:** `aysa_{AAAA-MM}_{cuenta}_factura.pdf`. Patrones de PDF: «cuenta de servicios», «total a pagar» y «total a pagar con recargo hasta el …» (próximo vencimiento).

## 3. Claro (m-miclaro.claro.com.ar)
> **TL;DR:** login Keycloak en 2 pasos con stealth desactivado; descarga por popup + httpx con cookies.
- **Login:** OAuth2/OIDC por Keycloak (`ingreso.claro.com.ar`) en 2 pasos: email → «Continuar» → password → redirige a `/elegirservicio`.
- **Fingerprint:** el login manual funciona pero el automatizado puede recibir HTTP 403 tras enviar el email («Request error»). En `ClaroConfig`: `browser_stealth=False`, `browser_user_agent=None`, `browser_args=["--disable-blink-features=AutomationControlled"]` (verificado; limitado a Claro).
- **Sesión persistente:** `.chrome_profile/claro` puede conservar la sesión; `portal_url` puede pasar por `/home` antes de `elegirservicio`: esperar el formulario de email o la URL autenticada y, si ya llegó a `elegirservicio`, omitir email/password.
- **Cuentas:** `/elegirservicio` muestra botones DIV (`role="button"`) por línea; cada clic navega a `/{base64(billNumber)}/home` y de ahí se extrae el `billNumber` (nº de línea; p. ej. `1157004151` ↔ `MTE1NzAwNDE1MQ==`). Las líneas son independientes (no hay cuenta activa que cambiar).
- **Descarga:** `/{base64(billNumber)}/factura` → clic en «Descargar factura en PDF» → `page.expect_popup()`; el popup puede quedar en `about:blank`: esperar con `popup.wait_for_url` hasta `/facturas/ultima` (`/factura/back/public/facturas/ultima?t={token}`) y bajar con httpx usando las cookies del navegador. Período: respuesta de `/factura/back/cuenta/ciclos` al cargar la factura.

## 4. Edenor (edenordigital.com)
> **TL;DR:** API Widergy con JWT sin «Bearer» y job polling; el PDF llega en base64.
- **Login:** `/ingreso/bienvenida` → botón de clase `c0039` → `/ingreso/ingresar` → email + password en la misma página → «Ingresar». reCAPTCHA v3 invisible.
- **API:** Widergy UtilityGo `utilitygo.widergy.com/api/v1`; headers `utility-id: 19`, `channel: web` y `Authorization` con el JWT crudo (**sin** «Bearer»). Un `NetworkInterceptor` captura `auth_token`, `account_id` y `client_number` del tráfico. Cuentas: `GET /api/v1/accounts`.
- **Descarga:** API asíncrona con job polling (202 → poll → resultado): `/bills/printed_bill?client_number={}&external_id={}`; el PDF llega en base64 (`{'base64': '…'}`). Si `bills` viene vacío, usar `/accounts/{id}/bills/last` con polling. Un 400 suele ser un header equivocado (`utility-id`, `channel` o «Bearer» de más).

## 5. Edesur (ov.edesur.com.ar)
> **TL;DR:** descarga por Docuprint; si pide verificación humana, usar `--debug`.
- **Login:** email + password en `/login` → «Ingresar» → `/mi-cuenta`. Angular SPA con Material y JS muy ofuscado.
- **Auth:** JWT en `localStorage.token`, enviado como `Bearer` a `ed.edesur.com.ar/api/` con header `x-origin-channel`. Cuentas desde `localStorage.LISTA_CUENTAS_DETALLE` (`contractAccount`, `meterNumber`, `name`, `address`).
- **Descarga:** «Descargar» → `window.open` a `edesur.docuprint.com/home/download/{token}` → verificación humana de Cloudflare/reCAPTCHA si aparece → botón «Descarga tu factura digital» → PDF. Edesur interpreta su URL alternativa y obtiene sus enlaces de Docuprint de Gmail con `providers/edesur/gmail_reader.py`.
- **Importante:** si aparece la verificación humana, ejecutar con `--debug` (o Debug desde la web) y completarla a mano; Edesur usa Chrome sin stealth ni User-Agent sobrescrito y la descarga sigue cuando se habilita el botón, sin pulsar el captcha automáticamente.

## 6. Mastercard / Mis Consultas (misconsultas.com.ar)
> **TL;DR:** MFA obligatorio (Authenticator); API con Bearer + cookies.
- **Login:** `#email` + `#passw` en `/socios/login` → `button[type="submit"]`. **MFA obligatorio:** se pide el código vigente de la app Authenticator (consola o consulta en la web), se completa en `#digitosTarjeta` y se envía `/api/api/v1/auth/mfa/validation` con el header `TemporaryToken` → `{token, refreshToken}`. No requiere `--debug`; funciona headless.
- **API** `https://misconsultas.com.ar/api/api`: JWT en cookie `token` + `Authorization: Bearer` + `Platform: WEB`; las llamadas httpx **deben incluir las cookies** del contexto. Tarjetas: `GET /v2/creditCard/cards`; resúmenes: `POST /v2/creditCard/latestSummaryStatus {cardNumberM}` (ordenados desc); PDF: `POST /v2/creditCard/monthlySummaryPdf {cardNumberM, statementDate}`.
- **Archivo:** `mastercard_{statementDate}_{last4}_resumen.pdf`. Tarjetas sin resumen (p. ej. adicionales sin actividad) → `InvoiceNotFoundError`. Perfil: email y contraseña.

## 7. Medifé (medife.com.ar/portal)
> **TL;DR:** login por documento; `playwright-stealth` y perfil persistente.
- **Acceso:** formulario de documento: tipo (DNI, CI, LE, LC, PP; vacío = DNI), número y contraseña. Los perfiles viejos con email deben editarse (en `--gestionar-credenciales` o en la web) para completar número y tipo; la contraseña se conserva. No cambia de cliente dentro de un mismo acceso: otros accesos = perfiles separados.
- **Descarga:** `facturaciones?tab=consulta`; baja la última factura del cliente activo (el portal ofrece los últimos tres períodos); el período «mes AAAA» se convierte a `AAAA-MM`. Archivo `medife_{AAAA-MM}_{cliente}_factura.pdf`.
- **Navegador:** Playwright con Chrome nativo y `playwright-stealth` aplicado al contexto persistente **antes** de navegar; conserva User-Agent, plataforma y GPU reales. Desactivar solo en Medifé con `MEDIFE_STEALTH_ENABLED=false`. El perfil persistente conserva la sesión (evitar `--nosession` para reutilizarla); no garantiza que el portal deje de pedir verificación humana (usar `--debug`/`--ingresar`).

## 8. Metrogas (registro.micuenta.metrogas.com.ar)
> **TL;DR:** SAML con routing por hash; GET directo con `verify=False`.
- **Login:** SAML 2.0 con SAP Cloud Identity: entrada → «Iniciar Sesión» → `#j_username` → `#logOnFormSubmit` → `#j_password` → `#logOnFormSubmit` → sondear la URL hasta el redirect al portal (routing por hash `#Home-show`: usar polling de `page.url`, no `wait_for_url`, que da timeout).
- **Cuentas:** botón «Cambiar» abre un modal; se parsean los `li` con regex (N.º Cliente, Titular, Medidor).
- **Descarga:** GET directo `/sap/fiori/ovcustdashboard//OvServiceHub/api/v1/M360/invoice/isu/lastInvoice/{client_number}` con httpx y `verify=False` (certificado corporativo).

## 9. Telecentro (telecentro.com.ar/sucursal-virtual)
> **TL;DR:** el navegador solo captura el JWT; la descarga es 100 % httpx con un JWT por cuenta.
- **Login:** email + password en `/sucursal-virtual/login`. Playwright solo captura el JWT inicial (interceptor de los requests a `apiext`; el JWT lleva `nameidentifier=clienteId`) y el navegador se cierra enseguida. Si el perfil ya tiene sesión, el login omite el formulario y captura el JWT de los requests del home. Fresh login resuelto con `browser_stealth=False` y `--disable-blink-features=AutomationControlled` (hallazgo propio de Telecentro).
- **API:** `apiext.telecentro.net.ar`, todo con JWT puro (sin cookies). Cuentas: `GET /bss/vta/clientes/v1/byEmail?email={email}`. Descarga 100 % httpx: (1) cambiar JWT por cuenta con `POST /sv/api/refreshtokenByClient {clienteid}` (el nuevo JWT lleva el `clienteId` de la cuenta); (2) `GET /bss/fac/facturacion/v1/comprobantes/cantidad/18?tipoFacturacion=S` (filtra por el claim del JWT, **ignora** `clienteId` como query param; lista de la más reciente a la más antigua con `key`, `fechaEmision`, `link`); (3) `GET https://telecentro.com.ar/tlc/facturas/show/{key}` con el JWT de la cuenta (sin cookies; verificado 2026-04-30). Requiere `verify=False`.
- Si dos cuentas devuelven la misma factura, es que se está usando el `clienteId` del query param en vez del JWT de la cuenta. Debug/Ingresar usan `PROVIDERS_PROFILE_FALLBACK=1` si falta `telecentro_default_clone`.

## 10. Visa / Prisma (mycards.prismamediosdepago.com)
> **TL;DR:** login con OTP por email; el backend de Prisma se cae seguido (no es un problema de credenciales).
- **Login:** formulario con `select#documentType` (DNI), `#documentNumber`, `#username` (type=password) y `#password` → «Ingresar». Perfil: DNI, usuario y contraseña.
- **API** `https://mistarjetas.prismamediosdepago.com/socios/auth`: `POST /api/auth/login` → `POST /api/auth/login/otp` (OTP de 6 dígitos por email, vence en ~2 min, se pide por consola/web); token en la cookie `token` (js-cookie), refresh por `/api/v1/auth/refresh`.
- **Servidor caído:** `/health` con estado DOWN indica caída del backend (HTTP 500 en todo); si el cuerpo contiene «intentá nuevamente», «error inesperado», etc. se lanza `ServerUnavailableError` en vez de esperar 60 s: no es un problema de credenciales. Estrategias de descarga, selector de tarjeta, logout y período viven en módulos internos separados. Estado: implementado, backend de Prisma intermitente.

## 11. Cómo agregar un portal
> **TL;DR:** copiar un portal parecido, registrarlo, definir patrones de PDF y pruebas, dar de alta el portal y su perfil en Supabase, probar con Debug y recién después programar.

1. **Módulo** `providers/<portal>/` copiando uno parecido (nube sin 2FA: Metrogas; con 2FA/MFA: Visa, Mastercard, Edesur): `config.py` (clase que extiende `BaseProviderConfig`, `env_prefix="<NOMBRE>_"`), `login.py`, `accounts.py` (`fetch_accounts`), `invoice.py`, `__init__.py` (clase `<Portal>Provider(Provider)` con los 4 métodos obligatorios + `register(...)`) y `tests/`.
2. **Registrar:** `from . import <portal>  # noqa: F401` en `providers/__init__.py`.
3. **Credenciales:** declarar `credential_fields` en el módulo (deben coincidir con `proveedor_portales.campos_login`).
4. **Navegador:** siempre `core.browser`; si necesita perfil persistente, `can_resume_session = True`.
5. **Datos del PDF:** `invoice_data_patterns` (identificador de cuenta, vencimiento actual y próximo, importes) probados con PDFs **sintéticos**.
6. **Pruebas:** `providers/<portal>/tests/test_<portal>_*.py` con nombres únicos (login con mocks, cuentas, descarga, extracción) y un test que proteja la frontera del core; `python -m pytest`.
7. **Alta en Supabase** (ver `docs/OPERACIONES.md` §4): fila en `proveedor_portales` (`codigo` = `name`, `modo`, `requiere_2fa`, `campos_login`) y perfil de credenciales desde la web de finanzas. Un portal con captcha o 2FA va con `modo = local_asistido` y `requiere_2fa = true` (corre en el agente, no en Actions).
8. **Probar en la VM:** Debug (navegador visible) → Descargar → verificar el comprobante (concepto + vencimiento, sin duplicar) y el PDF en Storage.
9. **«Estable»:** varias descargas de punta a punta exitosas con el comprobante verificado; no programar antes.
10. **Documentar:** una sección en este archivo, `CHANGELOG.md` de este repo (y el de finanzas si cambia la web) y `PENDIENTES.md`.
