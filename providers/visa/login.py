from __future__ import annotations

import asyncio
import json

from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError, ServerUnavailableError
from .config import VisaConfig

_LOGIN_PAGE = "https://mis-tarjetas.prismamediosdepago.com/"

# Selectores del formulario de login.
# El portal Prisma migró a un frontend React/Next.js y los campos ya no vienen
# exclusivamente con los IDs legacy. Soportamos ambos formatos.
_SEL_DOC_TYPE = 'select#documentType'
_SEL_NUMERO   = '#documentNumber'
_SEL_USUARIO  = '#username'
_SEL_PASSWORD = '#password'

_SELECTOR_GROUPS = {
    "documentType": [
        'select#documentType',
        'select[name="documentType"]',
        '[name="documentType"]',
    ],
    "documentNumber": [
        '#documentNumber',
        'input[name="documentNumber"]',
        'input[id*="documentNumber"]',
        '[name="documentNumber"]',
    ],
    "username": [
        '#username',
        'input[name="username"]',
        'input[id*="username"]',
        '[name="username"]',
    ],
    "password": [
        '#password',
        'input[name="password"]',
        'input[id*="password"]',
        '[name="password"]',
    ],
    "code": [
        'input[name="code"]',
        'input[name="otp"]',
        'input[type="tel"]',
        'input[type="number"]',
        'input[placeholder*="digo"]',
        'input[placeholder*="Codigo"]',
    ],
}

_CREDENTIAL_ERROR_TEXTS = [
    "datos incorrectos",
    "contrase\u00f1a incorrecta",
    "usuario incorrecto",
    "credenciales incorrectas",
]

_SERVER_DOWN_TEXTS = [
    "intente m\u00e1s tarde",
    "intent\u00e1 nuevamente",
    "intenta m\u00e1s tarde",
    "intenta nuevamente",
    "en este momento",
    "error inesperado",
    "ocurri\u00f3 un error",
    "no pudimos procesar",
    "servicio no disponible",
    "temporalmente",
]

# Textos que indican sesion activa preexistente
_SESSION_CONFLICT_TEXTS = [
    "sesi\u00f3n activa",   # "sesión activa"
    "sesion activa",
    "sesi\u00f3n abierta",  # "sesión abierta"
    "sesion abierta",
    "ya ten\u00e9s",        # "ya tenés"
    "ya tienes",
    "ya inici",             # "ya iniciaste", "ya iniciaste sesion"
    "cerrar sesi",          # "cerrar sesión anterior"
]


class LoginOrchestrator:
    """
    Login de Visa/Prisma.

    State machine post-credenciales:
      "otp"              → pedir codigo por consola y enviarlo
      "session_conflict" → detectar y cerrar sesion anterior, luego puede pedir OTP
      "dashboard"        → ya estamos en mistarjetas, listo
    """

    def __init__(self, page: Page, context: BrowserContext, config: VisaConfig):
        self.page = page
        self.context = context
        self.config = config

    async def execute(self) -> None:
        # 1. Intentar reusar sesion del run anterior
        if await self._try_restore_session():
            return

        # 2. Login con credenciales
        await self._fill_login_form()

        # 3. Detectar estado post-login y manejarlo
        state = await self._detect_post_login_state()
        print(f"  [Visa] Estado post-login: {state}")

        if state == "session_conflict":
            await self._handle_session_conflict()
            # Dar tiempo a que el DOM se actualice tras cerrar la sesion
            await asyncio.sleep(3)
            # Despues de resolver el conflicto deberia aparecer OTP
            state = await self._detect_post_login_state()
            print(f"  [Visa] Estado tras resolver conflicto: {state}")

        if state == "otp":
            await self._handle_otp()
        elif state == "dashboard":
            pass
        elif state == "session_conflict":
            raise LoginError(
                "No se pudo resolver el conflicto de sesion de Visa. "
                "Cerrala manualmente en el portal y reintenta."
            )
        # else "unknown" → dejamos que _wait_for_dashboard detecte

        await self._wait_for_dashboard()
        await self._save_session()

    # ------------------------------------------------------------------ session restore

    async def _try_restore_session(self) -> bool:
        """
        Intenta navegar al dashboard con las cookies guardadas.
        Solo funciona si la sesion server-side sigue viva (JSESSIONID valido).
        """
        sf = self.config.session_file
        if not sf.exists():
            return False
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            if not cookies:
                return False
            await self.context.add_cookies(cookies)

            await self.page.goto(self.config.portal_url, timeout=self.config.timeout_ms)
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=self.config.timeout_ms)
            except Exception:
                pass
            await asyncio.sleep(2)

            url = self.page.url
            print(f"  [Visa] Restore session: URL final = {url}")
            # Sesion valida: en mistarjetas/app (no en login ni en mycards)
            if ("mistarjetas" in url
                    and "/app/" in url
                    and "login" not in url.lower()
                    and "mycards" not in url):
                print("  Sesion de Visa restaurada desde disco.")
                return True
            print("  [Visa] Sesion expirada o invalida — login completo requerido.")

        except Exception as e:
            print(f"  [Visa] Restauracion de sesion fallo: {e}")

        await self.context.clear_cookies()
        return False

    # ------------------------------------------------------------------ login form

    async def _find_field(self, field_name: str, timeout_ms: int = 30000):
        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
        last_error = None
        while asyncio.get_running_loop().time() < deadline:
            for selector in _SELECTOR_GROUPS.get(field_name, []):
                try:
                    locator = self.page.locator(selector).first
                    count = await locator.count()
                    if count == 0:
                        continue
                    if await locator.is_visible(timeout=1500):
                        return locator
                except Exception as exc:
                    last_error = exc
                    pass
            await asyncio.sleep(0.5)
        if last_error is not None:
            print(f"  [Visa] campo '{field_name}' no listo todavía: {last_error}")
        return None

    async def _set_select_option(self, field_name: str, value: str) -> bool:
        locator = await self._find_field(field_name)
        if locator is None:
            return False
        try:
            await locator.select_option(value=value)
            return True
        except Exception:
            try:
                await locator.select_option(label=value)
                return True
            except Exception:
                pass
        return False

    async def _fill_login_form(self) -> None:
        try:
            await self.page.goto(_LOGIN_PAGE, timeout=self.config.timeout_ms)
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(1)

            doc_type = await self._find_field("documentType", timeout_ms=30000)
            if doc_type is None:
                raise LoginError(
                    "Visa: no se encontró el selector de tipo de documento dentro del timeout esperado. "
                    "La pantalla de login aún no está disponible o cambió."
                )
            if await doc_type.evaluate("el => el.tagName.toLowerCase() === 'select'"):
                if not await self._set_select_option("documentType", "DNI"):
                    try:
                        await doc_type.select_option(label="DNI")
                    except Exception:
                        pass
            await asyncio.sleep(0.3)

            numero = await self._find_field("documentNumber", timeout_ms=30000)
            if numero is None:
                raise LoginError("Visa: no se encontró el campo de documento dentro del timeout esperado.")
            await numero.fill(self.config.documento_nacional_de_identidad)
            await asyncio.sleep(0.3)

            usuario = await self._find_field("username", timeout_ms=30000)
            if usuario is None:
                raise LoginError("Visa: no se encontró el campo de usuario dentro del timeout esperado.")
            await usuario.fill(self.config.usuario)
            await asyncio.sleep(0.2)

            password = await self._find_field("password", timeout_ms=30000)
            if password is None:
                raise LoginError("Visa: no se encontró el campo de contraseña dentro del timeout esperado.")
            await password.fill(self.config.password)
            await asyncio.sleep(0.2)

            await self.page.click('button:has-text("Ingresar"), button[type="submit"], button:has-text("Iniciar sesión")')
            await asyncio.sleep(3)

            # Detectar errores de credenciales o servidor caido
            try:
                body = (await self.page.inner_text("body", timeout=3000)).lower()
                for txt in _CREDENTIAL_ERROR_TEXTS:
                    if txt in body:
                        raise LoginError(
                            "Visa: credenciales incorrectas. "
                            "Verifica el perfil guardado en el gestor de credenciales."
                        )
                for txt in _SERVER_DOWN_TEXTS:
                    if txt in body:
                        raise ServerUnavailableError(
                            f"Visa: servidor no disponible. Reintenta mas tarde."
                        )
            except (LoginError, ServerUnavailableError):
                raise
            except Exception:
                pass

        except PlaywrightTimeout as e:
            raise NavigationError(f"Timeout llenando formulario de Visa: {e}") from e

    # ------------------------------------------------------------------ state detection

    async def _detect_post_login_state(self) -> str:
        """
        Detecta el estado actual tras submit de credenciales u OTP:
          "dashboard"        → URL en mistarjetas
          "otp"              → pantalla de verificacion con input
          "session_conflict" → portal dice que ya hay sesion activa
          "unknown"          → ninguno de los anteriores
        """
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        for _ in range(20):  # hasta 10 s
            await asyncio.sleep(0.5)
            url = self.page.url

            if "mistarjetas" in url and "login" not in url.lower():
                return "dashboard"

            try:
                body = (await self.page.inner_text("body", timeout=2000)).lower()

                # Sesion activa preexistente
                for txt in _SESSION_CONFLICT_TEXTS:
                    if txt in body:
                        return "session_conflict"

                # Pantalla de OTP: input numerico o boton de verificar.
                # El portal actual usa campos con name="code"/"otp" en un frontend React.
                has_otp_input = await self.page.locator(
                    'input[name="code"], input[name="otp"], '
                    'input[type="tel"], input[type="number"], '
                    'input[placeholder*="digo"], input[placeholder*="Codigo"]'
                ).count() > 0
                has_verify_btn = await self.page.locator(
                    'button:has-text("Verificar"), button:has-text("Confirmar"), '
                    'button:has-text("Validar"), button:has-text("Continuar")'
                ).count() > 0
                if has_otp_input or has_verify_btn:
                    return "otp"

            except Exception:
                pass

        return "unknown"

    # ------------------------------------------------------------------ session conflict

    async def _handle_session_conflict(self) -> None:
        """
        El portal muestra 'Ya tenes una sesion activa' con un boton 'Cerrar'
        que termina la sesion previa. Despues hay que re-clickear 'Ingresar'.
        """
        print("  [Visa] Cerrando sesion previa activa...")

        # El boton que cierra la sesion activa en mycards es <BUTTON> 'Cerrar'
        # (distinto de los <A> 'cerrar' de los popups del dashboard)
        candidates = [
            'button:has-text("Cerrar")',       # boton principal confirmado
            'button:has-text("Finalizar")',
            'button:has-text("Cerrar sesi")',
            'button:has-text("Continuar")',
            'button:has-text("Aceptar")',
        ]
        clicked = False
        for selector in candidates:
            try:
                el = self.page.locator(selector).first
                if await el.count() > 0 and await el.is_visible(timeout=2000):
                    print(f"  [Visa] Click '{selector}' para cerrar sesion previa")
                    await el.click()
                    await asyncio.sleep(2)
                    try:
                        await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            # No encontramos boton — diagnostico ASCII-safe
            try:
                body = await self.page.inner_text("body", timeout=3000)
                safe = body[:600].encode("ascii", errors="replace").decode("ascii")
                print(f"  [Visa] No se encontro boton. Texto:\n{safe}")
            except Exception:
                pass
            return

        # Tras cerrar la notificacion, esperar a que el portal proceda solo al OTP.
        # NO re-clickear "Ingresar": el primer submit ya hizo el request; "Cerrar"
        # resuelve el conflicto server-side y el frontend deberia avanzar al OTP.
        print("  [Visa] Sesion previa cerrada — esperando OTP...")
        await asyncio.sleep(4)
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    # ------------------------------------------------------------------ OTP

    async def _handle_otp(self) -> None:
        print()
        print("  *** Visa requiere verificacion de identidad (OTP) ***")
        print("  Revisa tu email y pega el codigo de 6 digitos.")
        otp = input("  Codigo OTP: ").strip()
        if not otp:
            raise LoginError("No se ingreso el codigo OTP de Visa")

        try:
            codigo_input = self.page.locator(
                'input[name="code"], input[name="otp"], '
                'input[type="tel"], input[type="number"], input[type="text"], '
                'input[placeholder*="digo"], input[placeholder*="Codigo"]'
            ).first
            await codigo_input.wait_for(state="visible", timeout=10000)
            await codigo_input.fill(otp)
            await asyncio.sleep(0.5)

            submitted = False
            for btn_text in ["Verificar", "Confirmar", "Validar", "Continuar"]:
                try:
                    btn = self.page.locator(f'button:has-text("{btn_text}")').first
                    if await btn.count() > 0 and await btn.is_visible(timeout=2000):
                        await btn.click()
                        submitted = True
                        break
                except Exception:
                    pass
            if not submitted:
                await codigo_input.press("Enter")

        except PlaywrightTimeout as e:
            raise LoginError(f"Timeout ingresando OTP de Visa: {e}") from e

        # Esperar el dialog de confirmacion "Codigo validado con exito" y hacer click en Ingresar
        for _ in range(20):
            await asyncio.sleep(0.5)
            if "mistarjetas" in self.page.url:
                return
            try:
                btn = self.page.locator('button:has-text("Ingresar")').first
                if await btn.count() > 0 and await btn.is_visible(timeout=500):
                    print("  [Visa] OTP validado - haciendo click en Ingresar...")
                    await btn.click()
                    break
            except Exception:
                pass

        await asyncio.sleep(2)
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass

        if "mistarjetas" in self.page.url:
            return

        # Verificar rechazo explicito (con y sin tildes)
        try:
            body = (await self.page.inner_text("body", timeout=3000)).lower()
            _rejected = (
                "invalido" in body        # "inválido" lowercased pierde tilde en ascii
                or "inv\u00e1lido" in body  # con tilde
                or "incorrecto" in body
                or "no pudimos validar" in body
                or "expirado" in body
                or "expired" in body
            )
            if _rejected:
                # Cerrar el dialog de error para dejar la pagina limpia
                for sel in ['button:has-text("Cerrar")', 'button:has-text("OK")', 'button:has-text("Aceptar")']:
                    try:
                        btn = self.page.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible(timeout=1000):
                            await btn.click()
                            await asyncio.sleep(0.5)
                            break
                    except Exception:
                        pass
                raise LoginError(
                    "OTP de Visa rechazado (codigo incorrecto o expirado). "
                    "Ejecuta de nuevo — se enviara un codigo nuevo al mail."
                )
        except LoginError:
            raise
        except Exception:
            pass

        print("  [Visa] OTP enviado, esperando dashboard...")

    # ------------------------------------------------------------------ dashboard

    async def _wait_for_dashboard(self) -> None:
        """Espera a que la URL sea del dashboard de mistarjetas."""
        for _ in range(60):
            await asyncio.sleep(1)
            url = self.page.url

            if "mistarjetas" in url and "login" not in url.lower():
                await self.page.wait_for_load_state("domcontentloaded", timeout=self.config.timeout_ms)
                print(f"  [Visa] Dashboard: {url}")
                return

            # Boton "Ingresar" pendiente del dialog de OTP exitoso
            try:
                btn = self.page.locator('button:has-text("Ingresar")').first
                if await btn.count() > 0 and await btn.is_visible(timeout=500):
                    await btn.click()
                    await asyncio.sleep(2)
                    continue
            except Exception:
                pass

        raise LoginError(
            f"Visa no redirigio al dashboard. URL: {self.page.url}"
        )

    # ------------------------------------------------------------------ session save

    async def _save_session(self) -> None:
        cookies = await self.context.cookies()
        data = {"cookies": cookies}
        self.config.session_file.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
        print(f"  Sesion guardada en {self.config.session_file}")

    # ------------------------------------------------------------------ helpers

    async def _login_form_visible(self) -> bool:
        try:
            btn = self.page.locator('button:has-text("Ingresar")')
            return await btn.is_visible(timeout=1000)
        except Exception:
            return False
