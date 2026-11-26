#!/usr/bin/env python3
"""Agente de ejecuciones: toma pedidos de la interfaz web y corre main.py.

Uso:
    python agent.py                    # escucha la cola (runner = agente)
    python agent.py --ejecucion 123    # corre una ejecución puntual (GitHub Actions)

Variables: SUPABASE_URL, SUPABASE_SERVICE_KEY (obligatorias) y AGENT_NAME
(opcional, por defecto el nombre del equipo). Corre igual en tu PC o en una VM.
AGENT_RUN_TIMEOUT_MIN limita la duración de una descarga (45 min en el agente, 25 en GitHub Actions;
0 = sin límite). "debug" e "ingresar" son interactivas y no tienen límite.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vm_exec
from integrations.supabase_sync.client import (
    SupabaseClient,
    SupabaseConfigurationError,
    SupabaseError,
)

ROOT = Path(__file__).resolve().parent
POLL_SECONDS = 5
STALE_AFTER = timedelta(minutes=2)
RUN_TIMEOUT_MIN = 45  # agente (PC o VM)
ACTIONS_TIMEOUT_MIN = 25  # el workflow de GitHub Actions corta a los 30
_AUTO = object()  # "calcular el límite según la acción"


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


def run_timeout_minutes(action: str, default: int = RUN_TIMEOUT_MIN) -> int | None:
    """Minutos máximos de una ejecución, o None si no hay límite (acciones interactivas o 0 en el entorno)."""
    if action != "descargar":
        return None
    raw = os.environ.get("AGENT_RUN_TIMEOUT_MIN", "").strip()
    try:
        minutes = int(raw) if raw else default
    except ValueError:
        minutes = default
    return minutes if minutes > 0 else None


def _kill_tree(proc: subprocess.Popen) -> None:
    """Corta el proceso y todo lo que lanzó (el navegador de Playwright incluido)."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)  # gracia para que los hijos cierren; lo que siga vivo se corta
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # el grupo ya no existe: terminaron todos
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_process(argv: list[str], cwd: Path, timeout_s: float | None) -> tuple[int, bool]:
    """Corre argv y devuelve (código, vencido). Si vence, corta el árbol de procesos completo."""
    kwargs: dict = {"cwd": cwd, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # grupo propio: se puede cortar con todos sus hijos
    proc = subprocess.Popen(argv, **kwargs)
    try:
        return proc.wait(timeout=timeout_s), False
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return (proc.returncode if proc.returncode is not None else -9), True
    except BaseException:  # Ctrl+C o cierre del agente: no dejar el navegador huérfano
        _kill_tree(proc)
        raise


def run_execution(client: SupabaseClient, row: dict, timeout_min=_AUTO) -> int:
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
    if timeout_min is _AUTO:
        timeout_min = run_timeout_minutes(row["accion"])
    returncode, timed_out = run_process(argv, ROOT, timeout_min * 60 if timeout_min else None)
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
                "resumen": (
                    f"Superó el tiempo máximo ({timeout_min} min) y el agente la cortó."
                    if timed_out
                    else f"El proceso terminó sin informar estado (código {returncode})."
                ),
            },
        )
    return returncode


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
        position = sys.argv.index("--ejecucion") + 1
        execution_id = sys.argv[position] if position < len(sys.argv) else ""
        if not execution_id.isdigit():
            print("ERROR: --ejecucion requiere el número de la ejecución.", file=sys.stderr)
            return 2
        row = claim(client, {"id": f"eq.{execution_id}"}, name)
        if row is None:
            print(f"La ejecución {execution_id} no está pendiente.", file=sys.stderr)
            return 1
        return run_execution(
            client, row, run_timeout_minutes(row["accion"], default=ACTIONS_TIMEOUT_MIN)
        )

    recover_stale(client, name)
    vm_enabled = bool(os.environ.get("VM_APPROVAL_KEY", "").strip())
    if vm_enabled:
        try:
            vm_exec.recover_interrupted(client, name)
        except SupabaseError as error:
            print(f"[Agente] vm_comandos: {error}", file=sys.stderr)
    print(f"[Agente] {name} escuchando ejecuciones pendientes (Ctrl+C para salir).")
    if vm_enabled:
        print("[Agente] Comandos de la VM con aprobación: activados.")
    while True:
        try:
            row = claim(client, {"runner": "eq.agente"}, name)
            if row is not None:
                run_execution(client, row)
                continue
            if vm_enabled and vm_exec.run_pending(client, name):
                continue
        except SupabaseError as error:
            print(f"[Agente] {error}", file=sys.stderr)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[Agente] Detenido.")
