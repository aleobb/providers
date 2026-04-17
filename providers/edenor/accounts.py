from __future__ import annotations

import httpx
from playwright.async_api import BrowserContext

from core.accounts import Account
from .config import EdenorConfig
from .interceptor import NetworkInterceptor


async def fetch_accounts(
    context: BrowserContext, interceptor: NetworkInterceptor, config: EdenorConfig
) -> list[Account]:
    cookies = {c["name"]: c["value"] for c in await context.cookies()}
    raw_token = (interceptor.auth_token or "").removeprefix("Bearer ").strip()
    headers = {
        "Accept": "application/json",
        "Accept-Language": "es-AR",
        "Referer": config.base_url + "/",
        "utility-id": "19",
        "channel": "web",
    }
    if raw_token:
        headers["Authorization"] = raw_token

    async with httpx.AsyncClient(
        cookies=cookies, headers=headers, follow_redirects=True, timeout=30
    ) as client:
        r = await client.get(f"{config.api_base}/accounts")
        r.raise_for_status()
        return _parse_accounts(r.json())


def _parse_accounts(data: list) -> list[Account]:
    accounts = []
    for item in data:
        if not isinstance(item, dict):
            continue
        accounts.append(Account(
            client_number=str(item.get("client_number", "")),
            display_name=item.get("holder_name", ""),
            address=f"{item.get('address', '')} - {item.get('city', '')}",
            extra={
                "id": str(item.get("id", "")),
                "Alias": item.get("alias") or "",
                "Relación": item.get("relationship", ""),
                "Estado": item.get("status_label", ""),
            },
        ))
    return accounts
