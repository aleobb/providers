import asyncio

from providers.aysa import invoice


class _FakeCookies(dict):
    def update(self, cookies):
        super().update(cookies)


class _FakeClient:
    def __init__(self, **options):
        self.options = options
        self.cookies = _FakeCookies(options["cookies"])
        self.closed = False

    async def aclose(self):
        self.closed = True


def test_aysa_invoice_service_reuses_client_and_refreshes_cookies(monkeypatch):
    clients = []

    def make_client(**options):
        client = _FakeClient(**options)
        clients.append(client)
        return client

    monkeypatch.setattr(invoice.httpx, "AsyncClient", make_client)
    service = invoice.InvoiceService(page=None, config=None)

    first = service._get_client({"session": "first"})
    second = service._get_client({"session": "second"})

    assert first is second
    assert len(clients) == 1
    assert clients[0].cookies == {"session": "second"}

    asyncio.run(service.aclose())

    assert clients[0].closed is True
    assert service._client is None
