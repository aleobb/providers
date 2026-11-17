from __future__ import annotations

import os
import platform
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, BrowserContext, Page

from .config import BaseProviderConfig

# Directorio base de perfiles. Cada proveedor tiene su propio subdirectorio,
# lo que permite ejecuciones paralelas sin conflictos de lock de Chrome.
# Gitignoreado. La primera vez puede pedir CAPTCHA; las siguientes lo saltea.
_PROFILES_BASE = Path(__file__).parent.parent / ".chrome_profile"


def browser_channel() -> str | None:
    """Canal de Chromium para todo el proyecto (None = Chromium de Playwright).

    PROVIDERS_BROWSER_CHANNEL manda; si no está definida, Chrome salvo en Linux ARM
    (VM de Oracle), donde Chrome no existe y se usa el Chromium de Playwright.
    """
    value = os.environ.get("PROVIDERS_BROWSER_CHANNEL", "").strip().lower()
    if not value:
        is_linux_arm = sys.platform.startswith("linux") and platform.machine().lower() in {
            "aarch64",
            "arm64",
        }
        value = "chromium" if is_linux_arm else "chrome"
    return None if value == "chromium" else value


def _profile_lock_pid(profile_dir: Path) -> int | None:
    """PID del Chromium que tiene abierto el perfil (SingletonLock), si sigue vivo."""
    lock = profile_dir / "SingletonLock"
    if not lock.is_symlink():
        return None
    try:
        pid = int(os.readlink(lock).rsplit("-", 1)[-1])
        os.kill(pid, 0)
    except (ValueError, OSError):
        return None
    return pid


def _is_missing_browser_error(error: BaseException) -> bool:
    text = str(error).lower()
    return ("distribution" in text and "not found" in text) or "playwright install" in text


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
                if os.environ.get("PROVIDERS_PROFILE_FALLBACK") != "1":
                    raise FileNotFoundError(
                        f"No se encontró el perfil de Chrome configurado: {profile_dir}. "
                        "Configura browser_user_data_dir o restaura el perfil local."
                    )
                # VM: no existe el clon del perfil local; se usa el perfil persistente
                # propio del proveedor (se inicia a mano una vez con Ingresar).
                print(f"  [Browser] No existe {profile_dir}; uso el perfil propio de {self.profile_name}.")
                use_configured_profile = False
                profile_dir = _PROFILES_BASE / self.profile_name
                profile_dir.mkdir(parents=True, exist_ok=True)
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
            "viewport": {"width": 1280, "height": 800},
            "locale": "es-AR",
            "timezone_id": "America/Argentina/Buenos_Aires",
        }
        # Canal único del proyecto (ver browser_channel); PROVIDERS_BROWSER_EXECUTABLE
        # fuerza un binario concreto.
        executable = os.environ.get("PROVIDERS_BROWSER_EXECUTABLE", "").strip()
        channel = browser_channel()
        if executable:
            launch_options["executable_path"] = executable
        elif channel:
            launch_options["channel"] = channel
        if self.config.browser_user_agent:
            launch_options["user_agent"] = self.config.browser_user_agent

        args = list(self.config.browser_args)
        if use_configured_profile:
            args.append("--profile-directory=Default")
        if args:
            launch_options["args"] = args
        try:
            pid = _profile_lock_pid(profile_dir)
            if pid:
                raise RuntimeError(
                    f"El perfil {profile_dir.name} está abierto en otro navegador (pid {pid}). "
                    "Cerralo desde el escritorio remoto y reintentá."
                )
            try:
                self.context = await self._playwright.chromium.launch_persistent_context(
                    **launch_options,
                )
            except Exception as error:
                if "channel" not in launch_options or not _is_missing_browser_error(error):
                    raise
                print(f"  [Browser] {launch_options['channel']} no está instalado; uso el Chromium de Playwright.")
                launch_options.pop("channel")
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
