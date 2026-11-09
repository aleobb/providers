from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError
from .config import MedifeConfig


class LoginOrchestrator:
    def __init__(self, page: Page, config: MedifeConfig):
        self.page = page
        self.config = config

    async def execute(self) -> None:
        # Ir directamente a facturación también permite reutilizar una sesión activa.
        await self.page.goto(self.config.invoices_url, timeout=self.config.timeout_ms)
        try:
            await self.page.wait_for_function(
                """() => !!document.querySelector('#email, #nrodoc') ||
                /Estado de cuenta:\\s*Nro de cliente/i.test(document.body.innerText)""",
                timeout=self.config.timeout_ms,
            )
            if await self.page.locator('#nrodoc').is_visible():
                await self.page.get_by_text('Email', exact=True).locator('..').get_by_role('button').click()
            if await self.page.locator('#email').is_visible():
                await self.page.locator('#email').fill(self.config.email)
                await self.page.locator('#password').fill(self.config.password)
                await self.page.get_by_role('button', name='Iniciar sesión', exact=True).click()
                # Una verificación humana, si aparece, se resuelve manualmente en --debug.
                await self.page.wait_for_url(
                    '**/portal/**', timeout=self.config.timeout_ms,
                    wait_until='domcontentloaded',
                )
                await self.page.goto(self.config.invoices_url, timeout=self.config.timeout_ms)
            await self.page.get_by_text('Estado de cuenta:', exact=False).wait_for(
                state='visible', timeout=self.config.timeout_ms
            )
        except PlaywrightTimeout as error:
            raise LoginError(
                'Medife no completo el acceso a facturacion. Verifica las credenciales; '
                'si solicita una verificacion humana, ejecuta con --debug y completala manualmente.'
            ) from error
