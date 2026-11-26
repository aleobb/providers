import os
import time

import pytest

import vm_exec

KEY = "clave-de-prueba-0123456789"


class FakeClient:
    def __init__(self, row):
        self.row = row

    def select_one(self, table, params):
        return self.row if self.row["estado"] == "aprobado" else None

    def update(self, table, filters, patch):
        self.row = {**self.row, **patch}
        return [self.row]


def _row(comando, timeout_s=30, id=9):
    expira = int(time.time()) + 600
    return {
        "id": id, "comando": comando, "timeout_s": timeout_s, "estado": "aprobado",
        "expira_epoch": expira, "firma": vm_exec.firma(KEY, id, timeout_s, expira, comando),
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("VM_APPROVAL_KEY", KEY)


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_salida_enorme_se_recorta_sin_guardarla_entera():
    cliente = FakeClient(_row("python3 -c \"print('x' * 20_000_000); print('FIN')\""))
    assert vm_exec.run_pending(cliente, "vm") is True
    salida = cliente.row["salida"]
    assert cliente.row["estado"] == "ok" and cliente.row["codigo_salida"] == 0
    assert salida.startswith(vm_exec.MARCA_RECORTE)
    assert salida.count(vm_exec.MARCA_RECORTE) == 1
    assert salida.rstrip().endswith("FIN")
    assert len(salida) <= vm_exec.MAX_SALIDA + 200


@pytest.mark.skipif(os.name == "nt", reason="bash")
def test_salida_corta_queda_intacta_y_tiempo_agotado_conserva_la_cola():
    cliente = FakeClient(_row("echo uno; echo dos"))
    vm_exec.run_pending(cliente, "vm")
    assert cliente.row["salida"].split() == ["uno", "dos"]
    cliente = FakeClient(_row("echo antes; sleep 30", timeout_s=5))
    vm_exec.run_pending(cliente, "vm")
    assert "antes" in cliente.row["salida"] and "Tiempo agotado" in cliente.row["salida"]
