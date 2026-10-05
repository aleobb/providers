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
        # Esperar a que el dashboard renderice el contenido; la app usa polling
        # y no llega a networkidle de forma consistente.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self._config.timeout_ms)
        except Exception:
            pass
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

        Estrategia 1: click por JS en el link "Salir"/"Cerrar sesion" (aunque
                      no sea visible por estar en un menu colapsado).
        Estrategia 2: navegar a URLs de logout de Spring Security.
        Estrategia 3: POST via JS fetch al endpoint de Spring Security.

        En todos los casos: borrar session file y verificar que la URL quede
        fuera del dominio del portal autenticado.
        """
        _LOGOUT_URLS = [
            "https://mis-tarjetas.prismamediosdepago.com/socios/app/logout",
            "https://mis-tarjetas.prismamediosdepago.com/socios/logout",
            "https://mis-tarjetas.prismamediosdepago.com/socios/j_spring_security_logout",
        ]
        try:
            # 1. Click por JS en el link de logout (bypassa is_visible)
            logged_out = await self._try_ui_logout_js(page)

            # 2. Si seguimos en el portal autenticado, navegar a URLs de logout
            if not logged_out and "mistarjetas" in page.url and "/app/" in page.url:
                for logout_url in _LOGOUT_URLS:
                    try:
                        await page.goto(logout_url, timeout=8000)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                        current = page.url
                        if self._logout_succeeded(current):
                            print(f"  [Visa] Logout confirmado: {logout_url} -> {current}")
                            logged_out = True
                            break
                        print(f"  [Visa] {logout_url} -> {current} (sin redir a login)")
                    except Exception as e:
                        print(f"  [Visa] Error en {logout_url}: {e}")
                        continue

            # 3. Fallback: POST via JS fetch (Spring Security acepta POST)
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

            # Verificacion final: limpiar cookies de Spring por si el servidor no lo hizo
            try:
                await context.clear_cookies()
                print("  [Visa] Cookies del browser limpiadas.")
            except Exception:
                pass

            print(f"  [Visa] Logout finalizado. URL: {page.url}")

        except Exception as e:
            print(f"  [Visa] Logout error (no critico): {e}")
        finally:
            # Siempre borrar el session file para forzar login completo la proxima vez
            sf = self._config.session_file
            if sf.exists():
                sf.unlink()
                print("  [Visa] Session file eliminado.")

    @staticmethod
    def _logout_succeeded(url: str) -> bool:
        """El logout fue exitoso si salimos del dominio autenticado."""
        u = (url or "").lower()
        if "mycards" in u:
            return True
        if "login" in u:
            return True
        # Si seguimos en mistarjetas pero fuera de /app/ (p.ej. /socios/auth/...), ok
        if "mistarjetas" in u and "/app/" not in u:
            return True
        return False

    async def _try_ui_logout_js(self, page: Page) -> bool:
        """
        Busca y clickea el link de logout por JS. No requiere que sea visible:
        usa .click() sobre elementos ocultos (comun en menus colapsados del portal).
        """
        try:
            result = await page.evaluate(
                r"""() => {
                    const TEXTS = [
                        'Cerrar sesión', 'Cerrar Sesión', 'Cerrar sesion',
                        'CERRAR SESIÓN', 'CERRAR SESION',
                        'Salir', 'SALIR', 'salir',
                    ];
                    // 1. Buscar por texto exacto (la prioridad)
                    const anchors = Array.from(document.querySelectorAll('a, button'));
                    for (const txt of TEXTS) {
                        const el = anchors.find(a => (a.textContent || '').trim() === txt);
                        if (el) {
                            el.click();
                            return { ok: true, via: 'text', text: txt,
                                     href: el.getAttribute('href') || '' };
                        }
                    }
                    // 2. Buscar por href con "logout"
                    const byHref = anchors.find(a => {
                        const h = (a.getAttribute('href') || '').toLowerCase();
                        return h.includes('logout') || h.includes('j_spring_security_logout');
                    });
                    if (byHref) {
                        byHref.click();
                        return { ok: true, via: 'href',
                                 href: byHref.getAttribute('href') || '',
                                 text: (byHref.textContent || '').trim() };
                    }
                    return { ok: false };
                }"""
            )
            if not result.get("ok"):
                return False
            print(f"  [Visa] Logout UI via JS: {result}")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            # Si el click fue en un <a href="logout-url"> pero seguimos autenticados,
            # forzar navegacion al href
            if not self._logout_succeeded(page.url) and result.get("href"):
                href = result["href"]
                if not href.startswith("http"):
                    href = "https://mis-tarjetas.prismamediosdepago.com" + (
                        href if href.startswith("/") else "/" + href
                    )
                try:
                    await page.goto(href, timeout=8000)
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
            if self._logout_succeeded(page.url):
                print(f"  [Visa] Logout UI confirmado. URL: {page.url}")
                return True
            print(f"  [Visa] Logout UI clickeado pero URL sigue: {page.url}")
            return False
        except Exception as e:
            print(f"  [Visa] Logout UI JS fallo: {e}")
            return False


    # ─── Session store ────────────────────────────────────────────────────────
    # Visa (JSF portal) aún necesita el browser para el switch de tarjeta y
    # la captura de la URL de descarga. Solo guardamos cookies para análisis futuro.

    async def save_session(
        self, page: Page, context: BrowserContext, accounts: list[Account]
    ) -> None:
        """Guarda cookies de Spring Security + cuentas para la próxima ejecución."""
        from core import session_store
        cookies = {c["name"]: c["value"] for c in await context.cookies()}
        session_store.save(self.name, {
            "cookies": cookies,
            "accounts": session_store.accounts_to_list(accounts),
        })
        print("  [Visa] Sesión guardada.")


register("visa", VisaProvider)
