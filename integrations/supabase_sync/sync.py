"""Crea o actualiza `comprobantes` en Supabase con los datos extraídos del PDF.

Replica las reglas de `integrations/airtable/sync.py`:
- El concepto se busca por proveedor (+ banco) y se valida contra
  `conceptos.Identificador` cuando existe; nunca se crean conceptos.
- Un comprobante se identifica por concepto + vencimiento actual: una sola
  coincidencia actualiza, ninguna crea, varias detienen sin modificar nada.
- Los campos ausentes no sobrescriben datos existentes.
- Si el comprobante ya tiene documento, no se vuelve a subir.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from integrations.pdf_extractor.invoice_data import InvoiceData

from .client import SupabaseClient, SupabaseError

BUCKET = "Comprobantes"


class SupabaseSyncError(Exception):
    """Un comprobante extraído no se pudo sincronizar."""


@dataclass(frozen=True)
class SupabaseSyncResult:
    comprobante_id: int
    created: bool
    documento_subido: bool
    storage_path: str | None = None
    drive_file_id: str | None = None


@dataclass(frozen=True)
class _Concept:
    id: int
    name: str
    identifier: Any


class SupabaseInvoiceSync:
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client
        self._concepts: list[_Concept] | None = None  # los conceptos se leen una vez por corrida

    # ------------------------------------------------------------------ API
    def sync_invoice(
        self,
        pdf_path: Path,
        data: InvoiceData,
        drive_result: dict | None = None,
    ) -> SupabaseSyncResult:
        try:
            self._validate(pdf_path, data)
            concept_id = self._find_concept_id(data)
            fields = self._invoice_fields(data, concept_id)
            existing = self._client.select(
                "comprobantes",
                {
                    "concepto_id": f"eq.{concept_id}",
                    "fecha_vto": f"eq.{data.current_due_date}",
                    "select": "id,doc_storage_path,doc_drive_file_id,importe_pesos,importe_usd,nro_doc",
                },
            )
            if len(existing) > 1:
                existing = self._pick_among_duplicates(existing, fields)
            if existing:
                row = existing[0]
                self._client.update("comprobantes", {"id": f"eq.{row['id']}"}, fields)
                comprobante_id, created = int(row["id"]), False
                has_document = bool(
                    row.get("doc_storage_path") or row.get("doc_drive_file_id")
                )
            else:
                created_row = self._client.insert_one("comprobantes", fields)
                comprobante_id, created = int(created_row["id"]), True
                has_document = False

            storage_path = drive_file_id = None
            if not has_document:
                storage_path, drive_file_id = self._attach_document(
                    comprobante_id, pdf_path, drive_result
                )
            return SupabaseSyncResult(
                comprobante_id=comprobante_id,
                created=created,
                documento_subido=bool(storage_path or drive_file_id),
                storage_path=storage_path,
                drive_file_id=drive_file_id,
            )
        except SupabaseSyncError:
            raise
        except SupabaseError as error:
            raise SupabaseSyncError(str(error)) from error
        except OSError as error:
            raise SupabaseSyncError(
                f"No se pudo leer el PDF {pdf_path.name}: {error}"
            ) from error

    # ------------------------------------------------------------- internals
    @staticmethod
    def _validate(pdf_path: Path, data: InvoiceData) -> None:
        if not pdf_path.is_file():
            raise SupabaseSyncError(f"No se encontró el PDF: {pdf_path}.")
        if pdf_path.suffix.lower() != ".pdf":
            raise SupabaseSyncError(
                f"El documento no es un PDF: {pdf_path.name}."
            )
        if not data.current_due_date:
            raise SupabaseSyncError(
                "No se encontró el vencimiento actual; no se puede "
                "identificar el comprobante para actualizarlo."
            )
        try:
            date.fromisoformat(data.current_due_date)
        except ValueError as error:
            raise SupabaseSyncError(
                "El vencimiento actual no tiene formato YYYY-MM-DD; "
                "no se puede identificar el comprobante."
            ) from error

    def _attach_document(
        self, comprobante_id: int, pdf_path: Path, drive_result: dict | None
    ) -> tuple[str | None, str | None]:
        patch: dict[str, Any] = {}
        storage_error: SupabaseError | None = None
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", pdf_path.name)
        storage_path = f"{comprobante_id}/{safe_name}"
        try:
            self._client.upload(
                BUCKET, storage_path, pdf_path.read_bytes(), "application/pdf"
            )
            patch["doc_storage_path"] = storage_path
        except SupabaseError as error:
            storage_error = error
            storage_path = None
        drive_file_id = None
        if drive_result and drive_result.get("file_id"):
            drive_file_id = str(drive_result["file_id"])
            patch["doc_drive_file_id"] = drive_file_id
            patch["doc_drive_link"] = drive_result.get("link")
        if patch:
            patch["doc_nombre"] = pdf_path.name
            patch["doc_subido_at"] = _now()
            self._client.update(
                "comprobantes", {"id": f"eq.{comprobante_id}"}, patch
            )
        if storage_error is not None:
            if not drive_file_id:
                raise SupabaseSyncError(
                    f"No se pudo subir el PDF a Storage: {storage_error}"
                )
            print(
                f"  [Supabase] Aviso: no se pudo subir a Storage ({storage_error}); "
                "se guardó solo el enlace de Drive."
            )
        return storage_path, drive_file_id

    def _load_concepts(self) -> list[_Concept]:
        if self._concepts is None:
            self._concepts = self._read_concepts()
        return self._concepts

    def _read_concepts(self) -> list[_Concept]:
        rows = self._client.select(
            "conceptos",
            {
                "select": "*,conceptos__proveed_r(proveedores(nombre))",
                "inhabilitado": "eq.false",
            },
        )
        concepts = []
        for row in rows:
            names = [
                rel["proveedores"]["nombre"]
                for rel in row.get("conceptos__proveed_r") or []
                if rel.get("proveedores")
            ]
            if row.get("sub_concepto"):
                names.append(str(row["sub_concepto"]))
            concepts.append(
                _Concept(int(row["id"]), " ".join(names), row.get("Identificador"))
            )
        return concepts

    def _find_concept_id(self, data: InvoiceData) -> int:
        provider_tokens = _meaningful_tokens(
            re.sub(r"\([^)]*\)", " ", data.provider_name)
        )
        bank_tokens = _meaningful_tokens(
            data.bank_name or "", ignored={"banco", "bank", "de", "del"}
        )
        if not provider_tokens:
            raise SupabaseSyncError(
                "No se pudo identificar el proveedor para buscar el concepto."
            )
        wanted = provider_tokens | bank_tokens
        detail = f"proveedor '{data.provider_name}'" + (
            f" y banco '{data.bank_name}'" if data.bank_name else ""
        )
        matches = [
            c
            for c in self._load_concepts()
            if _meaningful_tokens(c.name).issuperset(wanted)
        ]
        if not matches:
            raise SupabaseSyncError(
                f"No se encontró un concepto para {detail} en conceptos."
            )

        by_identifier = [
            c
            for c in matches
            if _identifier_matches(c.identifier, data.account_identifier)
        ]
        if by_identifier:
            if len(by_identifier) > 1:
                raise SupabaseSyncError(
                    f"Hay varios conceptos con el mismo identificador para {detail}."
                )
            return by_identifier[0].id

        if any(_identifier_has_value(c.identifier) for c in matches):
            if data.account_identifier is None:
                raise SupabaseSyncError(
                    "No se pudo extraer el identificador de cliente/cuenta/"
                    f"servicio para buscar el concepto de {detail}."
                )
            raise SupabaseSyncError(
                f"No se encontró un concepto para {detail} con el "
                "identificador extraído."
            )

        exact = [c for c in matches if _meaningful_tokens(c.name) == wanted]
        if len(exact) == 1:
            return exact[0].id
        if exact:
            matches = exact
        if len(matches) > 1:
            raise SupabaseSyncError(
                f"Hay varios conceptos para {detail}; no se creó ni actualizó "
                "el comprobante. Cargá el Identificador en cada concepto para "
                "poder distinguirlos."
            )
        return matches[0].id

    @staticmethod
    def _pick_among_duplicates(candidates: list[dict], fields: dict[str, Any]) -> list[dict]:
        """Desempata comprobantes con el mismo concepto y vencimiento por el importe del documento.

        Solo se elige si exactamente un candidato tiene los mismos importes que el PDF; si no,
        no se actualiza ninguno (nunca se adivina). `nro_doc` (1, 2, ...) ordena los candidatos
        en el mensaje para que se identifiquen a mano.
        """
        def same(row: dict) -> bool:
            for name in ("importe_pesos", "importe_usd"):
                if name in fields and not _same_amount(row.get(name), fields[name]):
                    return False
            return any(name in fields for name in ("importe_pesos", "importe_usd"))

        matching = [row for row in candidates if same(row)]
        if len(matching) == 1:
            return matching
        ids = ", ".join(
            f"#{row['id']}" + (f" (nro_doc {row['nro_doc']})" if row.get("nro_doc") else "")
            for row in sorted(candidates, key=lambda r: (r.get("nro_doc") or 0, r["id"]))
        )
        raise SupabaseSyncError(
            "Hay varios comprobantes para el mismo concepto y vencimiento actual "
            f"({ids}) y el importe del documento no permite elegir uno; no se actualizó ninguno."
        )

    @staticmethod
    def _invoice_fields(data: InvoiceData, concept_id: int) -> dict[str, Any]:
        fields: dict[str, Any] = {"concepto_id": concept_id}
        amount_ars = data.amount_ars if data.amount_ars is not None else data.amount
        optional = (
            ("fecha_vto", data.current_due_date),
            ("prox_vto", data.next_due_date),
            ("cierre_actual", data.current_closing_date),
            ("prox_cierre", data.next_closing_date),
            ("importe_pesos", amount_ars),
            ("importe_usd", data.amount_usd),
        )
        for name, value in optional:
            if value is not None and value != "":
                fields[name] = format(value, "f") if isinstance(value, Decimal) else value
        fields["ultima_modificacion"] = _now()
        return fields


def _same_amount(stored: Any, new: Any) -> bool:
    if stored is None or new is None:
        return False
    try:
        return Decimal(str(stored)) == Decimal(str(new))
    except ArithmeticError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _meaningful_tokens(value: str, *, ignored: set[str] | None = None) -> set[str]:
    return set(_normalized_tokens(value)) - (
        {"prisma", "servicio", "proveedor"} | (ignored or set())
    )


def _normalized_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", normalized)


def _identifier_matches(value: Any, identifier: str | None) -> bool:
    if identifier is None:
        return False
    return _normalized_identifier(value) == _normalized_identifier(identifier)


def _identifier_has_value(value: Any) -> bool:
    return _normalized_identifier(value) != ""


def _normalized_identifier(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"[\W_]", "", normalized)
