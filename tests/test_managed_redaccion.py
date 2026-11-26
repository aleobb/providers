import shutil

import pytest
from cryptography.fernet import Fernet

from core import managed
from core.credential_store import CredentialStore
from integrations.supabase_sync.client import SupabaseError


@pytest.fixture
def run():
    r = managed.ManagedRun(client=None, execution_id=1)
    yield r
    shutil.rmtree(r._tmp, ignore_errors=True)


def _lineas(run):
    out = []
    while not run._queue.empty():
        out.append(run._queue.get_nowait()["linea"])
    return out


def test_el_registro_tapa_secretos_aunque_lleguen_partidos(run):
    run._redactor.add("secreto-1234")
    run._on_text("info", "clave secreto")
    run._on_text("info", "-1234 y listo\nsegunda línea\n")
    assert _lineas(run) == ["clave *** y listo", "segunda línea"]


def test_el_registro_tapa_variables_de_entorno_secretas(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_abcdefgh1234")
    r = managed.ManagedRun(client=None, execution_id=2)
    try:
        r._on_text("error", "falló con sb_secret_abcdefgh1234\n")
        assert _lineas(r) == ["falló con ***"]
    finally:
        shutil.rmtree(r._tmp, ignore_errors=True)


def test_register_secrets_solo_toma_campos_secretos(run, tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDERS_CREDENTIALS_KEY", Fernet.generate_key().decode())
    store = CredentialStore(tmp_path / "c.sqlite3")
    store.import_legacy_dotenv_once(tmp_path / "sin-env")
    fields = store.get_credential_fields("edenor")
    secretos = {f.name for f in fields if f.secret}
    assert secretos, "edenor debería tener al menos un campo secreto"
    creds = {f.name: f"valor-{f.name}-zzz" for f in fields}
    run._register_secrets(store, "edenor", creds)
    run._on_text("info", " ".join(creds.values()) + "\n")
    (linea,) = _lineas(run)
    for f in fields:
        assert (f"valor-{f.name}-zzz" in linea) == (f.name not in secretos)


class _Client:
    def __init__(self, respuestas, falla_limpieza=False):
        self.respuestas = list(respuestas)
        self.falla_limpieza = falla_limpieza

    def insert_one(self, table, row):
        return {"id": 9}

    def update(self, table, filters, patch):
        if self.falla_limpieza and "respuesta" in patch:
            raise SupabaseError("sin red")
        return []

    def select_one(self, table, params):
        item = self.respuestas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_broker_sigue_esperando_si_supabase_falla_un_momento(monkeypatch, capsys):
    monkeypatch.setattr(managed.time, "sleep", lambda s: None)
    r = managed.ManagedRun(
        _Client([SupabaseError("503"), SupabaseError("503"), {"estado": "respondido", "respuesta": "123456"}]), 3
    )
    try:
        assert r._broker("Código", "otp", None) == "123456"
        assert capsys.readouterr().err.count("se reintenta") == 1  # avisa una sola vez
        r._on_text("info", "ingresé 123456 ok\n")
        assert _lineas(r)[-1] == "ingresé *** ok"  # la respuesta OTP no queda en el log
    finally:
        shutil.rmtree(r._tmp, ignore_errors=True)


def test_broker_devuelve_la_respuesta_aunque_falle_la_limpieza(monkeypatch):
    monkeypatch.setattr(managed.time, "sleep", lambda s: None)
    r = managed.ManagedRun(_Client([{"estado": "respondido", "respuesta": "654321"}], falla_limpieza=True), 4)
    try:
        assert r._broker("Código", "mfa", None) == "654321"
    finally:
        shutil.rmtree(r._tmp, ignore_errors=True)
