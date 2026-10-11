"""Read Gmail messages to find Edesur Docuprint invoice URLs."""
from __future__ import annotations

import base64
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_DOCUPRINT_RE = re.compile(
    r"https://edesur\.docuprint\.com/home/download/[A-Za-z0-9_\-]+"
)


def _get_service(credentials_file: Path, token_file: Path):
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def _extract_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")
    if mime in ("text/plain", "text/html") and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")

    return "".join(_extract_text(part) for part in payload.get("parts", []))


def find_docuprint_url(
    credentials_file: str | Path,
    token_file: str | Path,
    max_results: int = 5,
) -> str | None:
    """Find the newest matching Docuprint URL in Gmail."""
    credentials_file = Path(credentials_file)
    token_file = Path(token_file)
    if not credentials_file.exists():
        raise FileNotFoundError(
            f"No se encontró {credentials_file}. "
            "Descargalo desde Google Cloud Console → APIs y servicios → Credenciales."
        )

    service = _get_service(credentials_file, token_file)
    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            q="from:edesur docuprint",
            maxResults=max_results,
        )
        .execute()
    )
    for message_ref in result.get("messages", []):
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_ref["id"], format="full")
            .execute()
        )
        text = _extract_text(message.get("payload", {}))
        match = _DOCUPRINT_RE.search(text)
        if match:
            return match.group(0)
    return None
