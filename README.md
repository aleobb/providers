# Descargador de facturas

Aplicacion Python para iniciar sesion en portales de servicios y tarjetas, descargar facturas PDF y, opcionalmente, guardarlas en Google Drive.

## Proveedores

Aysa, Claro, Edenor, Edesur, Mastercard, Medife, Metrogas, Telecentro y Visa.

### Medife

Agregar un perfil de Medife (tipo de documento, número de documento y contraseña)
mediante el gestor de credenciales y ejecutar:

```powershell
python main.py --proveedor medife
```

Descarga la última factura del cliente activo, con nombre
`medife_YYYY-MM_cliente_factura.pdf`. El portal ofrece los últimos tres períodos.
Medife usa Chrome nativo con su User-Agent real y el argumento
`--disable-blink-features=AutomationControlled` para reducir la señal de automatización.
El perfil persistente conserva la sesión entre ejecuciones; evitar `--nosession`
si se quiere reutilizarla. Este ajuste no garantiza que el portal deje de pedir
verificaciones humanas.

El acceso usa el formulario de documento. Tipos admitidos: DNI, CI, LE, LC y PP;
dejar el tipo vacío usa DNI. Si aparece una verificación humana, usar `--debug`
y resolverla manualmente. Los perfiles anteriores con email deben editarse en
`--gestionar-credenciales` para completar el número y tipo de documento;
la contraseña guardada se conserva. `--ingresar` conserva el flujo
común para acceder al portal. Otros accesos se configuran como perfiles separados;
no se cambia automáticamente de cliente dentro de un mismo acceso.

## Configuracion

1. Instalar Python y Google Chrome.
2. Instalar dependencias:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Copiar `.env.example` como `.env` para configuración no secreta opcional (por ejemplo, Google Drive).
4. Configurar una clave Fernet como variable de entorno `PROVIDERS_CREDENTIALS_KEY`. La clave cifra los perfiles de credenciales guardados en SQLite; no la guardes en la base ni la subas al repositorio. Conserva una copia segura: sin esa clave no se podrán recuperar los perfiles. En PowerShell:

   ```powershell
   $key = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   [Environment]::SetEnvironmentVariable("PROVIDERS_CREDENTIALS_KEY", $key, "User")
   $env:PROVIDERS_CREDENTIALS_KEY = $key
   ```

5. Ejecutar el gestor interactivo para agregar perfiles:

   ```powershell
   python main.py --gestionar-credenciales
   ```

   En el gestor, selecciona un proveedor y usa `V. Ver perfil` para visualizar
   sus credenciales guardadas. Se solicita confirmación antes de mostrar los
   valores, incluida la contraseña descifrada, en la terminal.

   La base se crea en `.credentials/providers.sqlite3` y se ignora en Git. Las contraseñas y demás campos de acceso se almacenan cifrados; la clave maestra debe proporcionarse mediante el entorno del proceso o un gestor de secretos. Al arrancar por primera vez, el programa importa una sola vez las credenciales existentes en `.env` y quita sus líneas del archivo.

El esquema relaciona `providers` con `clients` en una relación de uno a muchos. Cada proveedor puede tener varios perfiles; sus credenciales se cifran y se guardan junto con el alias. `provider_credential_fields` contiene los campos requeridos por proveedor y sus etiquetas, obligatoriedad y tratamiento secreto. Las clases de cada módulo declaran los valores iniciales; al inicializarse la base se registran sin sobrescribir los metadatos ya guardados. El gestor y el flujo de ejecución consultan SQLite, en vez de mantener sus propias listas de proveedores y etiquetas.

Los módulos implementan el contrato abstracto común `core.provider.Provider`. Para solicitar credenciales, el flujo usa `CredentialStore.request_credentials(nombre_proveedor)`: esa capa resuelve los campos registrados, selecciona el perfil y comprueba los valores obligatorios antes de inyectarlos en la configuración concreta del proveedor.

El core coordina el ciclo común y llama a hooks tipados del proveedor para las opciones de ejecución, la configuración de sesión, la restauración/guardado, el cierre de sesión, la extracción de fechas y la nomenclatura de Drive. Cada proveedor declara explícitamente si soporta reanudación y mantiene en su módulo los detalles de su portal; por ejemplo, Edesur interpreta su URL alternativa y obtiene sus enlaces de Gmail, mientras que Visa define su formato de fecha y su archivo de sesión. Las integraciones comunes solo extraen el PDF o suben archivos usando esos hooks; no contienen condicionales por nombre de proveedor.

Los servicios HTTP que descargan varias cuentas reutilizan su `httpx.AsyncClient` durante el ciclo del proveedor; el core libera esos clientes al finalizar la ejecución.

Claro y Telecentro comparten en `core/network_diagnostics.py` el filtrado de dominios, resumen de respuestas y redacción de secretos, manteniendo las diferencias específicas de cada portal.

Visa mantiene sus estrategias de descarga, selector de tarjeta, logout y extracción del período en módulos internos separados; `accounts.py` y `login.py` conservan las tareas correspondientes.

Después de descargar una factura, el CLI extrae y muestra el proveedor, el importe, el vencimiento actual y el próximo vencimiento. Las reglas comunes están en `integrations/pdf_extractor/invoice_data.py`; cada proveedor puede agregar patrones prioritarios mediante `invoice_data_patterns`, manteniendo los patrones comunes como alternativa. Hay patrones específicos para los formatos de AySA, Claro, Edenor, Edesur y Metrogas, incluidos rótulos compactos o particulares de vencimientos e importes. En Metrogas se prioriza la fecha de pago que aparece junto a `FECHA DE VENCIMIENTO` sobre la fecha CESP del pie de página. Para tarjetas también se muestran, cuando se reconoce el formato, el banco, los importes en pesos/dólares y las fechas de cierre actual y próximo. Durante una descarga, el banco de la cuenta seleccionada tiene prioridad; al procesar PDFs en lote se usa el banco que permita identificar el layout. Hay parsers para resúmenes Visa, Visa Nación y Mastercard BBVA/ICBC; el layout ICBC también reconoce el resumen con campos etiquetados (`Estado de cuenta al`, `Saldo actual` y fechas de vencimiento/cierre). No se asume que un layout no reconocido sea Visa. El importe común y las fechas se representan como `Decimal` y `YYYY-MM-DD`, respectivamente.

La extracción usa la capa de texto del PDF con `pdfplumber`: no es OCR y no reconoce texto en páginas escaneadas. Durante una descarga se leen las primeras dos páginas; el procesador por lotes lee todo el PDF. Otros formatos pueden aprovechar los patrones comunes o recibir reglas específicas cuando haya PDFs de muestra representativos.

Para guardar en CSV los datos extraídos durante una descarga:

```powershell
python main.py --proveedor edenor --todas --datos-pdf-csv datos.csv
```

Para procesar PDFs ya existentes en lote, los layouts de tarjeta soportados se detectan automáticamente. Para facturas de otros proveedores, indicar el proveedor:

```powershell
python -m integrations.pdf_extractor.cli resumen.pdf otro.pdf --csv datos.csv
python -m integrations.pdf_extractor.cli --dir facturas\edenor --proveedor edenor --csv datos.csv
```

La integracion con Google Drive es opcional; sus variables tambien se documentan en `.env.example`.

### Airtable

La sincronización con Airtable es opcional y explícita. Configurá
`AIRTABLE_TOKEN` y `AIRTABLE_BASE_ID` en el entorno o en `.env`; por defecto
usa las tablas `Comprobantes` y `Conceptos`. Para enviar los datos extraídos
de cada PDF descargado:

```powershell
python main.py --proveedor edenor --todas --airtable
```

En la estructura actual, `Comprobantes` enlaza a `Conceptos` mediante el campo
`Concepto`. El extractor busca el registro de `Conceptos` cuyo campo `Nombre`
contenga los términos del proveedor y del banco detectado. Cuando el concepto
tiene un identificador configurado, valida el número de
cliente/cuenta/servicio extraído del PDF contra `Conceptos.Identificador`; si
hay varios conceptos candidatos, usa ese número para desambiguar. La
sincronización se detiene si falta el identificador requerido o no coincide.
No se usa el nombre del titular para elegir el concepto y no se crean
conceptos automáticamente. Los valores comunes se guardan en `Fecha Vto.` y
`Importe Pesos`; las fechas de tarjeta se guardan en los campos `Prox.Vto.`,
`Cierre Actual` y `Prox.Cierre`, y el saldo en dólares en `Importe USD`.

El upsert identifica un comprobante por concepto enlazado y vencimiento
actual. Si hay una sola coincidencia, actualiza; si no hay ninguna, crea; si
hay más de una, se detiene sin modificar registros. Por eso se requiere que
el vencimiento actual esté extraído. Los campos ausentes no sobrescriben los
datos existentes. Los nombres de tablas y campos se pueden ajustar mediante
las variables `AIRTABLE_*` de `.env.example`. El PDF se carga directamente
desde el archivo local al campo de adjuntos `Doc.` con la API de carga de
Airtable; no hace falta publicar el archivo en una URL externa. Al actualizar,
si el registro ya tiene cualquier adjunto, se omite la carga para no
reemplazar ni duplicar el documento existente.

También se puede crear o actualizar un comprobante desde un PDF local, sin
iniciar sesión ni descargarlo del proveedor:

```powershell
python main.py --airtable-documento "C:\documentos\factura.pdf" --proveedor edenor
python main.py --airtable-documento "C:\documentos\resumen.pdf"
python main.py --airtable-documento "C:\documentos\visa.pdf" --proveedor visa --banco BBVA
```

Los layouts de Visa y Mastercard soportados se detectan automáticamente; para
otros proveedores se debe indicar `--proveedor`. `--banco` es opcional y
permite especificar el banco para seleccionar el concepto correcto cuando no
se puede inferir del documento. El PDF debe tener texto seleccionable (no se
realiza OCR), y el vencimiento actual debe poder extraerse para identificar
el comprobante.

## Uso

```powershell
python main.py --proveedor edenor --todas
python main.py --proveedor metrogas --listar
python main.py --todos-proveedores --todas
python main.py --proveedor mastercard --todas --datos-pdf-csv datos.csv
```

Las facturas se guardan localmente en `facturas/`. Para completar verificaciones humanas en un portal, usar `--debug` cuando corresponda.
Si un proveedor tiene varios perfiles, el programa solicita cuál usar; si solo tiene uno, lo selecciona automáticamente.

Para abrir el portal de un proveedor con login automático y dejar Chrome abierto para navegar manualmente:

```powershell
python main.py --proveedor edenor --ingresar
```

Este modo usa las credenciales guardadas y el perfil persistente del proveedor; no descarga facturas, consulta cuentas ni ejecuta logout. La terminal permanece activa hasta cerrar la ventana de Chrome. CAPTCHA, MFA u otras verificaciones del proveedor pueden requerir completar un paso manualmente.

## Desarrollo

Las pruebas compartidas estan en `tests/`; las especificas de cada proveedor, en `providers/<proveedor>/tests/`. Los utilitarios de diagnostico manual de Visa tambien estan en `providers/visa/tests/`; interactuan con el portal y no son necesarios para las descargas habituales.

## Interfaz web (Supabase) — opcional

Todo lo anterior sigue funcionando igual. Estas opciones se suman:

```powershell
# Sincroniza cada comprobante con Supabase (tabla comprobantes + PDF en Storage + datos de Drive)
python main.py --proveedor edenor --todas --supabase

# Elige el perfil sin preguntar (también sirve en ejecución local)
python main.py --proveedor edenor --todas --perfil principal

# Sube tus perfiles locales a Supabase (cifrados en Vault); primero con --dry-run
python tools/exportar_credenciales_supabase.py --dry-run
python tools/exportar_credenciales_supabase.py

# Agente: toma los pedidos de la interfaz web y ejecuta main.py (PC o VM)
python agent.py
```

Requiere `SUPABASE_URL` y `SUPABASE_SERVICE_KEY`. Una ejecución pedida desde la web
(`--ejecucion-id`) toma las credenciales de Supabase, guarda toda la salida de consola
(tabla `ejecucion_logs` y archivo completo en el bucket `ejecucion-logs`) y pide los
códigos OTP/MFA desde la web. El workflow `ejecutar-ejecucion.yml` hace lo mismo en
GitHub Actions para portales sin 2FA/captcha y necesita los secrets `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `GOOGLE_DRIVE_FOLDER_ID` y `GOOGLE_SERVICE_ACCOUNT_JSON`.
