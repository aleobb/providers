from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page

from core.accounts import Account
from core.registry import register
from .accounts import fetch_accounts as _fetch_accounts
from .config import VisaConfig
from .interceptor import NetworkInterceptor
from .invoice import InvoiceService
from .login import LoginOrchestrator


class VisaProvider:
    name = "visa"
    display_name = "Visa (Prisma)"

    def __init__(self):
        self._config = VisaConfig()
        self._interceptor = NetworkInterceptor()

    def get_config(self) -> VisaConfig:
        return self._config

    async def login(self, page: Page, context: BrowserContext) -> None:
        # Activar el interceptor antes del login para capturar el token
        await self._interceptor.start(page)
        orchestrator = LoginOrchestrator(page, context, self._config)
        await orchestrator.execute()
        # Esperar a que el dashboard cargue y dispare las API calls
        await page.wait_for_load_state("networkidle", timeout=self._config.timeout_ms)
        await asyncio.sleep(3)

    async def fetch_accounts(self, page: Page, context: BrowserContext) -> list[Account]:
        return await _fetch_accounts(page, context, self._interceptor, self._config)

    async def download_invoice(
        self, page: Page, context: BrowserContext, account: Account
    ) -> Path:
        service = InvoiceService(page, context, self._interceptor, self._config)
        return await service.download_for_account(account)

    async def logout(self, page: Page, context: BrowserContext) -> None:
        """
        Cierra la sesion en mistarjetas navegando al endpoint de logout.
        Esto invalida el JSESSIONID server-side y evita conflictos en la proxima ejecucion.
        """
        import httpx
        try:
            # Intentar logout via navegacion directa a la URL de logout del portal Java
            _LOGOUT_URLS = [
                "https://mistarjetas.prismamediosdepago.com/socios/app/logout",
                "https://mistarjetas.prismamediosdepago.com/socios/logout",
                "https://mistarjetas.prismamediosdepago.com/socios/j_spring_security_logout",
            ]
            if "mistarjetas" in page.url:
                for logout_url in _LOGOUT_URLS:
                    try:
                        await page.goto(logout_url, timeout=8000)
                        await asyncio.sleep(1)
                        print(f"  [Visa] Logout via {logout_url}")
                        break
                    except Exception:
                        continue
            else:
                # Usar httpx con las cookies actuales para llamar al logout
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
                async with httpx.AsyncClient(cookies=cookies, verify=False, timeout=8) as client:
                    for logout_url in _LOGOUT_URLS:
                        try:
                            r = await client.get(logout_url)
                            if r.status_code < 400:
                                print(f"  [Visa] Logout via httpx: {r.status_code}")
                                break
                        except Exception:
                            continue
        except Exception:
            pass
        finally:
            # Siempre borrar el session file (las cookies ya no son validas)
            sf = self._config.session_file
            if sf.exists():
                sf.unlink()
                print("  [Visa] Session file eliminado.")


register("visa", VisaProvider)
