from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from playwright.async_api import Page, Response

from core.accounts import Account
from core.exceptions import DownloadError
from core.utils import unique_path
from .config import TelecentroConfig


class InvoiceService:
    def __init__(self, page: Page, config: TelecentroConfig, jwt: str):
        self.page = page
        self.config = config
        self.jwt = jwt

    async def download_for_client(self, account: Account) -> Path:
        client_number = account.client_number

        # Paso 1: obtener comprobantes navegando el portal (la API usa sesión, no clienteId)
        comprobantes = await self._capture_comprobantes_via_browser(account)
        if not comprobantes:
            raise DownloadError(f"No se capturaron comprobantes para cuenta {client_number}")

        latest = comprobantes[0]
        key = latest.get("key", "")
        if not key:
            raise DownloadError("El comprobante más reciente no tiene 'key' para descargar")

        fecha = latest.get("fechaEmision", "")
        period = _parse_period(fecha)

        # Paso 2: descargar el PDF con las cookies actualizadas del browser
        cookies = {c["name"]: c["value"] for c in await self.page.context.cookies()}
        headers = {
            "Authorization": f"Bearer {self.jwt}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(
            headers=headers, cookies=cookies, follow_redirects=True, timeout=60, verify=False
        ) as client:
            pdf_url = f"{self.config.invoices_url}/{key}"
            pdf_r = await client.get(pdf_url)
            if pdf_r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {pdf_r.status_code} al descargar PDF para cuenta {client_number}"
                )

        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"telecentro_{period}_{client_number}_factura.pdf"
        )
        dest_path.write_bytes(pdf_r.content)
        return dest_path

    async def _capture_comprobantes_via_browser(self, account: Account) -> list | None:
        """
        Navega el portal hacia la cuenta indicada e intercepta el response de comprobantes
        que el JS del portal dispara naturalmente (la API filtra por sesión, no por query param).
        """
        captures: list[list] = []

        async def on_response(response: Response) -> None:
            if "comprobantes" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    comps = data.get("comprobantes", [])
                    if comps:
                        captures.append(comps)
                except Exception:
                    pass

        self.page.on("response", on_response)
        try:
            # Navegar al portal — dispara la carga de la cuenta activa
            await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)
            await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)
            await asyncio.sleep(2)

            before_switch = len(captures)

            # Intentar cambiar a la cuenta target en la UI
            switched = await self._switch_account_in_ui(account)

            if switched:
                # Esperar a que el portal recargue los datos de la nueva cuenta
                await asyncio.sleep(2)
                await self.page.wait_for_load_state("networkidle", timeout=self.config.timeout_ms)

                # Preferir captures posteriores al switch
                if len(captures) > before_switch:
                    return captures[-1]

            # Devolver lo último capturado (puede ser la cuenta correcta si ya estaba activa)
            return captures[-1] if captures else None
        finally:
            self.page.remove_listener("response", on_response)

    async def _switch_account_in_ui(self, account: Account) -> bool:
        """
        Hace clic en la tarjeta "Número de cliente: XXXX" (con ícono ↺ a la derecha)
        y luego selecciona la cuenta target en el modal que aparece.
        """
        search_terms = [t for t in [account.client_number, account.display_name, account.address] if t]

        # Esperar a que la tarjeta con "Número de cliente" esté visible
        try:
            await self.page.locator(':text("Número de cliente")').first.wait_for(
                state="visible", timeout=15000
            )
        except Exception as e:
            print(f"[DEBUG telecentro] No se encontró la tarjeta 'Número de cliente': {e}")
            return False

        await asyncio.sleep(1)

        # Estrategias de clic, de más específico (ícono) a más genérico (tarjeta entera)
        click_strategies = [
            "mat-card:has-text('Número de cliente') button",
            "mat-card:has-text('Número de cliente') mat-icon",
            "mat-card:has-text('Número de cliente') a",
            "mat-card:has-text('Número de cliente')",
            "[class*='card']:has-text('Número de cliente') button",
            "[class*='card']:has-text('Número de cliente') [class*='icon']",
            "[class*='card']:has-text('Número de cliente')",
            ":text('Número de cliente:') >> xpath=ancestor::*[self::div or self::a or self::button][1]",
        ]

        clicked = False
        for selector in click_strategies:
            try:
                elem = self.page.locator(selector).first
                if await elem.count() == 0:
                    continue
                if not await elem.is_visible(timeout=1500):
                    continue
                await elem.click(timeout=3000)
                print(f"[DEBUG telecentro] Switcher clickeado con: {selector}")
                clicked = True
                break
            except Exception as e:
                print(f"[DEBUG telecentro] Selector falló '{selector}': {e}")
                continue

        if not clicked:
            print("[DEBUG telecentro] No se pudo clickear el switcher de cuentas")
            return False

        # Esperar a que aparezca el modal/listado
        await asyncio.sleep(2)

        # Buscar la cuenta target en el listado que apareció
        for term in search_terms:
            try:
                target = self.page.get_by_text(str(term), exact=False).last
                if await target.is_visible(timeout=3000):
                    await target.click()
                    print(f"[DEBUG telecentro] Cuenta seleccionada por término: {term}")
                    return True
            except Exception as e:
                print(f"[DEBUG telecentro] No se encontró cuenta por '{term}': {e}")
                continue

        print(f"[DEBUG telecentro] No se encontró la cuenta {account.client_number} en el modal")
        return False


def _parse_period(fecha: str) -> str:
    """Convierte 'DD/MM/YYYY' a 'YYYY-MM'. Devuelve 'sin-fecha' si no puede parsear."""
    try:
        parts = fecha.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}"
    except Exception:
        pass
    return "sin-fecha"
