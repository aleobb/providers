import pytest

from core import cli


def _parse(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["main.py", *argv])
    return cli.parse_args()


def test_los_valores_por_defecto_no_cambian(monkeypatch):
    assert _parse(monkeypatch) == {
        "debug": False, "listar": False, "todas": False, "nosession": False, "cuenta": None,
        "proveedor": None, "todos_proveedores": False, "url": None, "gestionar_credenciales": False,
        "datos_pdf_csv": None, "ingresar": False, "airtable": False, "airtable_documento": None, "banco": None,
    }


def test_todos_los_flags_conocidos(monkeypatch):
    args = _parse(
        monkeypatch, "--debug", "--listar", "--todas", "--nosession", "-p", "EDENOR", "--cuenta", "123",
        "--todos-proveedores", "--ingresar", "--airtable", "--airtable-documento", "f.pdf", "--banco", "Nación",
        "--gestionar-credenciales", "--datos-pdf-csv", "d.csv", "--url", "https://x",
    )
    assert args["proveedor"] == "edenor"  # -p y minúsculas
    assert args["cuenta"] == "123" and args["banco"] == "Nación" and args["url"] == "https://x"
    assert all(args[k] is True for k in ("debug", "listar", "todas", "nosession", "todos_proveedores", "ingresar", "airtable", "gestionar_credenciales"))
    assert args["airtable_documento"] == "f.pdf" and args["datos_pdf_csv"] == "d.csv"


@pytest.mark.parametrize("argv", [["--todo"], ["--proveedor"], ["--cuenta"], ["--prov", "edenor"], ["suelto"]])
def test_flag_desconocido_abreviado_o_sin_valor_termina_con_error(monkeypatch, capsys, argv):
    with pytest.raises(SystemExit) as exit_info:
        _parse(monkeypatch, *argv)
    assert exit_info.value.code == 2
    assert "main.py" in capsys.readouterr().err


def test_help_funciona(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _parse(monkeypatch, "--help")
    assert exit_info.value.code == 0
    assert "--todos-proveedores" in capsys.readouterr().out
