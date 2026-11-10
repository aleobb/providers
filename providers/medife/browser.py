from playwright.async_api import BrowserContext

from core.exceptions import ConfigurationError


async def apply_context_stealth(context: BrowserContext) -> None:
    """Instala los ajustes antes de navegar, también en un perfil persistente."""
    try:
        from playwright_stealth import Stealth
    except ModuleNotFoundError as error:
        if error.name != 'playwright_stealth':
            raise
        raise ConfigurationError(
            'Medife requiere playwright-stealth. Ejecuta '
            'python -m pip install -r requirements.txt.'
        ) from error

    # Conserva plataforma, User-Agent y GPU reales; no impone datos de Windows
    # sobre Linux ni cambia las cabeceras HTTP de otros proveedores.
    stealth = Stealth(
        init_scripts_only=True,
        navigator_languages_override=('es-AR', 'es'),
        navigator_platform=False,
        navigator_platform_override=None,
        navigator_user_agent=False,
        navigator_user_agent_data=False,
        webgl_vendor=False,
    )
    await stealth.apply_stealth_async(context)
