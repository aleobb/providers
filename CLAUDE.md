# Descargador Unificado de Facturas de Servicios

## Descripcion del Proyecto
Script Python para loguearse en portales web de proveedores de servicios (con usuario/clave) y descargar la ultima factura PDF al disco local. Soporta multiples proveedores y multiples cuentas por proveedor.

## Arquitectura

### Estructura de Archivos
```
C:\Users\Alejandro\.claude\Code\
├── main.py                          # Entry point -> core.cli.main()
├── .env                             # Credenciales por proveedor
├── requirements.txt                 # playwright, python-dotenv, httpx, pydantic-settings, tenacity
├── core/
│   ├── __init__.py
│   ├── accounts.py                  # Account dataclass + select_account()
│   ├── browser.py                   # BrowserSession (system Chrome via channel="chrome")
│   ├── cli.py                       # CLI unificado (--proveedor, --todas, --listar, --debug, --cuenta)
│   ├── config.py                    # BaseProviderConfig (pydantic-settings)
│   ├── exceptions.py                # Jerarquia de errores (InvoiceDownloaderError, LoginError, ServerUnavailableError, etc.)
│   ├── provider.py                  # Protocol con 4 metodos: get_config, login, fetch_accounts, download_invoice
│   ├── registry.py                  # Provider registry con register(), get_provider(), all_providers()
│   ├── run_log.py                   # Log persistente de ejecuciones (./ejecucion.log)
│   └── utils.py                     # unique_path() para evitar sobreescribir archivos
├── providers/
│   ├── __init__.py                  # Auto-import de todos los proveedores (trigger register())
│   ├── edenor/                      # Proveedor Edenor
│   ├── edesur/                      # Proveedor Edesur
│   ├── metrogas/                    # Proveedor Metrogas
│   ├── telecentro/                  # Proveedor Telecentro
│   ├── claro/                       # Proveedor Claro
│   ├── visa/                        # Proveedor Visa (Prisma)
│   └── mastercard/                  # Proveedor Mastercard (Mis Consultas)
├── facturas/                        # Directorio de salida de PDFs
└── _legacy/                         # Paquetes independientes viejos (edenor_downloader, metrogas_downloader)
```

### Patron de Diseno
- **Provider Protocol** (`core/provider.py`): interfaz runtime_checkable con 4 metodos
- **Provider Registry** (`core/registry.py`): dict name->class con register()
- **Auto-registration**: cada `providers/<nombre>/__init__.py` llama `register()` al importarse
- **pydantic-settings BaseSettings**: config con env_prefix por proveedor (EDENOR_, METROGAS_, EDESUR_, MASTERCARD_, etc.)
- **ServerUnavailableError** (`core/exceptions.py`): excepcion para errores transitorios de servidor → se loguea y continua con el siguiente proveedor
- **Run Log** (`core/run_log.py`): log persistente append-only en `./ejecucion.log` con estado de cada descarga (OK/ERROR/SERVER_DOWN)

### Decisiones Tecnicas Clave
- **Playwright async** para automatizacion del browser (necesario por captchas y flujos complejos)
- **System Chrome** (`channel="chrome"`) en vez de Chromium bundled — evita error de VC++ redistributable en Windows
- **Windows ProactorEventLoop**: requerido para subprocesos de Playwright en Windows (SelectorEventLoop no los soporta)
- **Archivos PDF** se guardan en `./facturas/` con nombre: `{proveedor}_{periodo}_{cliente}_factura.pdf`

## Proveedores

### Edenor (edenordigital.com)
- **Login**: pagina /ingreso/bienvenida -> click boton class c0039 -> /ingreso/ingresar -> email + password en misma pagina -> "Ingresar"
- **API Backend**: Widergy UtilityGo en `utilitygo.widergy.com/api/v1`
- **Headers requeridos**: `utility-id: 19`, `channel: web`, Authorization como JWT crudo (SIN prefijo "Bearer")
- **Cuentas**: GET /api/v1/accounts con interceptor de red que captura auth_token
- **Descarga**: API asincrona con patron de job polling (202 -> poll -> result). Endpoint: `/bills/printed_bill?client_number={}&external_id={}`. Respuesta PDF en base64: `{'base64': '...'}`
- **Interceptor de red** (`NetworkInterceptor`): captura auth_token, account_id, client_number del trafico API
- **reCAPTCHA v3** (invisible, no requiere interaccion)

### Edesur (ov.edesur.com.ar)
- **Login**: email + password en misma pagina /login, boton "Ingresar", redirige a /mi-cuenta
- **Auth**: JWT en `localStorage.token`, enviado como `Bearer` header
- **API Backend**: `ed.edesur.com.ar/api/` con header `x-origin-channel`
- **Cuentas**: se leen de `localStorage.LISTA_CUENTAS_DETALLE` (se cargan tras login). Campos: contractAccount, meterNumber, name, address
- **Descarga**: click "Descargar" -> window.open a `edesur.docuprint.com/home/download/{token_encriptado}` -> **reCAPTCHA v2** (checkbox, requiere interaccion humana) -> boton "Descarga tu factura digital" -> PDF download
- **IMPORTANTE**: Requiere `--debug` para resolver captcha manualmente. El popup se lleva al frente con `bring_to_front()`
- **Framework**: Angular SPA con Material Design, codigo JS fuertemente obfuscado

### Telecentro (telecentro.com.ar/sucursal-virtual)
- **Login**: email + password en `/sucursal-virtual/login`, boton "Ingresar", redirige a `/sucursal-virtual/home`
- **Auth**: JWT capturado via network interceptor (request header `Authorization: Bearer ...` o response de endpoint `autenticar`). Enviado como `Bearer` header
- **API Backend**: `apiext.telecentro.net.ar`
- **Cuentas**: GET `/bss/vta/clientes/v1/byEmail?email={email}` -> devuelve lista de clientes con `clienteId`, `apellidoNombre`, `domicilio`
- **Descarga**:
  - **CRITICO**: La API `/bss/fac/facturacion/v1/comprobantes/cantidad/18?tipoFacturacion=S&clienteId={}` **IGNORA el query param `clienteId`** y filtra por la sesion del browser (cookies). Para cuentas multiples hay que cambiar la cuenta activa en la UI ANTES de llamar la API
  - **Switch de cuenta**: click en la tarjeta "Número de cliente: XXXX" con icono ↺ a la derecha en el home -> aparece modal/listado -> click en la cuenta target (matchea por client_number, display_name o address)
  - Tras cambiar cuenta, interceptar el response de `comprobantes` que dispara el JS del portal (patron `NetworkInterceptor` como Edenor)
  - PDF: GET `https://telecentro.com.ar/tlc/facturas/show/{key}` donde `key` viene del primer comprobante capturado (ordenados del mas reciente al mas antiguo). Solo requiere cookies
- **SSL**: requiere `verify=False` en httpx
- **SPA**: Angular/Material, requiere `wait_for_load_state("networkidle")` + `asyncio.sleep()` post-navegacion

### Metrogas (registro.micuenta.metrogas.com.ar)
- **Login**: SAML 2.0 via SAP Cloud Identity. Entry page -> "Iniciar Sesion" -> #j_username -> #logOnFormSubmit -> #j_password -> #logOnFormSubmit -> poll URL para redirect a portal
- **Cuentas**: click boton "Cambiar" para abrir modal, parsea `li` items con regex para N Cliente, Titular, Medidor
- **Descarga**: GET directo `/sap/fiori/ovcustdashboard//OvServiceHub/api/v1/M360/invoice/isu/lastInvoice/{client_number}` con httpx
- **SSL**: requiere `verify=False` por certificado corporativo
- **Hash routing**: workaround con polling de `page.url` en vez de `wait_for_url` (hash-based routing #Home-show)

### Claro (m-miclaro.claro.com.ar)
- **Login**: OAuth2/OIDC via Keycloak (ingreso.claro.com.ar) en 2 pasos: email → "Continuar" → password → submit → redirect a /elegirservicio
- **Cuentas**: /elegirservicio muestra botones DIV (`role="button"`) por cada linea. Click en cada uno navega a `/{base64(billNumber)}/home` del cual se extrae el billNumber (numero de linea celular)
- **billNumber**: numero de linea codificado en base64 en el path de la URL. Ej: `1157004151` → `MTE1NzAwNDE1MQ==` (URL-encoded como `MTE1NzAwNDE1MQ%3D%3D`)
- **Descarga**: navegar a `/{base64(billNumber)}/factura` → click `:text("Descargar factura en PDF")` → interceptar popup con `page.expect_popup()` → URL del popup es `/factura/back/public/facturas/ultima?t={token}` → httpx GET con cookies del browser
- **Periodo**: interceptado del response de `/factura/back/cuenta/ciclos` (GET 200) al cargar la pagina de factura
- **Multi-cuenta**: cada linea es independiente; el portal no requiere switch de cuenta activa (el billNumber esta en la URL)

### Visa / Prisma Medios de Pago (mycards.prismamediosdepago.com)
- **Login**: formulario con `select#documentType` (value=DNI), `#documentNumber`, `#username` (type=password), `#password` → click "Ingresar"
- **API base**: `https://mistarjetas.prismamediosdepago.com/socios/auth`
- **Auth API**: `POST /api/auth/login` (credenciales) → `POST /api/auth/login/otp` (verificacion OTP)
- **Token**: cookie `token` gestionada por js-cookie (ta.set/get/remove). Refresh via `/api/v1/auth/refresh` con refreshToken
- **Health check**: `/health` → status DOWN indica outage del backend DB (causa HTTP 500 en todos los endpoints)
- **OTP**: 6 digitos por email. Se ingresa en consola. Expira ~2 minutos
- **Deteccion de servidor caido**: si el body contiene "intentá nuevamente", "error inesperado", etc. → lanza `ServerUnavailableError` en vez de esperar 60s
- **Credenciales .env**: `VISA_DOCUMENTO_NACIONAL_DE_IDENTIDAD`, `VISA_USUARIO`, `VISA_PASSWORD`
- **Estado**: implementado, pero el backend de Prisma esta intermitentemente caido (HTTP 500 en /api/auth/login, /health → DB DOWN)

### Mastercard / Mis Consultas (misconsultas.com.ar)
- **Login**: email (`#email`) + password (`#passw`) en `/socios/login` → click `button[type="submit"]`
- **MFA obligatorio por SMS**: POST `/api/api/v1/auth/login` → `{temporaryToken, phoneLastNumbers}` → usuario ingresa codigo en el browser (campo `#digitosTarjeta`) → POST `/api/api/v1/auth/mfa/validation` con header `TemporaryToken` → `{token, refreshToken}`
- **IMPORTANTE**: Requiere `--debug` para que el browser sea visible y el usuario pueda ingresar el codigo SMS
- **API base**: `https://misconsultas.com.ar/api/api`
- **Auth**: JWT via cookie `token`, enviado como `Authorization: Bearer {token}`, header `Platform: WEB`
- **Tarjetas**: `GET /v2/creditCard/cards` → `{cards: [{cardNumber, fullName, accountNumber, financialEntity, additional}]}`
- **Resumenes**: `POST /v2/creditCard/latestSummaryStatus` con `{cardNumberM: cardNumber}` → `{summaries: [{statementDate, id, statusId}]}` ordenados desc
- **Descarga PDF**: `POST /v2/creditCard/monthlySummaryPdf` con `{cardNumberM, statementDate}` → blob PDF
- **Cookies**: las llamadas httpx deben incluir las cookies del browser context (necesarias junto con el Bearer token)
- **Archivo PDF**: `mastercard_{statementDate}_{last4}_resumen.pdf`
- **Tarjetas sin resumen**: algunas tarjetas (ej. adicionales sin actividad) retornan summaries vacio → `InvoiceNotFoundError`
- **Credenciales .env**: `MASTERCARD_EMAIL`, `MASTERCARD_PASSWORD`
- **Cuidado**: el .env tenia `Mastercard__PASSWORD` (doble underscore) que no matcheaba el env_prefix — corregido a `MASTERCARD_PASSWORD`

## Variables de Entorno (.env)
```
EDENOR_EMAIL=...
EDENOR_PASSWORD=...
METROGAS_EMAIL=...
METROGAS_PASSWORD=...
EDESUR_EMAIL=...
EDESUR_PASSWORD=...
TELECENTRO_EMAIL=...
TELECENTRO_PASSWORD=...
CLARO_EMAIL=...
CLARO_PASSWORD=...
VISA_DOCUMENTO_NACIONAL_DE_IDENTIDAD=...
VISA_USUARIO=...
VISA_PASSWORD=...
MASTERCARD_EMAIL=...
MASTERCARD_PASSWORD=...
```

## Uso
```bash
# Descargar todas las facturas de un proveedor
python main.py --proveedor edenor --todas
python main.py --proveedor edesur --debug --todas    # Edesur requiere --debug por captcha
python main.py --proveedor mastercard --debug --todas  # Mastercard requiere --debug por SMS OTP

# Todos los proveedores a la vez
python main.py --todos-proveedores --todas

# Listar cuentas
python main.py --proveedor edenor --listar

# Una cuenta especifica
python main.py --proveedor metrogas --cuenta 12345678

# Modo visual (debug)
python main.py --proveedor edenor --debug --todas
```

## Errores Comunes y Soluciones
- **BrowserType.launch: spawn UNKNOWN**: usar `channel="chrome"` (system Chrome)
- **NotImplementedError en Windows**: usar `asyncio.ProactorEventLoop()` en vez de `asyncio.run()`
- **Edenor API 400**: verificar headers `utility-id: 19`, `channel: web`, y que Authorization NO tenga "Bearer"
- **Edenor bills vacio**: usar `/accounts/{id}/bills/last` con job polling en vez de `/bills`
- **Metrogas SSL error**: usar `verify=False` en httpx
- **Metrogas wait_for_url timeout**: usar polling de `page.url` (hash routing)
- **Edesur captcha**: requiere `--debug` para resolver manualmente; el bot intenta click automatico pero reCAPTCHA v2 lo detecta
- **Telecentro misma factura en cuentas distintas**: sintoma de que el `clienteId` del query param se esta ignorando. La API filtra por sesion del browser — hay que switchear la cuenta activa en la UI (tarjeta "Número de cliente" con icono ↺) antes de llamar la API o interceptar el response del portal
- **Portales multi-cuenta con API session-based**: patron general — si pasar el ID como query param no cambia el resultado, la API depende de un "current account" server-side. Solucion: manipular la UI para switchear la cuenta activa antes de consumir la API, o interceptar los responses que el portal hace naturalmente (patron `NetworkInterceptor`)
- **Visa backend caido (HTTP 500)**: el healthcheck `/health` confirma DB DOWN. Hasta que Prisma lo restaure, el script lanza `ServerUnavailableError`, lo loguea en `ejecucion.log` y continua. NO es problema de credenciales
- **Mastercard doble underscore en .env**: `Mastercard__PASSWORD` (doble _) no matchea `env_prefix="MASTERCARD_"`. Debe ser `MASTERCARD_PASSWORD` (un solo _)
- **Mastercard sin SMS code**: requiere `--debug` para que el browser sea visible y el usuario pueda ingresar el OTP SMS manualmente en campo `#digitosTarjeta`
- **UnicodeEncodeError en consola Windows (cp1252)**: no usar caracteres Unicode especiales (box drawing, tildes) en `print()`. Usar ASCII simple para banners

## Como Agregar un Nuevo Proveedor
1. Crear directorio `providers/<nombre>/`
2. Crear `config.py` con clase que extienda `BaseProviderConfig` y `env_prefix="<NOMBRE>_"`
3. Crear `login.py` con flujo de autenticacion
4. Crear `accounts.py` con funcion para listar cuentas
5. Crear `invoice.py` con logica de descarga de PDF
6. Crear `__init__.py` con clase Provider que implemente los 4 metodos y llame `register("<nombre>", ProviderClass)`
7. Agregar `from . import <nombre>` en `providers/__init__.py`
8. Agregar credenciales en `.env`: `<NOMBRE>_EMAIL=...`, `<NOMBRE>_PASSWORD=...`
