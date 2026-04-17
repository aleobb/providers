from __future__ import annotations

from dataclasses import dataclass, field

from .exceptions import InvoiceDownloaderError


@dataclass
class Account:
    client_number: str
    display_name: str
    address: str
    extra: dict[str, str] = field(default_factory=dict)

    def display(self, index: int) -> str:
        lines = [f"  [{index}] {self.display_name}", f"       {self.address}", f"       N° {self.client_number}"]
        for key, val in self.extra.items():
            if val:
                lines.append(f"       {key}: {val}")
        return "\n".join(lines)


def select_account(accounts: list[Account], cuenta_arg: str | None) -> Account:
    if len(accounts) == 1:
        return accounts[0]

    if cuenta_arg is not None:
        try:
            idx = int(cuenta_arg) - 1
            if 0 <= idx < len(accounts):
                return accounts[idx]
        except ValueError:
            for acc in accounts:
                if cuenta_arg in acc.client_number:
                    return acc
        raise InvoiceDownloaderError(
            f"Cuenta '{cuenta_arg}' no encontrada. "
            f"Usar un número entre 1 y {len(accounts)} o el N° de cliente."
        )

    # Interactive prompt
    print("\nCuentas disponibles:")
    for i, acc in enumerate(accounts, 1):
        print(acc.display(i))
    print()

    while True:
        try:
            raw = input(f"Seleccionar cuenta [1-{len(accounts)}]: ").strip()
            idx = int(raw) - 1
            if 0 <= idx < len(accounts):
                return accounts[idx]
            print(f"  Ingresar un número entre 1 y {len(accounts)}.")
        except (ValueError, EOFError):
            print("  Ingresar un número válido.")
