import asyncio
from types import SimpleNamespace

from core.accounts import Account
from providers.telecentro import invoice


class _Response:
    def __init__(self, *, data=None, content=b"", headers=None):
        self.status_code = 200
        self._data = data
        self.content = content
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, **options):
        self.options = options
        self.requests = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return _Response(data={"token": "account-token"})

    async def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        if "comprobantes" in url:
            return _Response(
                data={
                    "comprobantes": [
                        {"key": "latest", "fechaEmision": "01/05/2026"}
                    ]
                }
            )
        return _Response(
            content=b"%PDF-1.4\n",
            headers={"content-type": "application/pdf"},
        )

    async def aclose(self):
        self.closed = True


def test_telecentro_reuses_one_async_client_for_multiple_accounts(monkeypatch, tmp_path):
    clients = []

    def make_client(**options):
        client = _FakeClient(**options)
        clients.append(client)
        return client

    monkeypatch.setattr(invoice.httpx, "AsyncClient", make_client)
    config = SimpleNamespace(
        api_base="https://api.example.test",
        invoices_url="https://api.example.test/invoices",
        ensure_output_dir=lambda: tmp_path,
    )
    service = invoice.InvoiceService(config, "base-token")

    async def download_two_accounts():
        paths = [
            await service.download_for_client(Account(number, number, ""))
            for number in ("101", "202")
        ]
        await service.aclose()
        return paths

    paths = asyncio.run(download_two_accounts())

    assert len(clients) == 1
    assert len(clients[0].requests) == 6
    assert all(path.is_file() for path in paths)
    assert clients[0].closed is True
