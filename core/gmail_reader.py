"""
Lee el inbox de Gmail buscando URLs de Docuprint en mails de Edesur.

Autenticación: OAuth 2.0 de usuario (no service account).
- Primera vez: abre el browser para autorizar y guarda token.json.
- Siguientes veces: usa el token guardado (se auto-refresca).

Archivos necesarios (gitignoreados):
  gmail_credentials.json  — descargado de Google Cloud Console
  gmail_token.json        — generado automáticamente en el primer run
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Solo lectura de Gmail — scope mínimo necesario
_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_DOCUPRINT_RE = re.compile(
    r"https://edesur\.docuprint\.com/home/download/[A-Za-z0-9_\-]+"
)


def _get_service(credentials_file: Path, token_file: Path):
    """Autentica y devuelve el servicio de Gmail API."""
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), _SCOPES)

    # Si no hay token válido, hace el flujo OAuth (abre el browser una sola vez)
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
    """Extrae el texto plano del payload de un mensaje de Gmail."""
    mime = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime in ("text/plain", "text/html") and body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")

    # Mensaje multipart: recorrer partes recursivamente
    text = ""
    for part in payload.get("parts", []):
        text += _extract_text(part)
    return text


def find_docuprint_url(
    credentials_file: str | Path,
    token_file: str | Path,
    max_results: int = 5,
) -> str | None:
    """
    Busca en el inbox los últimos mails de Edesur con un link de Docuprint.
    Devuelve la URL más reciente encontrada, o None si no hay ninguna.

    Args:
        credentials_file: Ruta al gmail_credentials.json de Google Cloud.
        token_file:        Ruta donde guardar/leer el token OAuth.
        max_results:       Cuántos mails revisar (por defecto los 5 más recientes).
    """
    credentials_file = Path(credentials_file)
    token_file = Path(token_file)

    if not credentials_file.exists():
        raise FileNotFoundError(
            f"No se encontró {credentials_file}. "
            "Descargalo desde Google Cloud Console → APIs y servicios → Credenciales."
        )

    service = _get_service(credentials_file, token_file)

    # Buscar mails de Edesur con link de Docuprint (leídos y no leídos)
    query = "from:edesur docuprint"
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    messages = result.get("messages", [])
    if not messages:
        return None

    for msg_ref in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="full")
            .execute()
        )
        text = _extract_text(msg.get("payload", {}))
        match = _DOCUPRINT_RE.search(text)
        if match:
            return match.group(0)

    return None
