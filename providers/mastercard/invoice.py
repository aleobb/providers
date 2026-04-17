from __future__ import annotations

from pathlib import Path

import httpx

from core.accounts import Account
from core.exceptions import DownloadError, InvoiceNotFoundError, ServerUnavailableError
from core.utils import unique_path
from .config import MastercardConfig


def _api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Platform": "WEB",
        "Accept": "*/*",
    }


async def download_invoice(
    config: MastercardConfig,
    token: str,
    cookies: dict[str, str],
    account: Account,
) -> Path:
    """
    Descarga el ultimo resumen PDF de la tarjeta indicada.

    Flujo:
      1. POST /v2/creditCard/latestSummaryStatus {cardNumberM} -> summaries[]
      2. Tomar summaries[0].statementDate (el mas reciente)
      3. POST /v2/creditCard/monthlySummaryPdf {cardNumberM, statementDate} -> blob PDF
    """
    card_number = account.client_number
    period = await _get_latest_period(config, token, cookies, card_number)
    pdf_bytes = await _fetch_pdf(config, token, cookies, card_number, period)

    last4 = card_number[-4:] if len(card_number) >= 4 else card_number
    dest = unique_path(
        config.ensure_output_dir() / f"mastercard_{period}_{last4}_resumen.pdf"
    )
    dest.write_bytes(pdf_bytes)
    return dest


async def _get_latest_period(
    config: MastercardConfig, token: str, cookies: dict[str, str], card_number: str
) -> str:
    """Obtiene la fecha del resumen mas reciente."""
    url = f"{config.api_base}/v2/creditCard/latestSummaryStatus"
    payload = {"cardNumberM": card_number}

    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, cookies=cookies
    ) as client:
        r = await client.post(url, json=payload, headers=_api_headers(token))

    if r.status_code in (500, 503):
        raise ServerUnavailableError(
            f"Mastercard: /latestSummaryStatus devolvio HTTP {r.status_code}. Reintenta mas tarde."
        )
    if r.status_code != 200:
        raise InvoiceNotFoundError(
            f"Mastercard: /latestSummaryStatus HTTP {r.status_code}: {r.text[:200]}"
        )

    data = r.json()
    summaries = data.get("summaries") or data.get("data") or []
    if not summaries:
        raise InvoiceNotFoundError(
            f"Mastercard: no hay resumenes disponibles para la tarjeta ****{card_number[-4:]}."
        )

    # Ordenar desc por statementDate y tomar el primero
    summaries_sorted = sorted(
        summaries, key=lambda s: s.get("statementDate", ""), reverse=True
    )
    period = summaries_sorted[0].get("statementDate")
    if not period:
        raise InvoiceNotFoundError("Mastercard: el resumen mas reciente no tiene statementDate.")

    return period


async def _fetch_pdf(
    config: MastercardConfig,
    token: str,
    cookies: dict[str, str],
    card_number: str,
    period: str,
) -> bytes:
    """Descarga el PDF del resumen."""
    url = f"{config.api_base}/v2/creditCard/monthlySummaryPdf"
    payload = {"cardNumberM": card_number, "statementDate": period}
    headers = _api_headers(token)
    headers["Accept"] = "application/pdf, */*"

    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True, cookies=cookies
    ) as client:
        r = await client.post(url, json=payload, headers=headers)

    if r.status_code in (500, 503):
        raise ServerUnavailableError(
            f"Mastercard: /monthlySummaryPdf devolvio HTTP {r.status_code}. Reintenta mas tarde."
        )
    if r.status_code != 200:
        raise DownloadError(
            f"Mastercard: /monthlySummaryPdf HTTP {r.status_code}: {r.text[:200]}"
        )

    if len(r.content) < 100:
        raise DownloadError(
            f"Mastercard: la respuesta es muy pequena ({len(r.content)} bytes), "
            f"probablemente no es un PDF."
        )

    return r.content
