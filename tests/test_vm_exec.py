import time
from types import SimpleNamespace

import pytest

import vm_exec

KEY = "clave-de-prueba-0123456789"


class FakeClient:
    def __init__(self, row=None):
        self.row = row
        self.updates = []

    def select_one(self, table, params):
        return self.row if self.row and self.row["estado"] == "aprobado" else None

    def update(self, table, filters, patch):
        self.updates.append((filters, patch))
        if filters.get("estado") == "eq.aprobado" and self.row and self.row["estado"] != "aprobado":
            return []
        if self.row:
            self.row = {**self.row, **patch}
        return [self.row] if self.row else []


def _row(comando="echo hola", timeout_s=10, expira=None, key=KEY, id=7):
    expira = int(time.time()) + 600 if expira is None else expira
    return {
        "id": id,
        "comando": comando,
        "timeout_s": timeout_s,
        "estado": "aprobado",
        "expira_epoch": expira,
        "firma": vm_exec.firma(key, id, timeout_s, expira, comando),
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("VM_APPROVAL_KEY", KEY)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_supersecreto123")



def test_ejecuta_una_vez_con_firma_valida():
    cliente = FakeClient(_row("echo hola; exit 0"))
    assert vm_exec.run_pending(cliente, "vm") is True
    assert cliente.row["estado"] == "ok" and cliente.row["codigo_salida"] == 0
    assert "hola" in cliente.row["salida"]
    assert vm_exec.run_pending(cliente, "vm") is False  # ya no está aprobado: no se repite


def test_codigo_distinto_de_cero_es_error():
    cliente = FakeClient(_row("echo mal >&2; exit 3"))
    vm_exec.run_pending(cliente, "vm")
    assert cliente.row["estado"] == "error" and cliente.row["codigo_salida"] == 3 and "mal" in cliente.row["salida"]


def test_comando_modificado_despues_de_aprobar_no_corre(tmp_path):
    marca = tmp_path / "corrio"
    fila = _row("echo ok")
    fila["comando"] = f"touch {marca}"
    cliente = FakeClient(fila)
    vm_exec.run_pending(cliente, "vm")
    assert cliente.row["estado"] == "error" and "firma" in cliente.row["salida"]
    assert not marca.exists()


def test_firma_con_otra_clave_se_rechaza():
    cliente = FakeClient(_row(key="otra-clave-distinta"))
    vm_exec.run_pending(cliente, "vm")
    assert cliente.row["estado"] == "error"


def test_aprobacion_vencida_no_corre():
    cliente = FakeClient(_row(expira=int(time.time()) - 5))
    vm_exec.run_pending(cliente, "vm")
    assert cliente.row["estado"] == "expirado"


def test_sin_clave_queda_desactivado(monkeypatch):
    monkeypatch.delenv("VM_APPROVAL_KEY")
    cliente = FakeClient(_row())
    assert vm_exec.run_pending(cliente, "vm") is False
    assert cliente.updates == []


def test_timeout_mata_el_proceso():
    cliente = FakeClient(_row("sleep 30", timeout_s=5))
    inicio = time.time()
    vm_exec.run_pending(cliente, "vm")
    assert time.time() - inicio < 15
    assert cliente.row["estado"] == "error" and "Tiempo agotado" in cliente.row["salida"]


def test_secretos_no_se_heredan_ni_salen_en_la_salida():
    cliente = FakeClient(_row('echo "[${SUPABASE_SERVICE_KEY}]"; echo sb_secret_supersecreto123'))
    vm_exec.run_pending(cliente, "vm")
    assert "supersecreto" not in cliente.row["salida"]
    assert "[]" in cliente.row["salida"]


def test_firma_vector_fijo_compartido_con_el_worker():
    # Mismo vector que apps/finanzas/src/lib/vmFirma.ts (aleobb/finanzas): si cambia el formato, falla en ambos.
    assert vm_exec.firma("k", 1, 300, 1700000000, "echo hola ñ|x") == (
        "d9b42d7ac78abfe16ec0c4b6873ae020f9da2e76906fd5314954b4f4b125531d"
    )
