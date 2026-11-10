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
                """() => !!document.querySelector('input#email, input#nrodoc') ||
                /Estado de cuenta:\\s*Nro de cliente/i.test(document.body.innerText)""",
                timeout=self.config.timeout_ms,
            )
            login_form_visible = (
                await self.page.locator('input#nrodoc').is_visible()
                or await self.page.locator('input#email').is_visible()
            )
            if self.config.manual_login and login_form_visible:
                await asyncio.to_thread(
                    ask,
                    'Inicia sesión manualmente en la ventana de Medifé. '
                    'Cuando veas el portal autenticado, presiona Enter para continuar: ',
                    kind='texto',
                )
                await self.page.wait_for_function(
                    r"/Estado de cuenta:\s*Nro de cliente/i.test(document.body.innerText)",
                    timeout=self.config.timeout_ms,
                )
                await self.page.goto(self.config.invoices_url, timeout=self.config.timeout_ms)
            elif await self.page.locator('input#nrodoc').is_visible():
                await self._fill_document_credentials()
            elif await self.page.locator('input#email').is_visible():
                await self.page.get_by_role('button', name='Ingresar con mi número de documento', exact=True).click()
                await self._fill_document_credentials()
            if await self.page.locator('input#nrodoc').is_visible():
                await self.page.locator('input#password').fill(self.config.password)
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

    async def _fill_document_credentials(self) -> None:
        if not self.config.documento_nacional_de_identidad or not self.config.password:
            raise LoginError(
                'Completa numero de documento y contraseña en el perfil de Medife '
                'con --gestionar-credenciales.'
            )
        await self.page.locator('select#tipodoc').select_option(self.config.tipo_documento)
        await self.page.locator('input#nrodoc').fill(self.config.documento_nacional_de_identidad)
