from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.exceptions import ConfigurationError
from pdfminer.pdfexceptions import PDFException

from .card_statement import detect_card_provider
from .csv_export import invoice_data_to_csv_row, write_invoice_data_csv
from .extractor import _read_text
from .invoice_data import extract_invoice_data_from_text


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrae datos comunes y de tarjetas desde PDFs existentes."
    )
    parser.add_argument("pdfs", nargs="*", help="Archivos PDF a procesar")
    parser.add_argument("--dir", type=Path, help="Carpeta con PDFs")
    parser.add_argument(
        "--proveedor",
        help="Proveedor para PDFs no identificados como layouts de tarjeta",
    )
    parser.add_argument("--csv", type=Path, help="Ruta del CSV de salida")
    args = parser.parse_args()
    if not args.pdfs and args.dir is None:
        parser.error("Indicá al menos un PDF o --dir")
    return args


def main() -> int:
    args = _parse_args()
    paths = [Path(path) for path in args.pdfs]
    if args.dir is not None:
        paths.extend(sorted(args.dir.glob("*.pdf")))
    if not paths:
        print("No se encontraron archivos PDF para procesar.", file=sys.stderr)
        return 1

    import providers  # noqa: F401
    from core.registry import get_provider

    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for path in paths:
        try:
            text = _read_text(path, max_pages=None)
        except (OSError, ValueError, PDFException) as error:
            errors.append(f"{path}: {error}")
            continue

        provider_name = detect_card_provider(text) or args.proveedor
        if not provider_name:
            errors.append(
                f"{path}: layout de tarjeta no reconocido; "
                "indicá --proveedor para usar patrones comunes."
            )
            continue
        try:
            provider = get_provider(provider_name.lower())
        except ConfigurationError as error:
            errors.append(f"{path}: {error}")
            continue

        data = extract_invoice_data_from_text(text, provider)
        row = invoice_data_to_csv_row(path, data)
        rows.append(row)
        print(
            f"{path.name}: proveedor={data.provider_name}; "
            f"banco={data.bank_name or '-'}; "
            f"importe={row['importe'] or '-'}; "
            f"vencimiento_actual={data.current_due_date or '-'}; "
            f"proximo_vencimiento={data.next_due_date or '-'}; "
            f"cierre_actual={data.current_closing_date or '-'}; "
            f"proximo_cierre={data.next_closing_date or '-'}; "
            f"importe_pesos={row['importe_pesos'] or '-'}; "
            f"importe_dolares={row['importe_dolares'] or '-'}"
        )

    if args.csv is not None:
        try:
            write_invoice_data_csv(args.csv, rows)
        except OSError as error:
            print(f"No se pudo escribir el CSV {args.csv}: {error}", file=sys.stderr)
            return 1
        print(f"CSV guardado en: {args.csv}")

    if errors:
        print("\nERRORES:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
