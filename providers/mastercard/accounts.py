from __future__ import annotations

import httpx

from core.accounts import Account
from core.exceptions import InvoiceNotFoundError, ServerUnavailableError
from .config import MastercardConfig


def _api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Platform": "WEB",
        "Accept": "*/*",
    }


async def fetch_accounts(
    config: MastercardConfig, token: str, cookies: dict[str, str]
) -> list[Account]:
    """
    Retorna TODAS las tarjetas del usuario.
    GET /api/api/v2/creditCard/cards → {cards: [...]}
    """
    url = f"{config.api_base}/v2/creditCard/cards"
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, cookies=cookies
    ) as client:
        r = await client.get(url, headers=_api_headers(token))

    if r.status_code in (500, 503):
        raise ServerUnavailableError(
            f"Mastercard: /cards devolvio HTTP {r.status_code}. Reintenta mas tarde."
        )
    if r.status_code != 200:
        raise InvoiceNotFoundError(
            f"Mastercard: /cards devolvio HTTP {r.status_code}: {r.text[:200]}"
        )

    data = r.json()
    cards = data.get("cards") or data.get("data") or []
    if not cards:
        raise InvoiceNotFoundError("Mastercard: no se encontraron tarjetas para el usuario.")

    accounts: list[Account] = []
    seen: set[str] = set()
    for card in cards:
        number = card.get("cardNumber") or card.get("cardNumberM") or ""
        if not number or number in seen:
            continue
        seen.add(number)
        name = (card.get("fullName") or "").strip()
        entity = card.get("financialEntity") or card.get("bank") or ""
        acct = card.get("accountNumber") or ""
        additional = card.get("additional", 1)
        last4 = number[-4:] if len(number) >= 4 else number
        display = name or f"Tarjeta ****{last4}"
        if entity:
            display += f" | Entidad {entity}"
        if additional and int(additional) > 1:
            display += " (adicional)"
        accounts.append(Account(
            client_number=number,
            display_name=display,
            address=f"Cta {acct}" if acct else "",
        ))

    return accounts
