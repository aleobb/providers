from __future__ import annotations

from pathlib import Path

import httpx

from core.accounts import Account
from core.exceptions import DownloadError
from core.utils import unique_path
from .config import TelecentroConfig


class InvoiceService:
    """
    Descarga facturas de Telecentro via API REST directa (sin browser).

    Flujo por cuenta:
    1. POST /sv/api/refreshtokenByClient con {clienteid} y JWT base
       → JWT especifico para esa cuenta (el nameidentifier del JWT embebe el clienteId)
    2. GET /bss/fac/facturacion/v1/comprobantes/cantidad/18?tipoFacturacion=S
       con el JWT de cuenta → lista de comprobantes filtrada por el JWT
    3. GET /tlc/facturas/show/{key}
       con el JWT de cuenta → PDF de la factura mas reciente

    Descubrimiento de endpoints realizado el 2026-04-30 via analisis de trafico
    y source JS del SPA (assets/useSvClient-*.js).
    """

    def __init__(self, config: TelecentroConfig, base_jwt: str):
        self.config = config
        self.base_jwt = base_jwt

    async def download_for_client(self, account: Account) -> Path:
        client_id = account.client_number

        # Paso 1: obtener JWT especifico para esta cuenta
        account_jwt = await self._get_account_jwt(client_id)

        # Paso 2: obtener comprobantes
        comprobantes = await self._fetch_comprobantes(account_jwt)
        if not comprobantes:
            raise DownloadError(f"No hay comprobantes disponibles para cuenta {client_id}")

        latest = comprobantes[0]
        key = latest.get("key", "")
        if not key:
            raise DownloadError(f"El comprobante más reciente no tiene 'key' para descargar")

        fecha = latest.get("fechaEmision", "")
        period = _parse_period(fecha)

        # Paso 3: descargar PDF
        pdf_bytes = await self._download_pdf(account_jwt, key, client_id)

        dest_dir = self.config.ensure_output_dir()
        dest_path = unique_path(
            dest_dir / f"telecentro_{period}_{client_id}_factura.pdf"
        )
        dest_path.write_bytes(pdf_bytes)
        return dest_path

    async def _get_account_jwt(self, client_id: str) -> str:
        """
        Intercambia el JWT base por uno especifico al clienteId dado.
        Endpoint: POST /sv/api/refreshtokenByClient
        Body: {clienteid: <int>}
        Respuesta: {token, refreshtoken, clienteid}

        El JWT resultante tiene nameidentifier == clienteId, por lo que
        la API de comprobantes filtrara automaticamente por esa cuenta.
        Si el clienteId ya coincide con el JWT base, devuelve el mismo JWT.
        """
        headers = {
            "Authorization": f"Bearer {self.base_jwt}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30) as client:
            r = await client.post(
                f"{self.config.api_base}/sv/api/refreshtokenByClient",
                json={"clienteid": int(client_id)},
            )
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} al obtener JWT para cuenta {client_id}: {r.text[:200]}"
                )
            data = r.json()
            token = data.get("token", "")
            if not token:
                raise DownloadError(
                    f"refreshtokenByClient no devolvió token para cuenta {client_id}"
                )
            return token

    async def _fetch_comprobantes(self, account_jwt: str) -> list:
        """
        Obtiene la lista de comprobantes para la cuenta del JWT.
        El endpoint filtra por el clienteId embebido en el JWT (nameidentifier),
        por eso no se pasa clienteId como query param.
        Endpoint: GET /bss/fac/facturacion/v1/comprobantes/cantidad/18?tipoFacturacion=S
        Respuesta: {comprobantes: [{key, fechaEmision, link, importe, ...}]}
        """
        headers = {
            "Authorization": f"Bearer {account_jwt}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(headers=headers, verify=False, timeout=30) as client:
            r = await client.get(
                f"{self.config.api_base}/bss/fac/facturacion/v1/comprobantes/cantidad/18",
                params={"tipoFacturacion": "S"},
            )
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} al obtener comprobantes: {r.text[:200]}"
                )
            data = r.json()
            return data.get("comprobantes", [])

    async def _download_pdf(self, account_jwt: str, key: str, client_id: str) -> bytes:
        """
        Descarga el PDF de la factura.
        Endpoint: GET /tlc/facturas/show/{key}
        Solo requiere el JWT en Authorization (verificado el 2026-04-30).
        """
        headers = {
            "Authorization": f"Bearer {account_jwt}",
        }
        pdf_url = f"{self.config.invoices_url}/{key}"
        async with httpx.AsyncClient(
            headers=headers, verify=False, follow_redirects=True, timeout=60
        ) as client:
            r = await client.get(pdf_url)
            if r.status_code >= 400:
                raise DownloadError(
                    f"HTTP {r.status_code} al descargar PDF para cuenta {client_id}"
                )
            content_type = r.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and len(r.content) < 1000:
                raise DownloadError(
                    f"La respuesta del PDF no parece un PDF válido "
                    f"(content-type: {content_type}, size: {len(r.content)})"
                )
            return r.content


def _parse_period(fecha: str) -> str:
    """Convierte 'DD/MM/YYYY' a 'YYYY-MM'. Devuelve 'sin-fecha' si falla."""
    try:
        parts = fecha.split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}"
    except Exception:
        pass
    return "sin-fecha"
