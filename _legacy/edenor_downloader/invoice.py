from __future__ import annotations

import asyncio
import base64
import re
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Config
from .exceptions import DownloadError, InvoiceNotFoundError
from .interceptor import NetworkInterceptor

_POLL_INTERVAL = 2
_POLL_MAX_TRIES = 25
_JOB_HOST = "https://utilitygo-api.widergy.com"


def _unique_path(base: Path) -> Path:
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    counter = 2
    while True:
        candidate = base.parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _period_str(bill: dict) -> str:
    for field in ("period", "periodo", "issued_on", "period_started_on"):
        val = bill.get(field)
        if val:
            m = re.match(r"(\d{2})/(\d{4})", str(val))
            if m:
                return f"{m.group(2)}-{m.group(1)}"
            m2 = re.search(r"(\d{4})[-/](\d{2})", str(val))
            if m2:
                return f"{m2.group(1)}-{m2.group(2)}"
    return "sin-fecha"


def _is_still_processing(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if "job_id" in data:
        return True
    status = data.get("status") or data.get("response")
    return str(status).lower() in ("processing", "pending", "queued")


class InvoiceService:
    def __init__(self, context, page, interceptor: NetworkInterceptor, config: Config):
        self.context = context
        self.page = page
        self.interceptor = interceptor
        self.config = config

    def _build_headers(self, raw_token: str) -> dict:
        h = {
            "Accept": "application/json,application/pdf,*/*",
            "Accept-Language": "es-AR",
            "Referer": self.config.base_url + "/",
            "utility-id": "19",
            "channel": "web",
        }
        if raw_token:
            h["Authorization"] = raw_token
        return h

    async def download_latest(self, account_id: str, client_number: str) -> Path:
        cookies = await self.context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        raw_token = (self.interceptor.auth_token or "").removeprefix("Bearer ").strip()
        headers = self._build_headers(raw_token)

        async with httpx.AsyncClient(
            cookies=cookie_dict, headers=headers, follow_redirects=True, timeout=60
        ) as client:
            bill = await self._fetch_last_bill(client, account_id)

        dest_dir = self.config.ensure_output_dir()
        period = _period_str(bill)
        dest_path = _unique_path(dest_dir / f"edenor_{period}_factura.pdf")

        # Check if this account is currently active in the browser
        page_content = await self.page.content()
        account_active_in_browser = client_number in page_content

        if account_active_in_browser:
            # Fast path: click the download button in the browser
            return await self._browser_download(dest_path)
        else:
            # API path: use printed_bill endpoint with async job polling
            external_id = bill.get("external_id")
            if not external_id:
                raise DownloadError(
                    "No se encontró el external_id en los datos de la factura."
                )
            cookies2 = await self.context.cookies()
            cookie_dict2 = {c["name"]: c["value"] for c in cookies2}
            async with httpx.AsyncClient(
                cookies=cookie_dict2, headers=headers, follow_redirects=True, timeout=60
            ) as client2:
                return await self._api_download(client2, client_number, external_id, dest_path)

    async def _fetch_last_bill(self, client: httpx.AsyncClient, account_id: str) -> dict:
        url = f"{self.config.api_base}/accounts/{account_id}/bills/last"
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

        if _is_still_processing(data):
            job_url = data.get("url", "")
            data = await self._poll_job(client, job_url)

        bill = self._extract_bill(data)
        if not bill:
            raise InvoiceNotFoundError(
                f"No se encontró factura. Respuesta: {str(data)[:300]}"
            )
        return bill

    async def _poll_job(self, client: httpx.AsyncClient, job_url: str) -> Any:
        if job_url.startswith("/"):
            job_url = _JOB_HOST + job_url

        for _ in range(_POLL_MAX_TRIES):
            await asyncio.sleep(_POLL_INTERVAL)
            r = await client.get(job_url)
            r.raise_for_status()

            ct = r.headers.get("content-type", "")
            if "pdf" in ct or "octet-stream" in ct:
                return {"_pdf_bytes": r.content}

            data = r.json()

            # Base64-encoded PDF (Widergy returns PDF as base64 JSON)
            if isinstance(data, dict) and "base64" in data:
                return {"_pdf_bytes": base64.b64decode(data["base64"])}

            if _is_still_processing(data):
                new_url = data.get("url")
                if new_url:
                    job_url = new_url if new_url.startswith("http") else _JOB_HOST + new_url
                continue

            if isinstance(data, dict) and "response" in data:
                resp = data["response"]
                if resp and not _is_still_processing({"status": resp}):
                    return resp

            return data

        raise InvoiceNotFoundError(
            f"El job no completó en {_POLL_MAX_TRIES * _POLL_INTERVAL}s"
        )

    def _extract_bill(self, data: Any) -> dict | None:
        if isinstance(data, dict):
            if any(k in data for k in ("external_id", "amount", "period", "downloadable")):
                return data
            for key in ("bill", "invoice", "factura", "data", "response", "result"):
                val = data.get(key)
                if isinstance(val, dict) and val:
                    return val
                if isinstance(val, list) and val:
                    return val[0]
        if isinstance(data, list) and data:
            return data[0]
        return None

    async def _api_download(
        self,
        client: httpx.AsyncClient,
        client_number: str,
        external_id: str,
        dest_path: Path,
    ) -> Path:
        url = (
            f"{self.config.api_base}/bills/printed_bill"
            f"?client_number={client_number}&external_id={external_id}"
        )
        r = await client.get(url)
        r.raise_for_status()

        ct = r.headers.get("content-type", "")
        if "pdf" in ct or "octet-stream" in ct:
            dest_path.write_bytes(r.content)
            return dest_path

        data = r.json()
        if _is_still_processing(data):
            job_url = data.get("url", "")
            result = await self._poll_job(client, job_url)

            if isinstance(result, dict) and "_pdf_bytes" in result:
                dest_path.write_bytes(result["_pdf_bytes"])
                return dest_path
            if isinstance(result, str) and result.startswith("http"):
                return await self._stream_pdf(client, result, dest_path)
            if isinstance(result, dict):
                pdf_url = result.get("url") or result.get("pdf_url") or result.get("download_url")
                if pdf_url:
                    return await self._stream_pdf(client, pdf_url, dest_path)

        raise DownloadError(
            f"No se pudo obtener el PDF para cliente {client_number}.",
            context={"client_number": client_number, "external_id": external_id},
        )

    async def _browser_download(self, dest_path: Path) -> Path:
        btn = self.page.get_by_role("button", name="Descargar factura")
        if await btn.count() == 0:
            raise DownloadError(
                "No se encontró el botón 'Descargar factura'. "
                "Usar EDENOR_HEADLESS=false para diagnóstico."
            )
        async with self.page.expect_download(timeout=60000) as dl_info:
            await btn.click()
            dl = await dl_info.value
            await dl.save_as(dest_path)
        return dest_path

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def _stream_pdf(
        self, client: httpx.AsyncClient, url: str, dest_path: Path
    ) -> Path:
        async with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise DownloadError(f"HTTP {response.status_code} descargando PDF")
            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes(8192):
                    f.write(chunk)
        return dest_path
