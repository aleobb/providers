#!/usr/bin/env python3
"""Verifica la documentación de docs/: frontmatter (con resumen), enlaces relativos, IDs únicos, TL;DR por sección, índice y secretos.

Uso: python tools/docs_check.py
Código de salida 1 si hay errores. Los avisos (documentos sin revisar > 90 días) no fallan.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REQUIRED = ("id", "titulo", "estado", "ultima_revision", "resumen", "fuentes", "relacionados")
ESTADOS = {"borrador", "vigente", "obsoleto"}
STALE_DAYS = 90
SECRET_PATTERNS = {
    "token de GitHub": re.compile(r"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}"),
    "secret key de Supabase": re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}"),
    "clave de API de Anthropic": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    "token Fernet": re.compile(r"gAAAA[A-Za-z0-9_=-]{40,}"),
    "clave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "clave hexadecimal de 64 caracteres": re.compile(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{64}(?![A-Fa-f0-9])"),
}
LINK = re.compile(r"\]\(([^)\s]+)\)")

errors: list[str] = []
warnings: list[str] = []


def frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    if not DOCS.is_dir():
        print("No existe docs/")
        return 1
    files = sorted(p for p in DOCS.rglob("*.md") if "_plantillas" not in p.parts)
    ids: dict[str, str] = {}
    index_text = (DOCS / "README.md").read_text(encoding="utf-8") if (DOCS / "README.md").exists() else ""
    today = date.today()

    for path in files:
        text = path.read_text(encoding="utf-8")
        name = rel(path)
        fm = frontmatter(text)
        if fm is None:
            errors.append(f"{name}: falta el frontmatter (--- … ---)")
        else:
            for key in REQUIRED:
                if key not in fm:
                    errors.append(f"{name}: falta el campo '{key}' en el frontmatter")
            if fm.get("estado") and fm["estado"] not in ESTADOS:
                errors.append(f"{name}: estado '{fm['estado']}' inválido (usar {', '.join(sorted(ESTADOS))})")
            doc_id = fm.get("id", "")
            if doc_id:
                if doc_id in ids:
                    errors.append(f"{name}: id '{doc_id}' repetido (ya en {ids[doc_id]})")
                ids[doc_id] = name
            revised = fm.get("ultima_revision", "")
            try:
                age = (today - datetime.strptime(revised, "%Y-%m-%d").date()).days
                if age > STALE_DAYS and fm.get("estado") == "vigente":
                    warnings.append(f"{name}: sin revisar hace {age} días (estado vigente)")
            except ValueError:
                if revised:
                    errors.append(f"{name}: ultima_revision '{revised}' no es AAAA-MM-DD")
        if path.name != "README.md" and text.count("\n## ") != text.count("**TL;DR:**"):
            warnings.append(f"{name}: cada sección «## » debe llevar un «**TL;DR:**»")
        in_code = False
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target_path = (path.parent / target.split("#", 1)[0]).resolve()
                if not target_path.exists():
                    errors.append(f"{name}:{number}: enlace roto → {target}")
        if path.name != "README.md" or path.parent != DOCS:
            if name.removeprefix("docs/") not in index_text and path.parent != DOCS / "arquitectura" / "adr":
                warnings.append(f"{name}: no aparece en docs/README.md")

    scan = list(files) + [p for p in (ROOT / "AGENTS.md", ROOT / "README.md", ROOT / "CHANGELOG.md") if p.exists()]
    for path in scan:
        text = path.read_text(encoding="utf-8")
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{rel(path)}:{line}: posible secreto ({label}) — no versionar valores")

    for item in warnings:
        print(f"AVISO  {item}")
    for item in errors:
        print(f"ERROR  {item}")
    print(f"\n{len(files)} documentos revisados · {len(errors)} errores · {len(warnings)} avisos")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
