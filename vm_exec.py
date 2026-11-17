"""Comandos de la VM aprobados por una persona (tabla `vm_comandos` de Supabase).

Flujo: Claude solicita (estado `solicitado`), Ale aprueba en /proveedores y el Worker firma el pedido con
HMAC-SHA256 usando VM_APPROVAL_KEY (estado `aprobado`). El agente solo ejecuta pedidos con firma válida,
sin vencer, y una única vez (los reclama de forma atómica). Quien solicita no conoce la clave, así que no
puede aprobarse a sí mismo. Sin VM_APPROVAL_KEY en el entorno la función queda desactivada.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import signal
import subprocess
import time
from datetime import datetime, timezone

from integrations.supabase_sync.client import SupabaseClient

TABLE = "vm_comandos"
MAX_SALIDA = 100_000
# El comando aprobado no hereda secretos del agente (sí puede leer archivos del usuario: se revisa al aprobar).
SECRETOS = ("VM_APPROVAL_KEY", "SUPABASE_SERVICE_KEY", "CREDENTIALS_KEY", "PROVIDERS_CREDENTIALS_KEY", "GITHUB_TOKEN")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def firma(key: str, row_id: int, timeout_s: int, expira_epoch: int, comando: str) -> str:
    """Mismo formato que el Worker (apps/finanzas/src/lib/vmFirma.ts)."""
    mensaje = f"{row_id}|{timeout_s}|{expira_epoch}|{comando}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), mensaje, hashlib.sha256).hexdigest()


def firma_valida(key: str, row: dict) -> bool:
    try:
        esperada = firma(key, int(row["id"]), int(row["timeout_s"]), int(row["expira_epoch"]), row["comando"])
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(esperada, str(row.get("firma") or ""))


def _redactar(texto: str) -> str:
    for nombre in SECRETOS:
        valor = os.environ.get(nombre, "").strip()
        if len(valor) >= 8:
            texto = texto.replace(valor, "***")
    return texto


def _recortar(texto: str) -> str:
    if len(texto) <= MAX_SALIDA:
        return texto
    return f"[... salida recortada, se muestran los últimos {MAX_SALIDA} caracteres ...]\n" + texto[-MAX_SALIDA:]


def _terminar(client: SupabaseClient, row_id: int, estado: str, salida: str, codigo: int | None) -> None:
    client.update(
        TABLE,
        {"id": f"eq.{row_id}"},
        {"estado": estado, "fin_at": _now(), "codigo_salida": codigo, "salida": _recortar(_redactar(salida))},
    )


def recover_interrupted(client: SupabaseClient, name: str) -> None:
    """Un comando que reinicia el agente lo mata a mitad de camino: queda `ejecutando`."""
    client.update(
        TABLE,
        {"agente": f"eq.{name}", "estado": "eq.ejecutando"},
        {"estado": "error", "fin_at": _now(), "salida": "Interrumpido: el agente se reinició durante la ejecución."},
    )


def _ejecutar(comando: str, timeout_s: int) -> tuple[str, int | None, bool]:
    env = {k: v for k, v in os.environ.items() if k not in SECRETOS}
    proceso = subprocess.Popen(
        ["bash", "-lc", comando],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        salida, _ = proceso.communicate(timeout=timeout_s)
        return salida or "", proceso.returncode, False
    except subprocess.TimeoutExpired:
        os.killpg(proceso.pid, signal.SIGKILL)
        salida, _ = proceso.communicate()
        return (salida or "") + f"\n[Tiempo agotado: {timeout_s}s]", None, True


def run_pending(client: SupabaseClient, name: str) -> bool:
    """Ejecuta el próximo comando aprobado. Devuelve True si ejecutó (o descartó) uno."""
    key = os.environ.get("VM_APPROVAL_KEY", "").strip()
    if not key:
        return False
    row = client.select_one(TABLE, {"estado": "eq.aprobado", "order": "id.asc", "limit": "1"})
    if row is None:
        return False
    row_id = int(row["id"])
    if not firma_valida(key, row):
        _terminar(client, row_id, "error", "Rechazado por el agente: la firma de aprobación no es válida.", None)
        return True
    if int(row["expira_epoch"]) < int(time.time()):
        _terminar(client, row_id, "expirado", "La aprobación venció antes de ejecutarse.", None)
        return True
    reclamado = client.update(
        TABLE, {"id": f"eq.{row_id}", "estado": "eq.aprobado"}, {"estado": "ejecutando", "agente": name, "inicio_at": _now()}
    )
    if not reclamado:
        return False  # otro agente lo reclamó primero
    print(f"[Agente] Ejecutando comando aprobado #{row_id} ({row['timeout_s']}s máx.)")
    salida, codigo, agotado = _ejecutar(row["comando"], int(row["timeout_s"]))
    _terminar(client, row_id, "ok" if codigo == 0 and not agotado else "error", salida, codigo)
    return True
