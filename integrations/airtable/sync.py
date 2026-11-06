from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import requests
from pyairtable.formulas import Field, IS_SAME

from integrations.pdf_extractor.invoice_data import InvoiceData


class AirtableConfigurationError(Exception):
    """Raised when the Airtable connection is not configured."""


class AirtableSyncError(Exception):
    """Raised when an extracted invoice cannot be synchronized."""


@dataclass(frozen=True)
class AirtableConfig:
    token: str
    base_id: str
    invoices_table: str = "Comprobantes"
    concepts_table: str = "Conceptos"
    subjects_table: str = "Sujetos"
    concept_name_field: str = "Nombre"
    concept_link_field: str = "Concepto"
    concept_subject_field: str = "Sujeto"
    subject_name_field: str = "Indentificacion"
    default_subject_name: str = "Alejandro"
    invoice_attachment_field: str = "Doc."
    invoice_due_date_field: str = "Fecha Vto."
    invoice_next_due_date_field: str = "Prox.Vto."
    invoice_closing_date_field: str = "Cierre Actual"
    invoice_next_closing_date_field: str = "Prox.Cierre"
    invoice_amount_ars_field: str = "Importe Pesos"
    invoice_amount_usd_field: str = "Importe USD"

    @classmethod
    def from_env(cls) -> AirtableConfig:
        token = os.environ.get("AIRTABLE_TOKEN", "").strip()
        base_id = os.environ.get("AIRTABLE_BASE_ID", "").strip()
        if not token or not base_id:
            missing = [
                name
                for name, value in (
                    ("AIRTABLE_TOKEN", token),
                    ("AIRTABLE_BASE_ID", base_id),
                )
                if not value
            ]
            raise AirtableConfigurationError(
                f"Falta configurar: {', '.join(missing)}."
            )

        def configured(name: str, default: str) -> str:
            return os.environ.get(name, "").strip() or default

        return cls(
            token=token,
            base_id=base_id,
            invoices_table=configured(
                "AIRTABLE_COMPROBANTES_TABLE", "Comprobantes"
            ),
            concepts_table=configured("AIRTABLE_CONCEPTOS_TABLE", "Conceptos"),
            subjects_table=configured("AIRTABLE_SUJETOS_TABLE", "Sujetos"),
            concept_name_field=configured(
                "AIRTABLE_CONCEPTO_NOMBRE_FIELD", "Nombre"
            ),
            concept_link_field=configured(
                "AIRTABLE_CONCEPTO_FIELD", "Concepto"
            ),
            concept_subject_field=configured(
                "AIRTABLE_CONCEPTO_SUJETO_FIELD", "Sujeto"
            ),
            subject_name_field=configured(
                "AIRTABLE_SUJETO_NOMBRE_FIELD", "Indentificacion"
            ),
            default_subject_name=configured(
                "AIRTABLE_SUJETO_PREDETERMINADO", "Alejandro"
            ),
            invoice_attachment_field=configured(
                "AIRTABLE_DOCUMENTO_FIELD", "Doc."
            ),
            invoice_due_date_field=configured(
                "AIRTABLE_VENCIMIENTO_FIELD", "Fecha Vto."
            ),
            invoice_next_due_date_field=configured(
                "AIRTABLE_PROXIMO_VENCIMIENTO_FIELD", "Prox.Vto."
            ),
            invoice_closing_date_field=configured(
                "AIRTABLE_CIERRE_FIELD", "Cierre Actual"
            ),
            invoice_next_closing_date_field=configured(
                "AIRTABLE_PROXIMO_CIERRE_FIELD", "Prox.Cierre"
            ),
            invoice_amount_ars_field=configured(
                "AIRTABLE_IMPORTE_PESOS_FIELD", "Importe Pesos"
            ),
            invoice_amount_usd_field=configured(
                "AIRTABLE_IMPORTE_DOLARES_FIELD", "Importe USD"
            ),
        )


@dataclass(frozen=True)
class AirtableSyncResult:
    record_id: str
    created: bool
    attachment_uploaded: bool


class AirtableInvoiceSync:
    """Create or update Comprobantes using extracted PDF data."""

    def __init__(self, config: AirtableConfig, api: Any | None = None) -> None:
        if api is None:
            from pyairtable import Api

            api = Api(config.token)
        self._config = config
        self._invoices = api.table(config.base_id, config.invoices_table)
        self._concepts = api.table(config.base_id, config.concepts_table)
        self._subjects = api.table(config.base_id, config.subjects_table)
        self._subject_name_cache: dict[str, str] | None = None

    def sync_invoice(
        self, pdf_path: Path, data: InvoiceData
    ) -> AirtableSyncResult:
        try:
            if not pdf_path.is_file():
                raise AirtableSyncError(
                    f"No se encontró el PDF para adjuntar: {pdf_path}."
                )
            if pdf_path.suffix.lower() != ".pdf":
                raise AirtableSyncError(
                    f"El documento a adjuntar no es un PDF: {pdf_path.name}."
                )
            if not data.current_due_date:
                raise AirtableSyncError(
                    "No se encontró el vencimiento actual; no se puede "
                    "identificar el comprobante para actualizarlo."
                )
            try:
                date.fromisoformat(data.current_due_date)
            except ValueError as error:
                raise AirtableSyncError(
                    "El vencimiento actual no tiene formato YYYY-MM-DD; "
                    "no se puede identificar el comprobante."
                ) from error
            concept_id = self._find_concept_id(data)
            fields = self._invoice_fields(data, concept_id)
            candidates = self._invoices.all(
                formula=IS_SAME(
                    Field(self._config.invoice_due_date_field),
                    data.current_due_date,
                    "day",
                ),
                fields=[
                    self._config.concept_link_field,
                    self._config.invoice_due_date_field,
                    self._config.invoice_attachment_field,
                ],
            )
            existing = [
                record
                for record in candidates
                if concept_id
                in (record.get("fields", {}).get(self._config.concept_link_field) or [])
            ]
            if len(existing) > 1:
                raise AirtableSyncError(
                    "Hay varios comprobantes para el mismo concepto y "
                    "vencimiento actual; no se actualizó ninguno."
                )
            if existing:
                record = self._invoices.update(
                    existing[0]["id"], fields, typecast=True
                )
                created = False
                attachments = (
                    existing[0]
                    .get("fields", {})
                    .get(self._config.invoice_attachment_field, [])
                )
            else:
                record = self._invoices.create(fields, typecast=True)
                created = True
                attachments = []

            has_attachment = bool(attachments)
            if not has_attachment:
                self._invoices.upload_attachment(
                    record["id"],
                    self._config.invoice_attachment_field,
                    pdf_path,
                    content_type="application/pdf",
                )
            return AirtableSyncResult(
                record_id=record["id"],
                created=created,
                attachment_uploaded=not has_attachment,
            )
        except AirtableSyncError:
            raise
        except requests.HTTPError as error:
            response = error.response
            status = response.status_code if response is not None else "?"
            detail = response.text if response is not None else str(error)
            raise AirtableSyncError(
                f"Error de Airtable ({status}): {detail}"
            ) from error
        except requests.RequestException as error:
            raise AirtableSyncError(
                f"No se pudo conectar con Airtable: {error}"
            ) from error
        except OSError as error:
            raise AirtableSyncError(
                f"No se pudo leer o adjuntar el PDF {pdf_path.name}: {error}"
            ) from error

    def _find_concept_id(self, data: InvoiceData) -> str:
        provider_tokens = _meaningful_tokens(
            re.sub(r"\([^)]*\)", " ", data.provider_name)
        )
        bank_tokens = _meaningful_tokens(
            data.bank_name or "", ignored={"banco", "bank", "de", "del"}
        )
        if not provider_tokens:
            raise AirtableSyncError(
                "No se pudo identificar el proveedor para buscar el concepto."
            )
        records = self._concepts.all(
            fields=[
                self._config.concept_name_field,
                self._config.concept_subject_field,
            ]
        )
        matches = [
            record
            for record in records
            if _meaningful_tokens(
                str(
                    record.get("fields", {}).get(
                        self._config.concept_name_field, ""
                    )
                )
            ).issuperset(provider_tokens | bank_tokens)
        ]
        if not matches:
            detail = (
                f"proveedor '{data.provider_name}'"
                + (f" y banco '{data.bank_name}'" if data.bank_name else "")
            )
            raise AirtableSyncError(
                f"No se encontró un concepto para {detail} en "
                f"{self._config.concepts_table}."
            )

        subject_linked_matches = [
            record
            for record in matches
            if record.get("fields", {}).get(self._config.concept_subject_field)
        ]
        if subject_linked_matches:
            desired_subject = data.holder_name or self._config.default_subject_name
            subject_matches = [
                record
                for record in subject_linked_matches
                if any(
                    _subject_name_matches(
                        self._subject_name(subject_id),
                        desired_subject,
                    )
                    for subject_id in record["fields"][
                        self._config.concept_subject_field
                    ]
                )
            ]
            if not subject_matches:
                raise AirtableSyncError(
                    f"No se encontró un concepto para proveedor "
                    f"'{data.provider_name}', banco "
                    f"'{data.bank_name or '-'}' y sujeto "
                    f"'{desired_subject}'."
                )
            matches = subject_matches

        exact_matches = [
            record
            for record in matches
            if _meaningful_tokens(
                str(
                    record.get("fields", {}).get(
                        self._config.concept_name_field, ""
                    )
                )
            )
            == (provider_tokens | bank_tokens)
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]["id"]
        if exact_matches:
            matches = exact_matches
        if len(matches) > 1:
            raise AirtableSyncError(
                f"Hay varios conceptos para proveedor '{data.provider_name}'"
                + (f" y banco '{data.bank_name}'" if data.bank_name else "")
                + f" y sujeto '{data.holder_name or self._config.default_subject_name}'"
                + "; no se creó ni actualizó el comprobante."
            )
        return matches[0]["id"]

    def _subject_name(self, subject_id: str) -> str:
        if self._subject_name_cache is None:
            records = self._subjects.all(
                fields=[self._config.subject_name_field]
            )
            self._subject_name_cache = {
                record["id"]: name.strip()
                for record in records
                if isinstance(
                    name := record.get("fields", {}).get(
                        self._config.subject_name_field
                    ),
                    str,
                )
                and name.strip()
            }
        name = self._subject_name_cache.get(subject_id)
        if name is None:
            raise AirtableSyncError(
                f"No se encontró el nombre del sujeto {subject_id} en "
                f"{self._config.subjects_table}."
            )
        return name

    def _invoice_fields(
        self, data: InvoiceData, concept_id: str
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            self._config.concept_link_field: [concept_id],
        }
        amount_ars = (
            data.amount_ars if data.amount_ars is not None else data.amount
        )
        optional_values: tuple[tuple[str, Any], ...] = (
            (self._config.invoice_due_date_field, data.current_due_date),
            (self._config.invoice_next_due_date_field, data.next_due_date),
            (self._config.invoice_closing_date_field, data.current_closing_date),
            (
                self._config.invoice_next_closing_date_field,
                data.next_closing_date,
            ),
            (self._config.invoice_amount_ars_field, amount_ars),
            (self._config.invoice_amount_usd_field, data.amount_usd),
        )
        for field_name, value in optional_values:
            if value is not None and value != "":
                fields[field_name] = (
                    format(value, "f") if isinstance(value, Decimal) else value
                )
        return fields


def _meaningful_tokens(
    value: str, *, ignored: set[str] | None = None
) -> set[str]:
    return set(_normalized_tokens(value)) - (
        {"prisma", "servicio", "proveedor"} | (ignored or set())
    )


def _normalized_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    return re.findall(r"[a-z0-9]+", normalized)


def _subject_name_matches(subject_name: str, holder_name: str) -> bool:
    subject_tokens = _normalized_tokens(subject_name)
    holder_tokens = _normalized_tokens(holder_name)
    if not subject_tokens or not holder_tokens:
        return False

    holder_index = 0
    for subject_token in subject_tokens:
        while holder_index < len(holder_tokens):
            holder_token = holder_tokens[holder_index]
            holder_index += 1
            if subject_token == holder_token or (
                len(subject_token) == 1
                and holder_token.startswith(subject_token)
            ):
                break
        else:
            return False
    return True
