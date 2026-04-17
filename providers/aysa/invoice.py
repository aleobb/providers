from __future__ import annotations

from pathlib import Path

import httpx
from playwright.async_api import Page

from core.exceptions import DownloadError
from core.utils import unique_path
from .config import AysaConfig


class InvoiceService:
    def __init__(self, page: Page, config: AysaConfig):
        self.page = page
        self.config = config

    async def download_for_client(self, client_number: str) -> Path:
        cookies = {c["name"]: c["value"] for c in await self.page.context.cookies()}

        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=60, verify=False) as client:
            # Paso 1: obtener token CSRF (requerido para las llamadas POST)
            csrf_r = await client.get(
                f"{self.config.api_base}/cuentas",
                headers={"X-CSRF-Token": "Fetch"},
            )
            csrf_token = csrf_r.headers.get("X-CSRF-Token", "")

            # Paso 2: listar facturas del contrato
            invoices_r = await client.post(
                f"{self.config.api_base}/facturacion/facturas/{client_number}",
                headers={"X-CSRF-Token": csrf_token},
            )
            if invoices_r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {invoices_r.status_code} al obtener facturas para cuenta {client_number}"
                )

            invoices = invoices_r.json()
            if not invoices:
                raise DownloadError(f"No se encontraron facturas para cuenta {client_number}")

            # Paso 3: tomar la factura más reciente (mayor FAEDN)
            invoices.sort(key=lambda x: x.get("FAEDN", ""), reverse=True)
            latest = invoices[0]

            exbel = latest["EXBEL"]          # e.g. "0111B04929123A"
            numero_int = latest["NUMERO_INT"] # e.g. "0596507284"
            period = latest.get("FAEDN", "sin-fecha")[:7]  # e.g. "2026-04"

            # Paso 4: descargar el PDF
            pdf_url = (
                f"{self.config.api_base}/facturacion/factura/pdf"
                f"/{client_number}/{numero_int}/{exbel}?action=download"
            )
            pdf_r = await client.get(pdf_url)
            if pdf_r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {pdf_r.status_code} al descargar PDF para cuenta {client_number}"
                )

        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"aysa_{period}_{client_number}_factura.pdf"
        )
        dest_path.write_bytes(pdf_r.content)
        return dest_path
