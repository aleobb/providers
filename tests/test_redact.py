from core.redact import MASK, Redactor


def test_tapa_valores_exactos_y_su_version_url():
    r = Redactor()
    r.add("clave Secreta/1")
    texto = "login con clave Secreta/1 y clave%20Secreta%2F1 listo"
    salida = r.redact(texto)
    assert "Secreta" not in salida
    assert salida.count(MASK) == 2


def test_ignora_valores_cortos_o_no_texto():
    r = Redactor()
    r.add("123")
    r.add(None)
    r.add(12345678)
    assert r.redact("pin 123 ok") == "pin 123 ok"


def test_valor_largo_se_tapa_antes_que_el_corto_que_contiene():
    r = Redactor()
    r.add("abcd")
    r.add("abcdef-largo")
    assert r.redact("x abcdef-largo y") == f"x {MASK} y"


def test_env_solo_toma_nombres_de_secreto():
    r = Redactor()
    r.add_env({"SUPABASE_SERVICE_KEY": "sb_secret_12345678", "HOME": "/home/usuario-largo"})
    salida = r.redact("clave sb_secret_12345678 en /home/usuario-largo")
    assert "sb_secret" not in salida and "/home/usuario-largo" in salida


def test_formatos_de_token_comunes():
    r = Redactor()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk123456"
    lineas = [
        f"Authorization: Bearer {jwt}",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "token gAAAAA" + "B" * 60,
        "gh " + "ghp_" + "a" * 30,
    ]
    for linea in lineas:
        salida = r.redact(linea)
        assert MASK in salida
        assert "dXNlcjpwYXNz" not in salida and "ghp_a" not in salida and "BBBBBB" not in salida


def test_texto_normal_no_cambia():
    assert Redactor().redact("[1/3] N 123 - Casa: descargando...") == "[1/3] N 123 - Casa: descargando..."
