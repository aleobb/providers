import pytest
from cryptography.fernet import Fernet, InvalidToken

from core.crypto_keys import build_cipher


def test_una_clave_cifra_y_descifra():
    key = Fernet.generate_key().decode()
    cipher = build_cipher(key)
    assert cipher.decrypt(cipher.encrypt(b"hola")) == b"hola"


def test_rotacion_la_primera_cifra_y_todas_descifran():
    vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token_viejo = Fernet(vieja.encode()).encrypt(b"dato")
    cipher = build_cipher(f"{nueva}, {vieja}")
    assert cipher.decrypt(token_viejo) == b"dato"
    token_nuevo = cipher.encrypt(b"otro")
    assert Fernet(nueva.encode()).decrypt(token_nuevo) == b"otro"
    with pytest.raises(InvalidToken):
        Fernet(vieja.encode()).decrypt(token_nuevo)


def test_clave_invalida_o_vacia():
    with pytest.raises(ValueError):
        build_cipher("no-es-una-clave")
    with pytest.raises(ValueError):
        build_cipher(" , ")
