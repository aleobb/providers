# Descargador de facturas

Aplicacion Python para iniciar sesion en portales de servicios y tarjetas, descargar facturas PDF y, opcionalmente, guardarlas en Google Drive.

## Proveedores

Aysa, Claro, Edenor, Edesur, Mastercard, Metrogas, Telecentro y Visa.

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

La base se crea en `.credentials/providers.sqlite3` y se ignora en Git. Las contraseñas y demás campos de acceso se almacenan cifrados; la clave maestra debe proporcionarse mediante el entorno del proceso o un gestor de secretos. Al arrancar por primera vez, el programa importa una sola vez las credenciales existentes en `.env` y quita sus líneas del archivo.

El esquema relaciona `providers` con `clients` en una relación de uno a muchos. Cada proveedor puede tener varios perfiles; sus credenciales se cifran y se guardan junto con el alias. `provider_credential_fields` contiene los campos requeridos por proveedor y sus etiquetas, obligatoriedad y tratamiento secreto. Las clases de cada módulo declaran los valores iniciales; al inicializarse la base se registran sin sobrescribir los metadatos ya guardados. El gestor y el flujo de ejecución consultan SQLite, en vez de mantener sus propias listas de proveedores y etiquetas.

Los módulos implementan el contrato abstracto común `core.provider.Provider`. Para solicitar credenciales, el flujo usa `CredentialStore.request_credentials(nombre_proveedor)`: esa capa resuelve los campos registrados, selecciona el perfil y comprueba los valores obligatorios antes de inyectarlos en la configuración concreta del proveedor.

El core coordina el ciclo común y llama a hooks tipados del proveedor para las opciones de ejecución, la configuración de sesión, la restauración/guardado, el cierre de sesión, la extracción de fechas y la nomenclatura de Drive. Cada proveedor declara explícitamente si soporta reanudación y mantiene en su módulo los detalles de su portal; por ejemplo, Edesur interpreta su URL alternativa y obtiene sus enlaces de Gmail, mientras que Visa define su formato de fecha y su archivo de sesión. Las integraciones comunes solo extraen el PDF o suben archivos usando esos hooks; no contienen condicionales por nombre de proveedor.

Los servicios HTTP que descargan varias cuentas reutilizan su `httpx.AsyncClient` durante el ciclo del proveedor; el core libera esos clientes al finalizar la ejecución.

Claro y Telecentro comparten en `core/network_diagnostics.py` el filtrado de dominios, resumen de respuestas y redacción de secretos, manteniendo las diferencias específicas de cada portal.

Visa mantiene sus estrategias de descarga, selector de tarjeta, logout y extracción del período en módulos internos separados; `accounts.py` y `login.py` conservan las tareas correspondientes.

La integracion con Google Drive es opcional; sus variables tambien se documentan en `.env.example`.

## Uso

```powershell
python main.py --proveedor edenor --todas
python main.py --proveedor metrogas --listar
python main.py --todos-proveedores --todas
```

Las facturas se guardan localmente en `facturas/`. Para completar verificaciones humanas en un portal, usar `--debug` cuando corresponda.
Si un proveedor tiene varios perfiles, el programa solicita cuál usar; si solo tiene uno, lo selecciona automáticamente.

## Desarrollo

Las pruebas compartidas estan en `tests/`; las especificas de cada proveedor, en `providers/<proveedor>/tests/`. Los utilitarios de diagnostico manual de Visa tambien estan en `providers/visa/tests/`; interactuan con el portal y no son necesarios para las descargas habituales.
