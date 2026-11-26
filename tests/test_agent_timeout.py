import os
import sys
import time
from pathlib import Path

import pytest

import agent

posix = pytest.mark.skipif(os.name == "nt", reason="usa grupos de procesos POSIX")


class FakeClient:
    def __init__(self, estado="en_curso"):
        self.estado = estado
        self.updates = []

    def select_one(self, table, params):
        return {"estado": self.estado}

    def update(self, table, filters, patch):
        self.updates.append((filters, patch))
        return [{"id": 1}]


def test_run_timeout_minutes(monkeypatch):
    monkeypatch.delenv("AGENT_RUN_TIMEOUT_MIN", raising=False)
    assert agent.run_timeout_minutes("descargar") == agent.RUN_TIMEOUT_MIN
    assert agent.run_timeout_minutes("descargar", default=25) == 25
    assert agent.run_timeout_minutes("debug") is None  # interactivas: sin límite
    assert agent.run_timeout_minutes("ingresar") is None
    monkeypatch.setenv("AGENT_RUN_TIMEOUT_MIN", "10")
    assert agent.run_timeout_minutes("descargar") == 10
    monkeypatch.setenv("AGENT_RUN_TIMEOUT_MIN", "0")
    assert agent.run_timeout_minutes("descargar") is None
    monkeypatch.setenv("AGENT_RUN_TIMEOUT_MIN", "abc")
    assert agent.run_timeout_minutes("descargar") == agent.RUN_TIMEOUT_MIN


def test_run_process_termina_normal():
    code, timed_out = agent.run_process([sys.executable, "-c", "raise SystemExit(3)"], Path("."), 30)
    assert (code, timed_out) == (3, False)


@posix
def test_run_process_corta_el_proceso_vencido():
    inicio = time.time()
    code, timed_out = agent.run_process([sys.executable, "-c", "import time; time.sleep(60)"], Path("."), 1)
    assert timed_out is True
    assert time.time() - inicio < 15


@posix
def test_run_process_corta_tambien_a_los_hijos(tmp_path):
    pidfile = tmp_path / "hijo.pid"
    script = f"sleep 120 & echo $! > {pidfile}; wait"
    _, timed_out = agent.run_process(["sh", "-c", script], Path("."), 1)
    assert timed_out is True
    pid = int(pidfile.read_text().strip())
    stat = Path(f"/proc/{pid}/stat")

    def muerto():
        # no existe, o quedó zombi esperando que el init lo recoja
        return not stat.exists() or stat.read_text().split(")")[-1].split()[0] == "Z"

    limite = time.time() + 5
    while not muerto() and time.time() < limite:
        time.sleep(0.1)
    assert muerto()


def test_run_execution_marca_error_por_tiempo(monkeypatch):
    monkeypatch.setattr(agent, "run_process", lambda argv, cwd, timeout: (-9, True))
    client = FakeClient("en_curso")
    row = {"id": 5, "accion": "descargar", "args": {}, "proveedor_portales": {"codigo": "edenor"}}
    assert agent.run_execution(client, row, timeout_min=7) == -9
    filters, patch = client.updates[-1]
    assert filters == {"id": "eq.5"}
    assert patch["estado"] == "error" and "7 min" in patch["resumen"]


def test_run_execution_no_pisa_un_estado_ya_cerrado(monkeypatch):
    monkeypatch.setattr(agent, "run_process", lambda argv, cwd, timeout: (0, False))
    client = FakeClient("ok")
    row = {"id": 5, "accion": "descargar", "args": {}, "proveedor_portales": None}
    assert agent.run_execution(client, row) == 0
    assert client.updates == []


def test_run_execution_pasa_limite_segun_accion(monkeypatch):
    vistos = []
    monkeypatch.setattr(agent, "run_process", lambda argv, cwd, timeout: vistos.append(timeout) or (0, False))
    monkeypatch.delenv("AGENT_RUN_TIMEOUT_MIN", raising=False)
    client = FakeClient("ok")
    agent.run_execution(client, {"id": 1, "accion": "descargar", "args": {}, "proveedor_portales": None})
    agent.run_execution(client, {"id": 2, "accion": "debug", "args": {}, "proveedor_portales": None})
    agent.run_execution(client, {"id": 3, "accion": "ingresar", "args": {}, "proveedor_portales": {"codigo": "x"}})
    assert vistos == [agent.RUN_TIMEOUT_MIN * 60, None, None]


def test_main_rechaza_id_de_ejecucion_invalido(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_de-prueba")
    for argv in (["agent.py", "--ejecucion", "1; echo hola"], ["agent.py", "--ejecucion"]):
        monkeypatch.setattr(sys, "argv", argv)
        assert agent.main() == 2
    assert "requiere el número" in capsys.readouterr().err
