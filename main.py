#!/usr/bin/env python3
"""
Descargador unificado de facturas de servicios.

Uso:
    python main.py --proveedor <nombre> --todas
    python main.py --proveedor <nombre> --listar
    python main.py --todos-proveedores --todas
    python main.py --proveedor <nombre> --cuenta <numero>
    python main.py --proveedor <nombre> --debug

Credenciales de acceso:
    Gestionadas en SQLite; ejecutar --gestionar-credenciales para administrarlas.
    La clave de cifrado se configura como PROVIDERS_CREDENTIALS_KEY.

Variables opcionales por proveedor:
    <PREFIX>_OUTPUT_DIR   Directorio de destino (default: ./facturas)
    <PREFIX>_HEADLESS     true/false (default: true)
    <PREFIX>_TIMEOUT_MS   Timeout en ms (default: 30000)
"""

from core.cli import main

if __name__ == "__main__":
    main()
