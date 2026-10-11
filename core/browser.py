from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from .config import BaseProviderConfig

# Directorio base de perfiles. Cada proveedor tiene su propio subdirectorio,
# lo que permite ejecuciones paralelas sin conflictos de lock de Chrome.
# Gitignoreado. La primera vez puede pedir CAPTCHA; las siguientes lo saltea.
_PROFILES_BASE = Path(__file__).parent.parent / ".chrome_profile"


class BrowserSession:
    def __init__(
        self,
        config: BaseProviderConfig,
        profile_name: str = "default",
        fresh_profile: bool = False,
    ):
        self.config = config
        self.profile_name = profile_name
        self.fresh_profile = fresh_profile
        self._pw_cm = None
        self._playwright = None
        self._temporary_profile = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> BrowserSession:
        use_configured_profile = (
            not self.fresh_profile
            and not self.config.headless
            and self.config.browser_user_data_dir is not None
        )
        if self.fresh_profile:
            profile_dir: Path
        elif use_configured_profile:
            profile_dir = self.config.browser_user_data_dir
            if not profile_dir.is_dir():
                raise FileNotFoundError(
                    f"No se encontró el perfil de Chrome configurado: {profile_dir}. "
                    "Configura browser_user_data_dir o restaura el perfil local."
                )
        else:
            profile_dir = _PROFILES_BASE / self.profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)

        # Algunos proveedores rechazan verificaciones humanas si el browser
        # presenta señales modificadas o un User-Agent desactualizado.
        playwright_cm = async_playwright()
        if self.config.browser_stealth:
            try:
                from playwright_stealth import Stealth
            except ModuleNotFoundError as error:
                if error.name != "playwright_stealth":
                    raise
                raise RuntimeError(
                    "El proveedor requiere stealth, pero falta el paquete "
                    "'playwright-stealth'. Instala esa dependencia para usarlo."
                ) from error
            self._pw_cm = Stealth(
                navigator_languages_override=("es-419", "es", "en-US", "en")
            ).use_async(playwright_cm)
        else:
            self._pw_cm = playwright_cm
        self._playwright = await self._pw_cm.__aenter__()

        if self.fresh_profile:
            self._temporary_profile = tempfile.TemporaryDirectory(
                prefix=f"{self.profile_name}-fresh-"
            )
            profile_dir = Path(self._temporary_profile.name)

        launch_options = {
            "user_data_dir": str(profile_dir),
            "headless": self.config.headless,
            "channel": "chrome",
            "viewport": {"width": 1280, "height": 800},
            "locale": "es-AR",
            "timezone_id": "America/Argentina/Buenos_Aires",
        }
        if self.config.browser_user_agent:
            launch_options["user_agent"] = self.config.browser_user_agent

        args = list(self.config.browser_args)
        if use_configured_profile:
            args.append("--profile-directory=Default")
        if args:
            launch_options["args"] = args
        try:
            self.context = await self._playwright.chromium.launch_persistent_context(
                **launch_options,
            )
            self.page = await self.context.new_page()
        except BaseException:
            await self.__aexit__(*sys.exc_info())
            raise
        return self

    async def __aexit__(self, *args) -> None:
        try:
            if self.context:
                await self.context.close()
        finally:
            try:
                if self._pw_cm:
                    await self._pw_cm.__aexit__(*args)
            finally:
                if self._temporary_profile:
                    self._temporary_profile.cleanup()
                    self._temporary_profile = None
