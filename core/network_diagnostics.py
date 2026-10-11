from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit


class NetworkDiagnostics:
    """Shared URL, response-body, and secret-redaction helpers for login logs."""

    def __init__(
        self,
        domains: Sequence[str],
        *,
        include_subdomains: bool = False,
        preserve_netloc: bool = False,
        redact_long_path_segments: bool = False,
        redact_emails: bool = False,
    ):
        self.domains = tuple(domain.lower() for domain in domains)
        self.include_subdomains = include_subdomains
        self.preserve_netloc = preserve_netloc
        self.redact_long_path_segments = redact_long_path_segments
        self.redact_emails = redact_emails

    def matches_domain(self, url: str) -> bool:
        hostname = (urlsplit(url).hostname or "").lower()
        return any(
            hostname == domain
            or (
                self.include_subdomains
                and hostname.endswith(f".{domain}")
            )
            for domain in self.domains
        )

    def safe_url(self, url: str) -> str:
        parsed_url = urlsplit(url)
        host = parsed_url.netloc if self.preserve_netloc else (
            parsed_url.hostname or "(unknown-host)"
        )
        path = parsed_url.path
        if self.redact_long_path_segments:
            path = re.sub(r"/[^/]{32,}", "/[redacted]", path)
        return f"{host}{path}"

    def redact(self, value: str, secrets: Iterable[str] = ()) -> str:
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        value = re.sub(
            r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]*)?",
            "[redacted-jwt]",
            value,
        )
        if self.redact_emails:
            value = re.sub(
                r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                "[redacted-email]",
                value,
                flags=re.IGNORECASE,
            )
        return value

    def summarize_body(
        self,
        body: str,
        content_type: str,
        detail_keys: Sequence[str],
        secrets: Iterable[str] = (),
    ) -> str:
        if not body:
            return "body=(empty)"
        if "json" in content_type.lower():
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                keys = ",".join(str(key) for key in list(payload)[:15])
                safe_values = []
                for key in detail_keys:
                    value = payload.get(key)
                    if isinstance(value, (str, int, float, bool)):
                        safe_values.append(
                            f"{key}={self.redact(str(value)[:120], secrets)}"
                        )
                details = f"json-keys={keys or '(none)'}"
                if safe_values:
                    details += f"; json-details={','.join(safe_values)}"
                return details
        text = " ".join(body.split())
        return f"body-text={self.redact(text[:180], secrets)}"
