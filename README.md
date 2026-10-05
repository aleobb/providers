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

3. Copiar `.env.example` como `.env` y completar las credenciales necesarias. No subir `.env` al repositorio.

La integracion con Google Drive es opcional; sus variables tambien se documentan en `.env.example`.

## Uso

```powershell
python main.py --proveedor edenor --todas
python main.py --proveedor metrogas --listar
python main.py --todos-proveedores --todas
```

Las facturas se guardan localmente en `facturas/`. Para completar verificaciones humanas en un portal, usar `--debug` cuando corresponda.

## Desarrollo

Las pruebas estan en `tests/` y los utilitarios de diagnostico de Visa en `scripts/`. Estos ultimos interactuan con el portal; no son necesarios para las descargas habituales.
