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
        Cierra la sesion en mistarjetas.
        Estrategia 1: click en el link "Cerrar sesion" del UI.
        Estrategia 2: GET a las URLs de logout de Spring Security.
        Estrategia 3: POST via JS fetch (fallback para j_spring_security_logout).
        En todos los casos: borrar session file y verificar que la URL quede en el login.
        """
        _LOGOUT_URLS = [
            "https://mistarjetas.prismamediosdepago.com/socios/app/logout",
            "https://mistarjetas.prismamediosdepago.com/socios/logout",
            "https://mistarjetas.prismamediosdepago.com/socios/j_spring_security_logout",
        ]
        try:
            # 1. Buscar y clickear link de logout en el menu del portal
            logged_out = await self._try_ui_logout(page)

            # 2. Si seguimos en el portal, navegar a la URL de logout
            if not logged_out and "mistarjetas" in page.url:
                for logout_url in _LOGOUT_URLS:
                    try:
                        await page.goto(logout_url, timeout=8000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=5000)
                        except Exception:
                            pass
                        current = page.url
                        # Logout exitoso: el servidor redirige al dominio de login
                        if "mycards" in current or "login" in current.lower():
                            print(f"  [Visa] Logout confirmado: {logout_url}")
                            logged_out = True
                            break
                        print(f"  [Visa] {logout_url} -> {current} (sin redireccion a login)")
                    except Exception as e:
                        print(f"  [Visa] Error en {logout_url}: {e}")
                        continue

            # 3. Fallback: POST via JavaScript fetch (Spring Security acepta POST en _logout)
            if not logged_out:
                try:
                    result = await page.evaluate(
                        """async () => {
                            try {
                                const r = await fetch('/socios/j_spring_security_logout', {
                                    method: 'POST',
                                    credentials: 'include',
                                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                                });
                                return { ok: true, status: r.status, url: r.url };
                            } catch (e) {
                                return { ok: false, err: String(e) };
                            }
                        }"""
                    )
                    print(f"  [Visa] Logout POST JS: {result}")
                except Exception as e:
                    print(f"  [Visa] Logout POST fallback fallo: {e}")

            print(f"  [Visa] Logout finalizado. URL: {page.url}")

        except Exception as e:
            print(f"  [Visa] Logout error (no critico): {e}")
        finally:
            # Siempre borrar el session file para forzar login completo la proxima vez
            sf = self._config.session_file
            if sf.exists():
                sf.unlink()
                print("  [Visa] Session file eliminado.")

    async def _try_ui_logout(self, page: Page) -> bool:
        """Busca y clickea el link 'Cerrar sesion' en el menu del portal."""
        selectors = [
            'a:has-text("Cerrar sesi\u00f3n")',   # con tilde
            'a:has-text("Cerrar sesion")',           # sin tilde
            'a:has-text("Salir")',
            'button:has-text("Cerrar sesi\u00f3n")',
            'a[href*="logout"]',
            'a[href*="Logout"]',
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.count() > 0 and await el.is_visible(timeout=1000):
                    await el.click()
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    print(f"  [Visa] Logout via UI ({sel}). URL: {page.url}")
                    return True
            except Exception:
                pass
        return False


register("visa", VisaProvider)
