import importlib.util
from pathlib import Path

from cryptography.fernet import Fernet

from core.crypto_keys import build_cipher

_spec = importlib.util.spec_from_file_location(
    "recifrar_credenciales_tool", Path(__file__).resolve().parents[1] / "tools" / "recifrar_credenciales.py"
)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class FakeClient:
    def __init__(self, filas):
        self.filas = filas
        self.updates = []

    def select(self, table, params=None):
        return self.filas

    def update(self, table, filters, patch):
        self.updates.append((filters, patch))
        return [{}]


def test_recifra_con_la_clave_primera_y_marca_los_que_no_descifran():
    vieja, nueva, ajena = (Fernet.generate_key() for _ in range(3))
    filas = [
        {"id": 1, "credenciales_enc": Fernet(vieja).encrypt(b'{"a":"1"}').decode()},
        {"id": 2, "credenciales_enc": None},
        {"id": 3, "credenciales_enc": Fernet(ajena).encrypt(b"x").decode()},
        {"id": 4, "credenciales_enc": Fernet(nueva).encrypt(b'{"b":"2"}').decode()},
    ]
    cliente = FakeClient(filas)
    cifrador = build_cipher(f"{nueva.decode()},{vieja.decode()}")
    hechos, fallidos = tool.recifrar(cliente, cifrador)
    assert hechos == [1, 4] and fallidos == [3]
    assert [f["id"] for f, _ in cliente.updates] == ["eq.1", "eq.4"]
    token_1 = cliente.updates[0][1]["credenciales_enc"]
    assert Fernet(nueva).decrypt(token_1.encode()) == b'{"a":"1"}'  # ya no depende de la vieja


def test_dry_run_no_escribe():
    clave = Fernet.generate_key()
    cliente = FakeClient([{"id": 1, "credenciales_enc": Fernet(clave).encrypt(b"x").decode()}])
    hechos, _ = tool.recifrar(cliente, build_cipher(clave.decode()), dry_run=True)
    assert hechos == [1] and cliente.updates == []
