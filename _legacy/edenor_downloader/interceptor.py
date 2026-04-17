from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Page, Response


class NetworkInterceptor:
    """Captures API responses and auth tokens from browser network traffic."""

    def __init__(self):
        self.captured: list[dict[str, Any]] = []
        self.auth_token: str | None = None
        self.account_id: str | None = None
        self.client_number: str | None = None
        self._lock = asyncio.Lock()

    async def start(self, page: Page) -> None:
        page.on("response", self._handle_response)

    async def _handle_response(self, response: Response) -> None:
        url = response.url
        if "utilitygo.widergy.com/api/v1" not in url:
            return

        # Extract account ID from URL patterns like /accounts/920358/
        match = re.search(r"/accounts/(\d+)", url)
        if match and not self.account_id:
            async with self._lock:
                self.account_id = match.group(1)

        # Extract client_number from shortcuts URL
        match_cn = re.search(r"client_number=(\d+)", url)
        if match_cn and not self.client_number:
            async with self._lock:
                self.client_number = match_cn.group(1)

        # Capture auth token from outgoing Authorization header
        request_headers = response.request.headers
        auth_header = request_headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and not self.auth_token:
            async with self._lock:
                self.auth_token = auth_header

        try:
            body = await response.json()
        except Exception:
            body = None

        # Extract access_token from session response body
        if isinstance(body, dict) and "access_token" in body and not self.auth_token:
            async with self._lock:
                self.auth_token = f"Bearer {body['access_token']}"

        async with self._lock:
            self.captured.append({
                "url": url,
                "status": response.status,
                "body": body,
            })

    def find_url_containing(self, *fragments: str) -> str | None:
        for entry in self.captured:
            url = entry["url"]
            if all(f in url for f in fragments):
                return url
        return None

    def find_body_for_url(self, *fragments: str) -> Any:
        for entry in self.captured:
            url = entry["url"]
            if all(f in url for f in fragments):
                return entry["body"]
        return None
