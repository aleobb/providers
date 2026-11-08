"""Ejecución gestionada: opciones nuevas, todas opcionales, para la interfaz web.

Sin ninguno de estos flags, `main.py` se comporta exactamente igual que antes.

  --supabase           Sincroniza cada comprobante descargado con Supabase
                       (tabla comprobantes + PDF en Storage + datos de Drive).
  --perfil <alias>     Elige el perfil de credenciales sin preguntar.
  --ejecucion-id <n>   Ejecuta como la ejecución <n> de Supabase: credenciales
                       desde Supabase, salida de consola guardada, consultas
                       (OTP, MFA, perfil, cuenta) respondidas desde la web,
                       estado y heartbeat actualizados. Implica --supabase.

Variables: SUPABASE_URL y SUPABASE_SERVICE_KEY. PROVIDERS_PROMPT_TIMEOUT
(segundos, 600 por defecto) limita la espera de una respuesta.
"""
from __future__ import annotations

import _thread
import asyncio
import os
import queue
import shutil
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import hooks, prompts

_MAX_LINE = 2000
_PUMP_SECONDS = 2.0
_HEARTBEAT_SECONDS = 20.0


def extract_flags(argv: list[str]) -> tuple[list[str], dict]:
    """Separa los flags gestionados del resto de los argumentos."""
    rest: list[str] = []
    opts: dict = {"supabase": False, "ejecucion_id": None, "perfil": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--supabase":
            opts["supabase"] = True
        elif arg == "--ejecucion-id" and i + 1 < len(argv):
            try:
                opts["ejecucion_id"] = int(argv[i + 1])
            except ValueError:
                print("--ejecucion-id requiere un número.", file=sys.stderr)
                sys.exit(2)
            i += 1
        elif arg == "--perfil" and i + 1 < len(argv):
            opts["perfil"] = argv[i + 1]
            i += 1
        else:
            rest.append(arg)
        i += 1
    return rest, opts


def run_with_management(main_fn: Callable[[], None]) -> None:
    rest, opts = extract_flags(sys.argv[1:])
    if not (opts["supabase"] or opts["ejecucion_id"] or opts["perfil"]):
        main_fn()
        return

    sys.argv = [sys.argv[0], *rest]
    if opts["perfil"]:
        os.environ["PROVIDERS_PROFILE_ALIAS"] = opts["perfil"]
    if not (opts["supabase"] or opts["ejecucion_id"]):
        main_fn()
        return

    from integrations.supabase_sync.client import (
        SupabaseClient,
        SupabaseConfigurationError,
    )

    try:
        client = SupabaseClient()
    except SupabaseConfigurationError as error:
        print(f"ERROR [Supabase]: {error}", file=sys.stderr)
        sys.exit(2)

    hooks.register_post_download(_make_sync_hook(client), name="Supabase")
    run = ManagedRun(client, opts["ejecucion_id"]) if opts["ejecucion_id"] else None
    code = 0
    try:
        if run:
            run.start()
        main_fn()
    except SystemExit as exit_info:
        code = exit_info.code if isinstance(exit_info.code, int) else (
            0 if exit_info.code is None else 1
        )
        raise
    except BaseException:
        code = 1
        raise
    finally:
        if run:
            run.finish(code)


def _make_sync_hook(client):
    from integrations.supabase_sync.sync import SupabaseInvoiceSync

    sync = SupabaseInvoiceSync(client)

    async def supabase_sync(*, path, invoice_data, drive_result=None, **_):
        result = await asyncio.to_thread(
            sync.sync_invoice, path, invoice_data, drive_result
        )
        action = "creado" if result.created else "actualizado"
        print(f"  [Supabase] Comprobante {action}: {result.comprobante_id}")
        if result.documento_subido:
            print("  [Supabase] Documento guardado (Storage/Drive).")
        else:
            print("  [Supabase] El comprobante ya tenía documento; no se duplicó.")
        hooks.stats["synced"] += 1

    return supabase_sync


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Tee:
    """Copia lo escrito a la consola original y al registro de la ejecución."""

    def __init__(self, original, level: str, sink: Callable[[str, str], None]):
        self._original = original
        self._level = level
        self._sink = sink

    def write(self, text):
        written = self._original.write(text)
        try:
            self._sink(self._level, text)
        except Exception:  # noqa: BLE001 - el registro nunca rompe la salida
            pass
        return written

    def flush(self):
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


class ManagedRun:
    def __init__(self, client, execution_id: int) -> None:
        self.client = client
        self.id = execution_id
        self._tmp = Path(tempfile.mkdtemp(prefix="providers_run_"))
        self._log_path = self._tmp / f"ejecucion_{execution_id}.log"
        self._log_file = None
        self._queue: queue.Queue = queue.Queue()
        self._pending: list[dict] = []
        self._buffers = {"info": "", "error": ""}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cancelled = False
        self._streams: tuple | None = None

    # ---------------------------------------------------------------- ciclo
    def start(self) -> None:
        row = self.client.select_one(
            "ejecuciones",
            {"id": f"eq.{self.id}", "select": "*,proveedor_portales(codigo)"},
        )
        if row is None:
            print(f"ERROR: no existe la ejecución {self.id}.", file=sys.stderr)
            sys.exit(2)
        patch = {
            "estado": "en_curso",
            "agente": os.environ.get("AGENT_NAME")
            or ("github-actions" if os.environ.get("GITHUB_ACTIONS") else socket.gethostname()),
            "heartbeat_at": _now(),
        }
        if not row.get("inicio_at"):
            patch["inicio_at"] = _now()
        if os.environ.get("GITHUB_RUN_ID"):
            patch["github_run_id"] = os.environ["GITHUB_RUN_ID"]
        self.client.update("ejecuciones", {"id": f"eq.{self.id}"}, patch)

        self._log_file = self._log_path.open("a", encoding="utf-8")
        self._streams = (sys.stdout, sys.stderr)
        sys.stdout = _Tee(sys.stdout, "info", self._on_text)
        sys.stderr = _Tee(sys.stderr, "error", self._on_text)
        prompts.set_broker(self._broker)
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        try:
            self._prepare_environment(row)
        except SystemExit:
            raise
        except Exception as error:  # noqa: BLE001
            print(f"ERROR: no se pudo preparar la ejecución: {error}", file=sys.stderr)
            sys.exit(2)

    def finish(self, code: int) -> None:
        if self._cancelled:
            state = "cancelada"
        elif code == 0 and not hooks.stats["errors"]:
            state = "ok"
        else:
            state = "error"
        prompts.set_broker(None)
        if self._streams:
            sys.stdout, sys.stderr = self._streams
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._flush_buffers()
        self._send_logs(final=True)
        if self._log_file:
            self._log_file.close()
        patch = {
            "estado": state,
            "fin_at": _now(),
            "resumen": (
                f"{hooks.stats['synced']} comprobante(s) sincronizado(s); "
                f"{hooks.stats['errors']} error(es) de sincronización; "
                f"código de salida {code}"
            ),
        }
        try:
            data = self._log_path.read_bytes()
            self.client.upload("ejecucion-logs", f"{self.id}.log", data, "text/plain")
            patch["log_storage_path"] = f"ejecucion-logs/{self.id}.log"
        except Exception as error:  # noqa: BLE001
            print(f"[Supabase] No se pudo subir el log completo: {error}", file=sys.stderr)
        try:
            self.client.update("ejecuciones", {"id": f"eq.{self.id}"}, patch)
        except Exception as error:  # noqa: BLE001
            print(f"[Supabase] No se pudo actualizar el estado: {error}", file=sys.stderr)
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------ entorno
    def _prepare_environment(self, row: dict) -> None:
        """Credenciales desde Supabase en un almacén temporal + config del portal."""
        from cryptography.fernet import Fernet

        from .credential_store import CredentialStore, CredentialStoreError

        if row.get("perfil_id"):
            filters = {"id": f"eq.{row['perfil_id']}"}
        elif row.get("portal_id"):
            filters = {"portal_id": f"eq.{row['portal_id']}"}
        else:
            filters = {}
        profiles = self.client.select(
            "portal_perfiles",
            {
                **filters,
                "select": "id,alias,proveedor_portales(codigo,activo,config)",
                "order": "id",
            },
        )
        if not filters:
            profiles = [
                p for p in profiles if (p.get("proveedor_portales") or {}).get("activo")
            ]

        os.environ["PROVIDERS_CREDENTIALS_KEY"] = Fernet.generate_key().decode()
        os.environ["PROVIDERS_CREDENTIALS_DB"] = str(self._tmp / "providers.sqlite3")
        store = CredentialStore()
        # Marca la migración desde .env como hecha: el almacén temporal no debe
        # tocar el .env del repositorio.
        store.import_legacy_dotenv_once(self._tmp / "sin-env")

        loaded = 0
        for profile in profiles:
            portal = profile.get("proveedor_portales") or {}
            for key, value in (portal.get("config") or {}).items():
                os.environ.setdefault(str(key), str(value))
            credentials = self.client.rpc(
                "get_perfil_credenciales", {"p_perfil_id": profile["id"]}
            )
            if not credentials:
                print(
                    f"[Credenciales] El perfil «{profile['alias']}» de "
                    f"{portal.get('codigo')} no tiene credenciales guardadas.",
                    file=sys.stderr,
                )
                continue
            try:
                store.add_profile(portal["codigo"], profile["alias"], credentials)
                loaded += 1
            except CredentialStoreError as error:
                print(f"[Credenciales] {error}", file=sys.stderr)
        print(f"[Credenciales] {loaded} perfil(es) cargado(s) desde Supabase.")

    # ----------------------------------------------------------- registro
    def _on_text(self, level: str, text: str) -> None:
        with self._lock:
            buffer = self._buffers[level] + text
            *lines, self._buffers[level] = buffer.split("\n")
            for line in lines:
                line = line.rstrip("\r")
                if not line.strip():
                    continue
                line = line[:_MAX_LINE]
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if self._log_file:
                    marker = "ERR" if level == "error" else "   "
                    self._log_file.write(f"[{stamp}] {marker} {line}\n")
                    self._log_file.flush()
                self._queue.put({"ejecucion_id": self.id, "nivel": level, "linea": line, "ts": _now()})

    def _flush_buffers(self) -> None:
        for level in ("info", "error"):
            if self._buffers[level].strip():
                self._on_text(level, "\n")

    def _send_logs(self, final: bool = False) -> None:
        while True:
            try:
                self._pending.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if not self._pending:
            return
        batch = self._pending[:500]
        try:
            self.client.insert("ejecucion_logs", batch)
            del self._pending[: len(batch)]
        except Exception:  # noqa: BLE001 - se reintenta en la próxima vuelta
            if len(self._pending) > 5000:
                del self._pending[:-5000]
            if final:
                self._pending.clear()

    def _pump(self) -> None:
        last_beat = 0.0
        while not self._stop.wait(_PUMP_SECONDS):
            self._send_logs()
            if time.monotonic() - last_beat >= _HEARTBEAT_SECONDS:
                last_beat = time.monotonic()
                try:
                    rows = self.client.update(
                        "ejecuciones", {"id": f"eq.{self.id}"}, {"heartbeat_at": _now()}
                    )
                    if rows and rows[0].get("estado") == "cancelada" and not self._cancelled:
                        self._cancelled = True
                        _thread.interrupt_main()
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------ consultas
    def _broker(self, prompt: str, kind: str, options) -> str:
        kind = kind if kind in ("otp", "mfa", "perfil", "cuenta", "texto") else "texto"
        message = prompt.strip() or kind
        print(f"[Consulta] {message} (esperando respuesta en la interfaz web)")
        row = self.client.insert_one(
            "ejecucion_prompts",
            {
                "ejecucion_id": self.id,
                "tipo": kind,
                "mensaje": message,
                "opciones": options,
            },
        )
        self.client.update("ejecuciones", {"id": f"eq.{self.id}"}, {"estado": "esperando_input"})
        timeout = float(os.environ.get("PROVIDERS_PROMPT_TIMEOUT", "600"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(2)
            current = self.client.select_one(
                "ejecucion_prompts",
                {"id": f"eq.{row['id']}", "select": "estado,respuesta"},
            )
            if current and current["estado"] == "respondido":
                answer = current.get("respuesta") or ""
                # No dejar OTP/MFA guardados una vez consumidos.
                self.client.update(
                    "ejecucion_prompts", {"id": f"eq.{row['id']}"}, {"respuesta": None}
                )
                self.client.update(
                    "ejecuciones", {"id": f"eq.{self.id}"}, {"estado": "en_curso"}
                )
                return answer
        self.client.update(
            "ejecucion_prompts", {"id": f"eq.{row['id']}"}, {"estado": "expirado"}
        )
        self.client.update("ejecuciones", {"id": f"eq.{self.id}"}, {"estado": "en_curso"})
        raise prompts.PromptTimeoutError(
            f"No hubo respuesta a la consulta en {int(timeout)} segundos."
        )
