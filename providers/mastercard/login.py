from __future__ import annotations

import asyncio

import httpx
from playwright.async_api import BrowserContext, Page, TimeoutError as PlaywrightTimeout

from core.exceptions import LoginError, NavigationError, ServerUnavailableError
from .config import MastercardConfig

_ERROR_TEXTS = [
    "hubo un error al iniciar",
    "revis\u00e1 tus credenciales",
    "credenciales incorrectas",
]
_SERVER_DOWN_TEXTS = [
    "int\u00e9ntalo m\u00e1s tarde",
    "intent\u00e1 m\u00e1s tarde",
    "intenta m\u00e1s tarde",
    "en este momento",
    "servicio no disponible",
]


async def do_login(page: Page, context: BrowserContext, config: MastercardConfig) -> str:
    """
    Login en misconsultas.com.ar con código TOTP de Authenticator ingresado en consola.

    Flujo:
      1. Llena email + password → click "Ingresar"
      2. Aparece campo de OTP (id=digitosTarjeta) → pedir el codigo por consola
      3. Completa el OTP y lo envia desde el browser
      4. Intercepta la respuesta de /mfa/validation → captura {token, refreshToken}
      5. Espera redireccion al dashboard
    """
    try:
        await page.goto(config.login_url, timeout=config.timeout_ms)
        await page.wait_for_load_state("networkidle", timeout=config.timeout_ms)
        await asyncio.sleep(1)
        await page.wait_for_selector("#email", state="visible", timeout=config.timeout_ms)
        await page.fill("#email", config.email)
        await asyncio.sleep(0.3)
        await page.fill("#passw", config.password)
        await asyncio.sleep(0.3)
    except PlaywrightTimeout as e:
        raise NavigationError(f"Mastercard: timeout cargando formulario de login: {e}") from e

    # Interceptar respuesta del login y del MFA
    token_holder: list[str] = []

    async def on_response(resp):
        url = resp.url
        if resp.status == 200:
            if "/mfa/validation" in url:
                try:
                    data = await resp.json()
                    tok = data.get("token") or data.get("accessToken")
                    if tok:
                        token_holder.append(tok)
                except Exception:
                    pass

    page.on("response", on_response)

    try:
        await page.click('button[type="submit"]')
        await asyncio.sleep(3)
        await page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeout:
        pass

    # Detectar errores post-login
    try:
        body = await page.inner_text("body", timeout=3000)
        body_lower = body.lower()
        for txt in _SERVER_DOWN_TEXTS:
            if txt in body_lower:
                raise ServerUnavailableError(
                    f"Mastercard: servidor no disponible (\"{txt}\"). Reintenta mas tarde."
                )
        for txt in _ERROR_TEXTS:
            if txt in body_lower and "validaci" not in body_lower:
                raise LoginError(
                    "Mastercard: credenciales incorrectas. "
                    "Verificar MASTERCARD_EMAIL y MASTERCARD_PASSWORD en .env"
                )
    except (LoginError, ServerUnavailableError):
        raise
    except Exception:
        pass

    # El campo aparece tras enviar las credenciales.
    try:
        otp_input = page.locator("#digitosTarjeta")
        await otp_input.wait_for(state="visible", timeout=config.timeout_ms)
    except PlaywrightTimeout as e:
        raise LoginError(
            "Mastercard: no aparecio el campo para ingresar el codigo de Authenticator."
        ) from e

    print()
    print("  Mastercard requiere el codigo de tu app Authenticator.")
    otp = input("  Codigo actual de Authenticator: ").strip()
    if not otp:
        raise LoginError("No se ingreso el codigo de Authenticator de Mastercard")

    try:
        await otp_input.fill(otp)
        await otp_input.press("Enter")
    except PlaywrightTimeout as e:
        raise LoginError(
            f"Mastercard: timeout ingresando el codigo de Authenticator: {e}"
        ) from e

    # Esperar hasta 120 segundos a que el token sea capturado o que la URL cambie
    for i in range(120):
        await asyncio.sleep(1)
        if token_holder:
            break
        # Si ya redirigió al dashboard, el MFA se completó
        if "login" not in page.url and "socios" in page.url:
            break

    page.remove_listener("response", on_response)

    if not token_holder:
        # Intentar obtener token de cookies como fallback
        cookies = await context.cookies()
        for c in cookies:
            if c["name"] == "token":
                token_holder.append(c["value"])
                break

    if not token_holder:
        raise LoginError(
            "Mastercard: no se capturo el token JWT. "
            "Puede que el codigo de Authenticator haya expirado o sea incorrecto."
        )

    print(f"  [Mastercard] Token capturado ({len(token_holder[0])} chars)")
    return token_holder[0]
