#!/usr/bin/env python3
"""
Descargador unificado de facturas de servicios.

Uso:
    python main.py --proveedor edenor --todas
    python main.py --proveedor metrogas --listar
    python main.py --todos-proveedores --todas
    python main.py --proveedor edenor --cuenta 12345678
    python main.py --proveedor metrogas --debug

Variables de entorno (en archivo .env):
    EDENOR_EMAIL, EDENOR_PASSWORD
    METROGAS_EMAIL, METROGAS_PASSWORD

Telecentro con --debug usa el clon local del perfil Chrome Default.

Variables opcionales por proveedor:
    <PREFIX>_OUTPUT_DIR   Directorio de destino (default: ./facturas)
    <PREFIX>_HEADLESS     true/false (default: true)
    <PREFIX>_TIMEOUT_MS   Timeout en ms (default: 30000)
"""

from core.cli import main

if __name__ == "__main__":
    main()
