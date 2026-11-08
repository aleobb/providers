"""Cliente mínimo de Supabase (PostgREST, RPC y Storage) sobre httpx."""
from __future__ import annotations

import os
from dotenv import load_dotenv
from typing import Any
from urllib.parse import quote

import httpx

load_dotenv()

class SupabaseConfigurationError(Exception):
    """Falta configurar la conexión a Supabase."""


class SupabaseError(RuntimeError):
    """Error devuelto por Supabase o de conexión."""


class SupabaseClient:
    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        *,
        timeout: float = 30.0,
        http: httpx.Client | None = None,
    ) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL", "")).strip().rstrip("/")
        self.key = (key or os.environ.get("SUPABASE_SERVICE_KEY", "")).strip()
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.url),
                ("SUPABASE_SERVICE_KEY", self.key),
            )
            if not value
        ]
        if missing:
            raise SupabaseConfigurationError(
                f"Falta configurar: {', '.join(missing)}."
            )
        self._http = http or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------ internals
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.key}
        # Las claves nuevas (sb_secret_...) no son JWT: solo van en apikey.
        if not self.key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.key}"
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        extra = kwargs.pop("headers", None)
        try:
            response = self._http.request(
                method,
                f"{self.url}{path}",
                headers=self._headers(extra),
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise SupabaseError(f"No se pudo conectar con Supabase: {error}") from error
        if response.status_code >= 400:
            raise SupabaseError(
                f"Supabase {response.status_code}: {response.text[:500]}"
            )
        return response

    # ------------------------------------------------------------ PostgREST
    def select(self, table: str, params: dict[str, str] | None = None) -> list[dict]:
        return self._request("GET", f"/rest/v1/{table}", params=params or {}).json()

    def select_one(self, table: str, params: dict[str, str] | None = None) -> dict | None:
        rows = self.select(table, {**(params or {}), "limit": "1"})
        return rows[0] if rows else None

    def insert(self, table: str, rows: dict | list[dict]) -> list[dict]:
        response = self._request(
            "POST",
            f"/rest/v1/{table}",
            json=rows,
            headers={"Prefer": "return=representation"},
        )
        return response.json()

    def insert_one(self, table: str, row: dict) -> dict:
        return self.insert(table, row)[0]

    def update(self, table: str, filters: dict[str, str], patch: dict) -> list[dict]:
        response = self._request(
            "PATCH",
            f"/rest/v1/{table}",
            params=filters,
            json=patch,
            headers={"Prefer": "return=representation"},
        )
        return response.json()

    def rpc(self, function: str, args: dict | None = None) -> Any:
        response = self._request("POST", f"/rest/v1/rpc/{function}", json=args or {})
        return response.json() if response.content else None

    # -------------------------------------------------------------- Storage
    def upload(
        self,
        bucket: str,
        path: str,
        data: bytes,
        content_type: str,
        *,
        upsert: bool = True,
    ) -> None:
        self._request(
            "POST",
            f"/storage/v1/object/{quote(bucket, safe='')}/{quote(path, safe='/')}",
            content=data,
            headers={
                "Content-Type": content_type,
                "x-upsert": "true" if upsert else "false",
            },
        )

    def close(self) -> None:
        self._http.close()
