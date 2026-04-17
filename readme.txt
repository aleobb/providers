C:\Users\Alejandro\.claude\Code\
├── main.py                          # Entry point → core.cli.main()
├── .env                             # Credenciales (EDENOR_*, METROGAS_*)
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── accounts.py                  # Account dataclass + select_account()
│   ├── browser.py                   # BrowserSession (system Chrome)
│   ├── cli.py                       # CLI unificado (--proveedor, --todas, etc.)
│   ├── config.py                    # BaseProviderConfig
│   ├── exceptions.py                # Jerarquía de errores
│   ├── provider.py                  # Protocol (interfaz de 4 métodos)
│   ├── registry.py                  # Registro de proveedores
│   └── utils.py                     # unique_path()
├── providers/
│   ├── __init__.py                  # Auto-import → registra edenor + metrogas
│   ├── edenor/
│   │   ├── __init__.py              # EdenorProvider
│   │   ├── accounts.py
│   │   ├── config.py
│   │   ├── interceptor.py
│   │   ├── invoice.py
│   │   └── login.py
│   └── metrogas/
│       ├── __init__.py              # MetrogasProvider
│       ├── accounts.py
│       ├── config.py
│       ├── invoice.py
│       └── login.py
