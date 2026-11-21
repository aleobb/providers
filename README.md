# Descargador de facturas (providers)

Aplicación Python que inicia sesión en portales de servicios y tarjetas, descarga la última factura en PDF, extrae sus datos (importe, vencimientos) y los sincroniza con Supabase, Airtable y Google Drive. Un agente atiende los pedidos de la interfaz web del repo `aleobb/finanzas` y los comandos aprobados de una VM Oracle.

**Proveedores:** Aysa, Claro, Edenor, Edesur, Mastercard, Medifé, Metrogas, Telecentro y Visa (notas de cada uno en `docs/PORTALES.md`).

## Puesta en marcha
1. Instalar Python 3.12 y Google Chrome.
2. `python -m pip install -r requirements.txt`
3. Copiar `.env.example` como `.env` (solo configuración no secreta, p. ej. Google Drive).
4. Generar la clave de cifrado y guardarla en el gestor de claves (sin ella no se recuperan los perfiles):
   ```powershell
   $key = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   [Environment]::SetEnvironmentVariable("PROVIDERS_CREDENTIALS_KEY", $key, "User")
   $env:PROVIDERS_CREDENTIALS_KEY = $key
   ```
5. Cargar los perfiles de acceso: `python main.py --gestionar-credenciales`.

## Uso
```powershell
python main.py --proveedor edenor --todas              # descarga de todas las cuentas
python main.py --proveedor metrogas --listar           # lista las cuentas
python main.py --todos-proveedores --todas
python main.py --proveedor mastercard --todas --datos-pdf-csv datos.csv
python main.py --proveedor edesur --debug --todas      # navegador visible (verificación humana)
python main.py --proveedor edenor --ingresar           # abre el portal con login automático
python main.py --proveedor edenor --todas --supabase   # sincroniza con Supabase
python agent.py                                        # agente de la interfaz web (PC o VM)
```
Las facturas se guardan en `facturas/`. Todos los flags, las credenciales, la sincronización y el extractor de PDF están en `docs/TECNICO.md`.

## Documentación
Este repo es autosuficiente: `AGENTS.md` (guía para asistentes de IA y reglas), `docs/` (índice en `docs/README.md`: técnico, portales, operaciones, decisiones, pendientes) y `CHANGELOG.md`. Despliegue del agente en la VM Oracle: `docs/OPERACIONES.md`.

## Desarrollo
`pip install pytest` y `python -m pytest` (CI en `.github/workflows/tests.yml`). Las pruebas compartidas están en `tests/` y las de cada portal en `providers/<portal>/tests/`.
