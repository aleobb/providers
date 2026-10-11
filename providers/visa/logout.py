from __future__ import annotations

from playwright.async_api import BrowserContext, Page

from .config import VisaConfig


class LogoutService:
    """Closes the authenticated Visa portal session."""

    def __init__(self, config: VisaConfig):
        self.config = config

    async def logout(self, page: Page, context: BrowserContext) -> None:
        logout_urls = [
            "https://mis-tarjetas.prismamediosdepago.com/socios/app/logout",
            "https://mis-tarjetas.prismamediosdepago.com/socios/logout",
            "https://mis-tarjetas.prismamediosdepago.com/socios/j_spring_security_logout",
        ]
        try:
            logged_out = await self._try_ui_logout_js(page)

            if not logged_out and "mistarjetas" in page.url and "/app/" in page.url:
                for logout_url in logout_urls:
                    try:
                        await page.goto(logout_url, timeout=8000)
                        try:
                            await page.wait_for_load_state(
                                "domcontentloaded", timeout=5000
                            )
                        except Exception:
                            pass
                        current = page.url
                        if self._logout_succeeded(current):
                            print(
                                f"  [Visa] Logout confirmado: "
                                f"{logout_url} -> {current}"
                            )
                            logged_out = True
                            break
                        print(
                            f"  [Visa] {logout_url} -> {current} "
                            "(sin redir a login)"
                        )
                    except Exception as error:
                        print(f"  [Visa] Error en {logout_url}: {error}")
                        continue

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
                except Exception as error:
                    print(f"  [Visa] Logout POST fallback fallo: {error}")

            try:
                await context.clear_cookies()
                print("  [Visa] Cookies del browser limpiadas.")
            except Exception:
                pass

            print(f"  [Visa] Logout finalizado. URL: {page.url}")

        except Exception as error:
            print(f"  [Visa] Logout error (no critico): {error}")
        finally:
            session_file = self.config.session_file
            if session_file.exists():
                session_file.unlink()
                print("  [Visa] Session file eliminado.")

    @staticmethod
    def _logout_succeeded(url: str) -> bool:
        url = (url or "").lower()
        if "mycards" in url:
            return True
        if "login" in url:
            return True
        if "mistarjetas" in url and "/app/" not in url:
            return True
        return False

    async def _try_ui_logout_js(self, page: Page) -> bool:
        try:
            result = await page.evaluate(
                r"""() => {
                    const TEXTS = [
                        'Cerrar sesión', 'Cerrar Sesión', 'Cerrar sesion',
                        'CERRAR SESIÓN', 'CERRAR SESION',
                        'Salir', 'SALIR', 'salir',
                    ];
                    const anchors = Array.from(document.querySelectorAll('a, button'));
                    for (const txt of TEXTS) {
                        const el = anchors.find(a => (a.textContent || '').trim() === txt);
                        if (el) {
                            el.click();
                            return { ok: true, via: 'text', text: txt,
                                     href: el.getAttribute('href') || '' };
                        }
                    }
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
            if not self._logout_succeeded(page.url) and result.get("href"):
                href = result["href"]
                if not href.startswith("http"):
                    href = "https://mis-tarjetas.prismamediosdepago.com" + (
                        href if href.startswith("/") else "/" + href
                    )
                try:
                    await page.goto(href, timeout=8000)
                    await page.wait_for_load_state(
                        "domcontentloaded", timeout=5000
                    )
                except Exception:
                    pass
            if self._logout_succeeded(page.url):
                print(f"  [Visa] Logout UI confirmado. URL: {page.url}")
                return True
            print(f"  [Visa] Logout UI clickeado pero URL sigue: {page.url}")
            return False
        except Exception as error:
            print(f"  [Visa] Logout UI JS fallo: {error}")
            return False
