import httpx
import pytest

from integrations.supabase_sync import client as client_module
from integrations.supabase_sync.client import SupabaseClient, SupabaseError


@pytest.fixture(autouse=True)
def _sin_espera(monkeypatch):
    monkeypatch.setattr(client_module, "_sleep", lambda s: None)


def _client(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://x.supabase.co", "sb_secret_clave-de-prueba", http=http, **kwargs)


def test_lectura_se_reintenta_ante_5xx_y_termina_bien():
    llamadas = []

    def handler(request):
        llamadas.append(request.method)
        return httpx.Response(503, text="caído") if len(llamadas) < 3 else httpx.Response(200, json=[{"id": 1}])

    assert _client(handler).select("t") == [{"id": 1}]
    assert len(llamadas) == 3


def test_lectura_agota_reintentos_y_falla():
    llamadas = []

    def handler(request):
        llamadas.append(1)
        return httpx.Response(500, text="error")

    with pytest.raises(SupabaseError, match="500"):
        _client(handler).select("t")
    assert len(llamadas) == 3  # 1 + 2 reintentos


def test_escritura_no_se_reintenta_ante_5xx():
    llamadas = []

    def handler(request):
        llamadas.append(request.method)
        return httpx.Response(502, text="mal")

    with pytest.raises(SupabaseError):
        _client(handler).update("t", {"id": "eq.1"}, {"a": 1})
    with pytest.raises(SupabaseError):
        _client(handler).insert("t", {"a": 1})
    assert llamadas == ["PATCH", "POST"]


def test_escritura_si_se_reintenta_si_no_pudo_conectar_o_hubo_429():
    estados = iter(["conexion", 429, "ok"])

    def handler(request):
        estado = next(estados)
        if estado == "conexion":
            raise httpx.ConnectError("sin red", request=request)
        if estado == 429:
            return httpx.Response(429, text="lento")
        return httpx.Response(200, json=[{"id": 1}])

    assert _client(handler).update("t", {"id": "eq.1"}, {"a": 1}) == [{"id": 1}]


def test_timeout_de_lectura_en_escritura_no_se_reintenta():
    llamadas = []

    def handler(request):
        llamadas.append(1)
        raise httpx.ReadTimeout("lento", request=request)

    with pytest.raises(SupabaseError, match="No se pudo conectar"):
        _client(handler).update("t", {"id": "eq.1"}, {"a": 1})
    assert len(llamadas) == 1


def test_subida_con_upsert_se_reintenta():
    llamadas = []

    def handler(request):
        llamadas.append(1)
        return httpx.Response(500) if len(llamadas) == 1 else httpx.Response(200, json={})

    _client(handler).upload("b", "a/b.pdf", b"x", "application/pdf")
    assert len(llamadas) == 2


def test_4xx_no_se_reintenta():
    llamadas = []

    def handler(request):
        llamadas.append(1)
        return httpx.Response(404, text="no existe")

    with pytest.raises(SupabaseError, match="404"):
        _client(handler).select("t")
    assert len(llamadas) == 1
