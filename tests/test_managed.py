import asyncio

import pytest

from core import hooks, managed, prompts
from core.credential_store import CredentialStore
import agent


def test_extract_flags_separa_y_conserva_el_resto():
    rest, opts = managed.extract_flags(
        ["--proveedor", "visa", "--todas", "--supabase", "--ejecucion-id", "12", "--perfil", "ale"]
    )
    assert rest == ["--proveedor", "visa", "--todas"]
    assert opts == {"supabase": True, "ejecucion_id": 12, "perfil": "ale"}


def test_sin_flags_no_hay_cambios():
    rest, opts = managed.extract_flags(["--proveedor", "visa", "--debug"])
    assert rest == ["--proveedor", "visa", "--debug"]
    assert not any(opts.values())


def test_ask_sin_broker_usa_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda p: "42")
    assert prompts.ask("n: ", kind="otp") == "42"


def test_ask_con_broker(monkeypatch):
    prompts.set_broker(lambda p, k, o: f"{k}:{o}")
    try:
        assert prompts.ask("n: ", kind="perfil", options=["1. a"]) == "perfil:['1. a']"
    finally:
        prompts.set_broker(None)


def test_choose_profile_con_alias_preferido(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("PROVIDERS_CREDENTIALS_KEY", Fernet.generate_key().decode())
    store = CredentialStore(tmp_path / "c.sqlite3")
    store.import_legacy_dotenv_once(tmp_path / "sin-env")
    fields = {f.name: "x" for f in store.get_credential_fields("edenor")}
    store.add_profile("edenor", "uno", fields)
    store.add_profile("edenor", "dos", fields)
    monkeypatch.setenv("PROVIDERS_PROFILE_ALIAS", "DOS")
    assert store.choose_profile("edenor").alias == "dos"


def test_hook_con_error_no_corta(capsys):
    hooks.clear()

    def malo(**_):
        raise RuntimeError("falló")

    class P:
        name = "visa"

    hooks.register_post_download(malo, name="Prueba")
    asyncio.run(hooks.run_post_download(provider=P(), account=None))
    assert hooks.stats["errors"] == 1
    assert "falló" in capsys.readouterr().err
    hooks.clear()


def test_build_argv():
    row = {"id": 3, "accion": "descargar", "args": {"perfil": "ale"}, "proveedor_portales": {"codigo": "edenor"}}
    argv = agent.build_argv(row)[2:]
    assert argv == ["--ejecucion-id", "3", "--proveedor", "edenor", "--supabase", "--todas", "--perfil", "ale"]
    debug = agent.build_argv({"id": 4, "accion": "debug", "args": {}, "proveedor_portales": None})[2:]
    assert "--todos-proveedores" in debug and "--debug" in debug
    with pytest.raises(ValueError):
        agent.build_argv({"id": 5, "accion": "ingresar", "args": {}, "proveedor_portales": None})
