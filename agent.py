#!/usr/bin/env python3
"""Agente de ejecuciones: toma pedidos de la interfaz web y corre main.py.

Uso:
    python agent.py                    # escucha la cola (runner = agente)
    python agent.py --ejecucion 123    # corre una ejecución puntual (GitHub Actions)

Variables: SUPABASE_URL, SUPABASE_SERVICE_KEY (obligatorias) y AGENT_NAME
(opcional, por defecto el nombre del equipo). Corre igual en tu PC o en una VM.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from integrations.supabase_sync.client import (
    SupabaseClient,
    SupabaseConfigurationError,
    SupabaseError,
)

ROOT = Path(__file__).resolve().parent
POLL_SECONDS = 5
STALE_AFTER = timedelta(minutes=2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_argv(row: dict) -> list[str]:
    """Arma la línea de comandos de main.py para una ejecución."""
    portal = (row.get("proveedor_portales") or {}).get("codigo")
    args = row.get("args") or {}
    action = row["accion"]
    argv = [sys.executable, "main.py", "--ejecucion-id", str(row["id"])]
    argv += ["--proveedor", portal] if portal else ["--todos-proveedores"]
    if action == "ingresar":
        if not portal:
            raise ValueError("--ingresar requiere un proveedor.")
        argv.append("--ingresar")
    else:
        argv.append("--supabase")
        if action == "debug":
            argv.append("--debug")
        if args.get("cuenta"):
            argv += ["--cuenta", str(args["cuenta"])]
        else:
            argv.append("--todas")
        if args.get("nosession"):
            argv.append("--nosession")
    perfil = args.get("perfil")
    if perfil:
        argv += ["--perfil", str(perfil)]
    return argv


def run_execution(client: SupabaseClient, row: dict) -> int:
    try:
        argv = build_argv(row)
    except ValueError as error:
        client.update(
            "ejecuciones",
            {"id": f"eq.{row['id']}"},
            {"estado": "error", "fin_at": _now(), "resumen": str(error)},
        )
        return 2
    print(f"[Agente] Ejecución {row['id']}: {' '.join(argv[1:])}")
    result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL)
    # Si main.py murió sin cerrar su estado, se marca como error.
    current = client.select_one(
        "ejecuciones", {"id": f"eq.{row['id']}", "select": "estado"}
    )
    if current and current["estado"] in ("pendiente", "en_curso", "esperando_input"):
        client.update(
            "ejecuciones",
            {"id": f"eq.{row['id']}"},
            {
                "estado": "error",
                "fin_at": _now(),
                "resumen": f"El proceso terminó sin informar estado (código {result.returncode}).",
            },
        )
    return result.returncode


def claim(client: SupabaseClient, filters: dict[str, str], name: str) -> dict | None:
    """Reclama la ejecución pendiente más antigua de forma atómica."""
    if "id" not in filters:
        oldest = client.select_one(
            "ejecuciones",
            {**filters, "estado": "eq.pendiente", "select": "id", "order": "creada_at.asc"},
        )
        if oldest is None:
            return None
        filters = {"id": f"eq.{oldest['id']}"}
    rows = client.update(
        "ejecuciones",
        {**filters, "estado": "eq.pendiente"},
        {"estado": "en_curso", "agente": name, "inicio_at": _now(), "heartbeat_at": _now()},
    )
    if not rows:
        return None  # otro agente la reclamó primero
    return client.select_one(
        "ejecuciones",
        {"id": f"eq.{rows[0]['id']}", "select": "*,proveedor_portales(codigo)"},
    )


def recover_stale(client: SupabaseClient, name: str) -> None:
    limit = (datetime.now(timezone.utc) - STALE_AFTER).isoformat()
    client.update(
        "ejecuciones",
        {
            "agente": f"eq.{name}",
            "estado": "in.(en_curso,esperando_input)",
            "heartbeat_at": f"lt.{limit}",
        },
        {"estado": "error", "fin_at": _now(), "resumen": "El agente se reinició durante la ejecución."},
    )


def main() -> int:
    try:
        client = SupabaseClient()
    except SupabaseConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    name = os.environ.get("AGENT_NAME") or socket.gethostname()
    os.environ["AGENT_NAME"] = name

    if "--ejecucion" in sys.argv:
        execution_id = sys.argv[sys.argv.index("--ejecucion") + 1]
        row = claim(client, {"id": f"eq.{execution_id}"}, name)
        if row is None:
            print(f"La ejecución {execution_id} no está pendiente.", file=sys.stderr)
            return 1
        return run_execution(client, row)

    recover_stale(client, name)
    print(f"[Agente] {name} escuchando ejecuciones pendientes (Ctrl+C para salir).")
    while True:
        try:
            row = claim(client, {"runner": "eq.agente"}, name)
            if row is not None:
                run_execution(client, row)
                continue
        except SupabaseError as error:
            print(f"[Agente] {error}", file=sys.stderr)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[Agente] Detenido.")
