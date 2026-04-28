from __future__ import annotations

import io
import json
import os
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveUploader:
    """
    Sube archivos PDF a Google Drive usando una Service Account.

    Credenciales: la variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON debe
    contener el JSON de la service account (como string) o una ruta a un archivo.
    """

    def __init__(self) -> None:
        creds = self._load_credentials()
        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
        # Cache: "{parent_id}/{name}" -> folder_id
        self._folder_cache: dict[str, str] = {}

    # ------------------------------------------------------------------ public

    def upload_to_path(
        self,
        pdf_path: Path,
        root_folder_id: str,
        subfolder_parts: list[str],
        drive_filename: str,
    ) -> str:
        """
        Navega (y crea si hace falta) la jerarquía de subcarpetas bajo
        root_folder_id y sube el archivo.

        Retorna el Drive file ID del archivo subido.
        Si ya existe un archivo con el mismo nombre en la carpeta destino,
        lo omite y retorna el ID existente.
        """
        folder_id = root_folder_id
        for part in subfolder_parts:
            folder_id = self._get_or_create_folder(part, folder_id)

        existing_id = self._find_existing_file(drive_filename, folder_id)
        if existing_id:
            return existing_id
        file_metadata = {
            "name": drive_filename,
            "parents": [folder_id],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(pdf_path.read_bytes()),
            mimetype="application/pdf",
            resumable=False,
        )
        result = (
            self._service.files()
            .create(body=file_metadata, media_body=media, fields="id,name")
            .execute()
        )
        return result.get("id", "")

    # ------------------------------------------------------------------ private

    def _load_credentials(self):
        sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not sa_json:
            raise EnvironmentError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no está configurado."
            )
        if sa_json.startswith("{"):
            info = json.loads(sa_json)
        else:
            info = json.loads(Path(sa_json).read_text(encoding="utf-8"))
        return service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )

    def _get_or_create_folder(self, name: str, parent_id: str) -> str:
        cache_key = f"{parent_id}/{name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        query = (
            f"name = {json.dumps(name)} "
            f"and mimeType = 'application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents "
            f"and trashed = false"
        )
        results = (
            self._service.files()
            .list(q=query, spaces="drive", fields="files(id,name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])
        if files:
            folder_id = files[0]["id"]
        else:
            meta = {
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            folder = (
                self._service.files().create(body=meta, fields="id").execute()
            )
            folder_id = folder["id"]

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def _find_existing_file(self, filename: str, folder_id: str) -> str | None:
        query = (
            f"name = {json.dumps(filename)} "
            f"and '{folder_id}' in parents "
            f"and trashed = false"
        )
        results = (
            self._service.files()
            .list(q=query, spaces="drive", fields="files(id,name)", pageSize=1)
            .execute()
        )
        files = results.get("files", [])
        return files[0]["id"] if files else None
