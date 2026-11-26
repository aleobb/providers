"""Cliente mínimo de Supabase (PostgREST, RPC y Storage) sobre httpx."""
from __future__ import annotations

import os
import time
from dotenv import load_dotenv
from typing import Any
from urllib.parse import quote

import httpx

load_dotenv()

# Reintentos ante fallos transitorios. Las lecturas se reintentan ante cualquier error de red, 429 o 5xx.
# Las escrituras solo cuando el pedido seguro no llegó (no se pudo conectar) o Supabase lo rechazó (429):
# repetir un PATCH/POST que sí se aplicó podría duplicar o desreclamar un pedido.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_READ_METHODS = frozenset({"GET", "HEAD"})
_sleep = time.sleep


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
        retries: int = 2,
        backoff: float = 0.5,
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
        self._retries = max(0, retries)
        self._backoff = backoff

    # ------------------------------------------------------------ internals
    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.key}
        # Las claves nuevas (sb_secret_...) no son JWT: solo van en apikey.
        if not self.key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self.key}"
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self, method: str, path: str, *, idempotent: bool = False, **kwargs: Any
    ) -> httpx.Response:
        extra = kwargs.pop("headers", None)
        safe = idempotent or method in _READ_METHODS
        for attempt in range(self._retries + 1):
            last = attempt == self._retries
            try:
                response = self._http.request(
                    method,
                    f"{self.url}{path}",
                    headers=self._headers(extra),
                    **kwargs,
                )
            except httpx.HTTPError as error:
                never_sent = isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                if last or not (safe or never_sent):
                    raise SupabaseError(
                        f"No se pudo conectar con Supabase: {error}"
                    ) from error
                _sleep(self._backoff * 2**attempt)
                continue
            retry_status = response.status_code in _RETRY_STATUS and (
                safe or response.status_code == 429
            )
            if retry_status and not last:
                _sleep(self._backoff * 2**attempt)
                continue
            break
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
            idempotent=upsert,
            headers={
                "Content-Type": content_type,
                "x-upsert": "true" if upsert else "false",
            },
        )

    def close(self) -> None:
        self._http.close()
