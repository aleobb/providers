import httpx
import pytest

from core.exceptions import DownloadError
from providers.metrogas.invoice import (
    _is_pdf_response,
    _validated_pdf_content,
)


def test_pdf_response_accepts_pdf_signature_even_with_octet_stream_content_type():
    response = httpx.Response(
        200,
        headers={"content-type": "application/octet-stream"},
        content=b"%PDF-1.7\ninvoice",
    )

    assert _is_pdf_response(response)
    assert _validated_pdf_content(response, "12345678") == response.content


def test_pdf_response_rejects_successful_html_login_redirect():
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<html><body>Login</body></html>",
    )

    assert not _is_pdf_response(response)
    with pytest.raises(DownloadError, match="sesión puede haber expirado"):
        _validated_pdf_content(response, "12345678")


def test_pdf_response_rejects_http_errors():
    response = httpx.Response(403, content=b"Forbidden")

    with pytest.raises(DownloadError, match="HTTP 403"):
        _validated_pdf_content(response, "12345678")
